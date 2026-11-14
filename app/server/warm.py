"""Pre-generate the default plans through a running Kello server, so nobody waits for the first one.

    .venv/bin/python app/server/warm.py                       # all 23 areas and the country, EUR 1M, English and Finnish
    .venv/bin/python app/server/warm.py --areas 21,04         # two areas only
    .venv/bin/python app/server/warm.py --base http://127.0.0.1:8743 --langs en

It only calls the server's own endpoints (the plan is written and stored by the server), so a plan that is
already stored returns at once and the script can be re-run safely. It also touches /api/overview and
/api/optimize for each area so those answers are in memory.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


MAX_WORKERS = 3   # the model pool is shared with everything else on the box
RETRIES = 4       # on a busy pool: wait WAIT_S seconds and ask again, this many times
WAIT_S = 60


def call(base: str, path: str, body: dict | None = None, timeout: float = 600):
    req = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def one_plan(base: str, area: str, budget: int, lang: str, objective: str | None, refresh: bool) -> dict:
    q = {"budget_eur": budget, "lang": lang}
    if objective:
        q["objective"] = objective
    if refresh:
        q["refresh"] = "true"
    t0 = time.time()
    waited = 0
    for attempt in range(RETRIES + 1):
        try:
            p = call(base, f"/api/plan/{area}?{urllib.parse.urlencode(q)}")
            if p.get("generated_by") == "template" and attempt < RETRIES:
                # the writer could not be reached: nothing was stored, so wait and ask again
                time.sleep(WAIT_S); waited += WAIT_S
                continue
            state = "template (Claude not reachable)" if p.get("generated_by") == "template" else "already stored" if p.get("cached") else "written"
            if waited:
                state += f" after waiting {waited} s"
            return {"area": area, "lang": lang, "ok": p.get("generated_by") != "template", "state": state, "s": round(time.time() - t0, 1), "title": p.get("title")}
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode(errors="replace")
            # 503 (or a 502 that carries a rate limit) = the model pool is busy: wait a minute and try again
            busy = e.code in (429, 503, 529) or (e.code == 502 and re.search(r"429|503|529|rate|overload|busy", body, re.I))
            if busy and attempt < RETRIES:
                time.sleep(WAIT_S); waited += WAIT_S
                continue
            return {"area": area, "lang": lang, "ok": False, "state": f"HTTP {e.code}: {body[:200]}", "s": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            return {"area": area, "lang": lang, "ok": False, "state": f"failed: {e}", "s": round(time.time() - t0, 1)}
    return {"area": area, "lang": lang, "ok": False, "state": "gave up", "s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8742")
    ap.add_argument("--areas", default="", help="comma-separated area ids; default: every area and FI")
    ap.add_argument("--langs", default="en,fi")
    ap.add_argument("--budget", type=int, default=1_000_000)
    ap.add_argument("--objective", default=None, help="curative, deaths or gap; default: the server's default")
    ap.add_argument("--workers", type=int, default=2, help="plans written at the same time (at most 3: the model pool is shared)")
    ap.add_argument("--refresh", action="store_true", help="write the plans again even if stored")
    a = ap.parse_args()

    areas = [x.strip() for x in a.areas.split(",") if x.strip()] or [x["id"] for x in call(a.base, "/api/areas")] + ["FI"]
    langs = [x.strip() for x in a.langs.split(",") if x.strip()]
    t0 = time.time()
    call(a.base, "/api/overview")
    for area in areas:
        body = {"scope": area, "budget_eur": a.budget}
        if a.objective:
            body["objective"] = a.objective
        call(a.base, "/api/optimize", body)
    print(f"overview and {len(areas)} optimiser answers in memory ({time.time() - t0:.1f} s)", flush=True)

    jobs = [(area, lang) for area in areas for lang in langs]
    bad = 0
    with cf.ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, a.workers))) as ex:
        futs = [ex.submit(one_plan, a.base, area, a.budget, lang, a.objective, a.refresh) for area, lang in jobs]
        for f in cf.as_completed(futs):
            r = f.result()
            bad += 0 if r["ok"] else 1
            print(f"{r['area']:>3} {r['lang']}  {r['s']:>6.1f} s  {r['state']}" + (f"  | {r['title']}" if r.get("title") else ""), flush=True)
    print(f"{len(jobs) - bad} of {len(jobs)} plans ready in {time.time() - t0:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
