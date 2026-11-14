#!/usr/bin/env python3
"""Record the screen captures of the Kello film from the shot list (film/shots.json).

    .venv/bin/python film/capture/capture.py            # every shot
    .venv/bin/python film/capture/capture.py verify plan   # only these shots
    .venv/bin/python film/capture/capture.py --list

One shot = one browser session = one file pair in $KELLO_FILM_OUT/public/captures/:
  <id>.mp4   the page, constant frame rate, no cursor (the film draws the cursor itself, so it stays smooth)
  <id>.json  duration, cursor track, clicks, named marks with the box of the element they point at,
             and the JSON of any API call the shot asked to keep (the film reads the live web check from it)

The film never hard-codes a pixel position inside a capture: zooms follow the marks. When the UI changes,
edit the targets in shots.json, run this again, then ./render.sh.
"""
import asyncio
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

SLOWMO_JS = """(r) => { const w = window;
  if (!w.__film_pn) { w.__film_pn = performance.now.bind(performance); w.__film_raf = w.requestAnimationFrame.bind(w);
    w.__film_seg = {real: w.__film_pn(), virt: w.__film_pn(), r: 1};
    performance.now = () => { const s = w.__film_seg; return s.virt + (w.__film_pn() - s.real) * s.r; };
    w.requestAnimationFrame = (cb) => w.__film_raf(() => cb(performance.now())); }
  const v = performance.now(); w.__film_seg = {real: w.__film_pn(), virt: v, r}; }"""

FILM = Path(__file__).resolve().parent.parent
OUT = Path(os.environ["KELLO_FILM_OUT"]) if os.environ.get("KELLO_FILM_OUT") else FILM / "out"
CAP = OUT / "public" / "captures"
TMP = OUT / "tmp"


def ease(t):
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


class Shot:
    def __init__(self, page, cdp, spec, cfg):
        self.page, self.cdp, self.spec, self.cfg = page, cdp, spec, cfg
        self.t0 = None
        self.frames = []  # (t, path)
        self.cursor = []  # [t, x, y]
        self.clicks = []
        self.marks = []
        self.api = {}
        self.texts = {}
        self.pos = [cfg["viewport"][0] * 0.55, cfg["viewport"][1] * 0.6]
        self.dir = TMP / spec["id"]
        self.n = 0
        self.skew = 0.0
        self.stepping = False
        self.last_step_t = -1.0
        self.slow = []  # [film t, playback rate]: slow-motion stretches (the film plays them back faster)
        self.recording = False

    def now(self):
        # film time: wall time minus the extra wall time that frame-by-frame scrolls took (0 before recording starts,
        # so `before` steps may move, click and mark too)
        return 0.0 if self.t0 is None else time.time() - self.t0 - self.skew

    # ---- targets: {"css": ...} | {"text": ...} | {"role": ..., "name": ...}, optional "nth" and "has_text",
    #      or {"any": [targets]} = the first one that is on the page (old UI and new UI side by side)
    def _loc(self, tg):
        if "css" in tg:
            loc = self.page.locator(tg["css"])
        elif "role" in tg:
            loc = self.page.get_by_role(tg["role"], name=tg.get("name"), exact=tg.get("exact", False))
        else:
            loc = self.page.get_by_text(tg["text"], exact=tg.get("exact", False))
        if "has_text" in tg:
            loc = loc.filter(has_text=tg["has_text"])
        return loc.nth(tg.get("nth", 0))

    async def find(self, tg, timeout=8000, optional=False):
        cands = tg["any"] if "any" in tg else [tg]
        end = time.time() + timeout / 1000
        while True:
            for c in cands:
                loc = self._loc(c)
                try:
                    if await loc.count() and await loc.is_visible():
                        return loc
                except Exception:
                    pass
            if time.time() > end:
                if optional or tg.get("optional"):
                    return None
                raise RuntimeError(f"shot {self.spec['id']}: target not found: {json.dumps(tg)}")
            await asyncio.sleep(0.15)

    async def box(self, loc, closest=None):
        if closest:  # the box of the nearest ancestor matching a selector (a whole row or card, not just its label)
            b = await loc.evaluate("(el, sel) => { const r = (el.closest(sel) || el).getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }", closest)
        else:
            b = await loc.bounding_box()
        return [round(b["x"]), round(b["y"]), round(b["width"]), round(b["height"])] if b else None

    # ---- steps
    async def move_to(self, x, y, ms=900):
        x0, y0 = self.pos
        d = math.hypot(x - x0, y - y0)
        ms = max(250, min(ms, 250 + d * 1.4)) if ms else 0
        n = max(1, int(ms / 16))
        # slight arc so the pointer does not travel like a ruler
        bx, by = (y - y0) * 0.06, -(x - x0) * 0.06
        for i in range(1, n + 1):
            t = ease(i / n)
            k = math.sin(math.pi * t)
            px, py = x0 + (x - x0) * t + bx * k, y0 + (y - y0) * t + by * k
            await self.page.mouse.move(px, py)
            if self.t0 is not None:
                self.cursor.append([round(self.now(), 3), round(px, 1), round(py, 1)])
            await asyncio.sleep(0.016)
        self.pos = [x, y]

    async def move(self, st):
        loc = await self.find(st["move"], st.get("timeout", 8000))
        if not loc:
            return None
        await self.scroll_into_view(loc, st.get("scroll_ms", 900))
        b = await loc.bounding_box()
        at = st.get("at", [0.5, 0.5])
        await self.move_to(b["x"] + b["width"] * at[0], b["y"] + b["height"] * at[1], st.get("ms", 900))
        return loc

    async def scroll_into_view(self, loc, ms=900, block=0.42):
        """Scroll the nearest scrolling ancestor so the element sits at `block` of the viewport height."""
        plan = await loc.evaluate(
            """(el, block) => {
                document.querySelectorAll('[data-film-sc]').forEach((e) => e.removeAttribute('data-film-sc'));
                let sc = el.parentElement;
                while (sc && !(/(auto|scroll)/.test(getComputedStyle(sc).overflowY) && sc.scrollHeight > sc.clientHeight + 4)) sc = sc.parentElement;
                const win = !sc || sc === document.body || sc === document.documentElement;
                const r = el.getBoundingClientRect();
                const vh = win ? innerHeight : sc.clientHeight;
                const top0 = win ? scrollY : sc.scrollTop;
                const base = win ? 0 : sc.getBoundingClientRect().top;
                if (r.top - base > vh * 0.12 && r.bottom - base < vh * 0.88) return null;
                const max = (win ? document.documentElement.scrollHeight : sc.scrollHeight) - vh;
                const to = Math.max(0, Math.min(max, top0 + (r.top - base) + r.height / 2 - vh * block));
                if (Math.abs(to - top0) < 4) return null;
                if (!win) sc.setAttribute('data-film-sc', '1');
                return {from: top0, to};
            }""",
            block,
        )
        if plan:
            await self.scroll_steps(plan["from"], plan["to"], ms)

    async def scroll_steps(self, y0, y1, ms):
        """A scroll is recorded frame by frame (one screenshot per film frame), so it is smooth at full
        resolution however slow the machine is. The wall time it takes is taken out of the film clock."""
        fps = self.cfg.get("fps", 60)
        n = max(2, round(ms / 1000 * fps))
        live = self.t0 is not None
        w0 = time.time()
        t_start = self.now() if live else 0
        self.stepping = True
        for i in range(1, n + 1):
            y = y0 + (y1 - y0) * ease(i / n)
            await self.page.evaluate("(y) => { const sc = document.querySelector('[data-film-sc]'); sc ? (sc.scrollTop = y) : scrollTo(0, y); }", y)
            if live:
                shot = await self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": self.cfg.get("jpeg_quality", 90)})
                self.save(t_start + i / fps, shot["data"])
        if live:
            self.last_step_t = t_start + n / fps
            self.skew += (time.time() - w0) - n / fps
        self.stepping = False

    async def run_step(self, st):
        if "wait" in st:
            await asyncio.sleep(st["wait"] / 1000)
        elif "wait_for" in st:
            await self.find(st["wait_for"], st.get("timeout", 30000))
        elif "wait_gone" in st:
            end = time.time() + st.get("timeout", 120000) / 1000
            while time.time() < end:
                gone = True
                for c in st["wait_gone"].get("any", [st["wait_gone"]]):
                    loc = self._loc(c)
                    if await loc.count() and await loc.is_visible():
                        gone = False
                if gone:
                    break
                await asyncio.sleep(0.25)
        elif "wait_api" in st:
            end = time.time() + st.get("timeout", 120000) / 1000
            while st["wait_api"] not in self.api and time.time() < end:
                await asyncio.sleep(0.25)
        elif "move" in st:
            await self.move(st)
        elif "click" in st:
            loc = await self.move({"move": st["click"], **{k: v for k, v in st.items() if k != "click"}})
            if loc:
                await asyncio.sleep(st.get("pause", 280) / 1000)
                if self.t0 is not None:
                    self.clicks.append(round(self.now(), 3))
                await self.page.mouse.down()
                await asyncio.sleep(0.07)
                await self.page.mouse.up()
        elif "scroll" in st:
            loc = await self.find(st["scroll"], st.get("timeout", 8000))
            if loc:
                await self.scroll_into_view(loc, st.get("ms", 1200), st.get("block", 0.42))
        elif "scroll_by" in st:
            await self.page.evaluate("() => document.querySelectorAll('[data-film-sc]').forEach((e) => e.removeAttribute('data-film-sc'))")
            y0 = await self.page.evaluate("scrollY")
            await self.scroll_steps(y0, y0 + st["scroll_by"], st.get("ms", 1200))
        elif "goto" in st:
            await self.page.evaluate("(h) => { location.hash = h }", st["goto"])
        elif "eval" in st:
            await self.page.evaluate(st["eval"])
        elif "slowmo" in st:
            # Slow the page's clock so a short animation is recorded with many frames on a busy machine: CSS
            # animations and transitions via CDP, requestAnimationFrame / performance.now by a virtual clock.
            # The capture stores the stretch (meta "slowmo"); the film maps it back to real speed with marks.
            rate = float(st["slowmo"])
            await self.cdp.send("Animation.enable")
            await self.cdp.send("Animation.setPlaybackRate", {"playbackRate": rate})
            await self.page.evaluate(SLOWMO_JS, rate)
            if self.t0 is not None:
                self.slow.append([round(self.now(), 3), rate])
        elif "expect" in st:
            loc = await self.find(st["expect"], st.get("timeout", 8000))
            txt = " ".join((await loc.inner_text()).split())
            for want in st.get("contains", []):
                if want not in txt:
                    raise RuntimeError(f"shot {self.spec['id']}: expected {want!r} in {txt[:200]!r} (the film's script says it)")
            self.texts[st.get("as", f"t{len(self.texts)}")] = txt
        elif "mark" in st:
            pass
        else:
            raise RuntimeError(f"unknown step {st}")
        # any step can carry a mark: {"mark": "name", "box": target}
        if "mark" in st:
            m = {"name": st["mark"], "t": round(self.now(), 3)}
            tg = st.get("box") or st.get("click") or st.get("move") or st.get("scroll") or st.get("wait_for") or st.get("expect")
            if tg:
                loc = await self.find(tg, 3000, optional=True)
                if loc:
                    m["box"] = await self.box(loc, st.get("closest"))
            if self.t0 is not None:
                self.marks.append(m)
                print(f"   mark {m}")

    # ---- recording
    async def on_frame(self, ev):
        try:
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:
            pass
        if self.t0 is None or self.stepping:
            return
        t = ev["metadata"]["timestamp"] - self.t0 - self.skew
        if t < 0 or t <= self.last_step_t:
            return
        self.save(t, ev["data"])

    async def poll(self):
        """The screencast sends frames only when the page repaints, and on a loaded machine sometimes none for
        seconds: fill any gap over 0.25 s with a screenshot, so a still page and a slow animation both have frames."""
        while self.recording:
            await asyncio.sleep(0.08)
            if self.stepping or not self.recording:
                continue
            t = self.now()
            last = max([f[0] for f in self.frames[-3:]], default=-1.0)
            if t - last < 0.25 or t <= self.last_step_t:
                continue
            try:
                shot = await self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": self.cfg.get("jpeg_quality", 90)})
            except Exception:
                continue
            if not self.stepping and t > self.last_step_t:
                self.save(t, shot["data"])

    def save(self, t, b64):
        p = self.dir / f"f{self.n:06d}.jpg"
        self.n += 1
        p.write_bytes(base64.b64decode(b64))
        self.frames.append((t, p))

    async def on_response(self, resp):
        for pat in self.spec.get("keep_api", []):
            if pat in resp.url:
                try:
                    self.api[pat] = {"t": round(self.now(), 3) if self.t0 else 0, "url": resp.url.split("://", 1)[-1].split("/", 1)[-1], "json": await resp.json()}
                    print(f"   kept {pat} at {self.api[pat]['t']} s")
                except Exception as e:
                    print(f"   could not keep {pat}: {e}")

    async def run(self):
        sp, cfg = self.spec, self.cfg
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.page.on("response", lambda r: asyncio.ensure_future(self.on_response(r)))
        await self.page.goto(cfg["base"] + "/" + sp.get("url", ""))
        for st in sp.get("before", []):  # not recorded: get the page into its starting state
            await self.run_step(st)
        await self.page.mouse.move(*self.pos)
        self.cdp.on("Page.screencastFrame", lambda ev: asyncio.ensure_future(self.on_frame(ev)))
        w, h = cfg["viewport"]
        s = cfg.get("scale", 1)
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": cfg.get("jpeg_quality", 90), "maxWidth": w * s, "maxHeight": h * s, "everyNthFrame": 1})
        await asyncio.sleep(0.3)
        self.t0 = time.time()
        self.cursor.append([0, *self.pos])
        # nudge so the first frame is delivered even on a still page
        await self.page.evaluate("() => { const d = document.createElement('i'); d.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:.01'; document.body.appendChild(d); let k = 0; setInterval(() => { d.style.opacity = (k++ % 2) ? '.01' : '.02' }, 250); }")
        self.recording = True
        poller = asyncio.ensure_future(self.poll())
        try:
            for st in sp["steps"]:
                await self.run_step(st)
        finally:
            self.recording = False
            await poller
        dur = self.now()
        await asyncio.sleep(0.3)
        await self.cdp.send("Page.stopScreencast")
        await asyncio.sleep(0.2)
        return self.encode(dur)

    def encode(self, dur):
        sp, cfg = self.spec, self.cfg
        fr = [(t, p) for t, p in sorted(self.frames) if t <= dur + 0.05]
        if not fr:
            raise RuntimeError(f"shot {sp['id']}: no frames")
        lst = self.dir / "list.txt"
        with open(lst, "w") as f:
            for i, (t, p) in enumerate(fr):
                nxt = fr[i + 1][0] if i + 1 < len(fr) else dur
                start = 0 if i == 0 else t
                f.write(f"file '{p}'\nduration {max(0.001, nxt - start):.4f}\n")
            f.write(f"file '{fr[-1][1]}'\n")
        CAP.mkdir(parents=True, exist_ok=True)
        mp4 = CAP / f"{sp['id']}.mp4"
        fps = cfg.get("fps", 60)
        (w, h), sc = cfg["viewport"], cfg.get("scale", 1)
        # every frame a keyframe (all-intra): Remotion extracts frames of these 3x captures in parallel and must never decode a GOP
        subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-vf", f"fps={fps},scale={w * sc}:{h * sc}:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-g", "1", "-movflags", "+faststart", str(mp4)], check=True)
        gaps = sorted((fr[i + 1][0] - fr[i][0] for i in range(len(fr) - 1)), reverse=True)
        meta = {
            "id": sp["id"], "file": f"captures/{sp['id']}.mp4", "duration": round(dur, 3), "fps": fps,
            "viewport": cfg["viewport"], "scale": cfg.get("scale", 1), "base": cfg["base"], "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_frames": len(fr), "source_fps_mean": round(len(fr) / dur, 1),
            "cursor": self.cursor, "clicks": self.clicks, "marks": self.marks, "slowmo": self.slow, "api": self.api, "texts": self.texts,
        }
        (CAP / f"{sp['id']}.json").write_text(json.dumps(meta, ensure_ascii=False))
        # the film imports the metadata (text, small) from the repo; the video stays outside it
        d = FILM / "src" / "data" / "captures"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sp['id']}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        shutil.rmtree(self.dir, ignore_errors=True)
        print(f" -> {mp4}  {dur:.1f} s, {len(fr)} source frames ({meta['source_fps_mean']} fps mean, longest still {gaps[0] if gaps else 0:.1f} s)")
        return meta


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cfg = json.loads((FILM / "shots.json").read_text())
    if os.environ.get("KELLO_BASE"):
        cfg["base"] = os.environ["KELLO_BASE"]
    shots = [s for s in cfg["shots"] if not args or s["id"] in args]
    if "--list" in sys.argv:
        for s in cfg["shots"]:
            print(f"{s['id']:14} {s.get('scene', ''):12} {s.get('what', '')}")
        return
    unknown = set(args) - {s["id"] for s in cfg["shots"]}
    if unknown:
        raise SystemExit(f"no such shot: {', '.join(sorted(unknown))}")
    failed = []
    async with async_playwright() as p:
        # --force-device-scale-factor (not the emulated one) is what makes the screencast come out at 2x
        browser = await p.chromium.launch(args=["--force-color-profile=srgb", "--hide-scrollbars", "--font-render-hinting=none", f"--force-device-scale-factor={cfg.get('scale', 1)}"])
        for sp in shots:
            print(f"shot {sp['id']}: {sp.get('what', '')}")
            w, h = cfg["viewport"]
            ctx = await browser.new_context(viewport={"width": w, "height": h}, locale="en-GB", timezone_id="Europe/Helsinki")
            page = await ctx.new_page()
            cdp = await ctx.new_cdp_session(page)
            try:
                await Shot(page, cdp, sp, cfg).run()
            except Exception as e:
                failed.append(sp["id"])
                print(f" !! {sp['id']} failed: {e}")
                try:
                    await page.screenshot(path=str(TMP / f"{sp['id']}-failed.png"))
                    print(f"    see {TMP / (sp['id'] + '-failed.png')}")
                except Exception:
                    pass
            await ctx.close()
        await browser.close()
    if failed:
        raise SystemExit(f"failed: {', '.join(failed)} (the old capture of a failed shot is kept)")


if __name__ == "__main__":
    asyncio.run(main())
