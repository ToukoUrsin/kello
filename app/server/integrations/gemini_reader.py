"""Gemini as the reader for sources that have no API: PDF reports, HTML factsheets
with charts, and web apps. Returns cited, structured numbers.

    read_report(source, hint="", mime=None) -> {document, extracted, model, notes}

Pass 1: Gemini reads the whole document (native PDF input, or full-page screenshots
plus page text plus the data behind rendered charts) into a response schema.
Pass 2: Gemini re-reads only the cited page / screenshot and confirms each number;
values it cannot confirm are dropped (mismatch) or flagged (`verified: false`).

Env: GEMINI_API_KEY; optional GEMINI_READER_MODEL.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

DEFAULT_MODEL = "gemini-4-hydrogen"  # when a person is waiting on the page: the fastest Gemini 4, 65k output
OFFLINE_MODEL = "gemini-4-carbon"    # for reads done ahead of time (build_raw_reads, build_chart_read): the strongest
_OUT_LIMIT = {"gemini-4-carbon": 32768}  # output tokens the model allows; a long read continues in rounds (_extract)
ROOT = Path(__file__).resolve().parents[3]
AREAS_PATH = ROOT / "data" / "processed" / "areas.json"
OUT_JSONL = ROOT / "data" / "processed" / "gemini_extracted.jsonl"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
TILE_W, TILE_H, MAX_TILES, MAX_FIGURES = 1280, 1600, 40, 40

INDICATOR_KEYS = {
    "lung_incidence_n": "number of new lung cancer cases (C33-C34) in the area and period",
    "lung_incidence_per_100k": "lung cancer incidence rate per 100 000 (state crude or age-standardised in the label)",
    "lung_deaths_n": "number of lung cancer deaths",
    "lung_deaths_per_100k": "lung cancer mortality rate per 100 000",
    "lung_stage_known_pct": "share of cases with stage at diagnosis recorded",
    "lung_stage_1_2_pct": "share diagnosed at stage I-II / localised",
    "lung_stage_3_pct": "share diagnosed at stage III / locally advanced",
    "lung_stage_4_pct": "share diagnosed at stage IV / metastatic",
    "lung_stage_unknown_pct": "share with unknown stage",
    "lung_histology_defined_pct": "share with a defined histology (cell type known / microscopically verified)",
    "lung_histology_unknown_pct": "share with unknown cell type",
    "lung_curative_intent_pct": "share of patients who received curative-intent treatment",
    "lung_surgery_pct": "share of patients who had surgery",
    "lung_radiotherapy_pct": "share who had radiotherapy",
    "lung_drug_therapy_pct": "share who had systemic drug therapy",
    "lung_no_treatment_pct": "share with no cancer treatment recorded",
    "lung_mdt_recorded_pct": "share with a multidisciplinary team (MDT) meeting recorded",
    "lung_days_referral_to_treatment": "days from referral to start of treatment (state median/mean in label)",
    "lung_days_diagnosis_to_treatment": "days from diagnosis to start of treatment",
    "lung_survival_1y_pct": "1-year survival (state relative/observed in label)",
    "lung_survival_5y_pct": "5-year survival",
}


class _Doc(BaseModel):
    title: str
    publisher: str
    pages: int


class _Item(BaseModel):
    indicator_guess: str
    label: str
    label_en: str
    area: str
    area_id: Optional[str] = None
    value: float
    unit: str
    period: str
    page: int
    quote: str
    read_from: str  # text | table | chart
    confidence: float


class _Extraction(BaseModel):
    document: _Doc
    extracted: list[_Item]
    notes: str


class _Check(BaseModel):
    i: int
    status: str  # confirmed | mismatch | not_visible
    value_seen: Optional[float] = None
    note: str


class _Checks(BaseModel):
    checks: list[_Check]


# ----------------------------------------------------------------- areas

_SUFFIXES = (
    "hyvinvointialue", "hyvinvointialueen", "wellbeing services county", "välfärdsområde",
    "sairaanhoitopiiri", "sairaanhoitopiirin", "hospital district", "sjukvårdsdistrikt",
    "maakunta", "region", "hva", "shp", "kaupunki", "city of",
)
# Old hospital districts / other spellings that map 1:1 to a county.
_EXTRA_ALIASES = {
    "pirkanmaa": "08", "varsinais-suomi": "05", "satakunta": "06", "kanta-häme": "07",
    "päijät-häme": "09", "kymenlaakso": "10", "etelä-karjala": "11", "eksote": "11",
    "etelä-savo": "12", "eloisa": "12", "pohjois-savo": "13", "pohjois-karjala": "14",
    "siun sote": "14", "keski-suomi": "15", "etelä-pohjanmaa": "16", "pohjanmaa": "17",
    "vaasa": "17", "vaasan": "17", "österbotten": "17", "keski-pohjanmaa": "18",
    "soite": "18", "pohjois-pohjanmaa": "19", "pohde": "19", "kainuu": "20", "lappi": "21",
    "lapland": "21", "helsingin kaupunki": "90", "helsingfors": "90", "helsinki": "90",
    "åland": "91", "ahvenanmaa": "91", "itä-uusimaa": "01", "keski-uusimaa": "02",
    "keusote": "02", "länsi-uusimaa": "03", "luvn": "03", "vantaa-kerava": "04",
    "vantaa ja kerava": "04", "vake": "04", "varha": "05", "pirha": "08", "kymsote": "10",
    "koko maa": "FI", "suomi": "FI", "finland": "FI", "whole country": "FI", "koko suomi": "FI",
    "hela landet": "FI", "kaikki": "FI",
}
_YTA = {
    "hus": "HUS", "etelä-suomi": "HUS", "etelä-suomen": "HUS", "helsinki university hospital": "HUS",
    "tyks": "TYKS", "länsi-suomi": "TYKS", "länsi-suomen": "TYKS", "tays": "TAYS",
    "sisä-suomi": "TAYS", "sisä-suomen": "TAYS", "kys": "KYS", "itä-suomi": "KYS",
    "itä-suomen": "KYS", "oys": "OYS", "pohjois-suomi": "OYS", "pohjois-suomen": "OYS",
}


def _norm(s: str) -> str:
    s = (s or "").lower().replace("–", "-").replace("‑", "-")
    for suf in _SUFFIXES:
        s = s.replace(suf, " ")
    s = re.sub(r"\b(yhteistyöalue|yta|collaborative area)\b", " ", s)
    return re.sub(r"[^a-zåäö\- ]+", " ", s).strip(" -").replace("  ", " ").strip()


_alias_cache: dict | None = None


def load_areas() -> list[dict]:
    return json.loads(AREAS_PATH.read_text())


def _aliases() -> dict:
    global _alias_cache
    if _alias_cache is None:
        m: dict[str, str] = {}
        for a in load_areas():
            for k in ("name_fi", "name_sv", "name_en", "short_fi", "short_en"):
                v = _norm(a.get(k, ""))
                if v:
                    m[v] = a["id"]
                    if k == "short_fi" and v.endswith("n"):
                        m.setdefault(v[:-1], a["id"])  # genitive -> nominative-ish
        for k, v in _EXTRA_ALIASES.items():
            m[_norm(k)] = v
        _alias_cache = m
    return _alias_cache


def map_area(name: str, model_id: str | None = None) -> str | None:
    """Map an area name as written in a document to our area id ("01".."21","90","91","FI",
    or "yta:HUS" style for collaborative areas). None when unknown."""
    valid = {a["id"] for a in load_areas()} | {"FI"}
    n = _norm(name)
    low = (name or "").lower()
    if n in _YTA and ("yhteistyö" in low or "yta" in low or n in ("hus", "tyks", "tays", "kys", "oys")):
        return "yta:" + _YTA[n]
    if n in _aliases():
        return _aliases()[n]
    if n in _YTA:
        return "yta:" + _YTA[n]
    if model_id:
        mid = model_id.strip()
        if mid in valid or re.fullmatch(r"yta:(HUS|TYKS|TAYS|KYS|OYS)", mid):
            return mid
    return None


# ----------------------------------------------------------------- fetching

def _ensure_display() -> bool:
    if os.environ.get("DISPLAY"):
        return True
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        return False
    disp = f":{90 + os.getpid() % 400}"
    subprocess.Popen([xvfb, disp, "-screen", "0", "1400x1800x24", "-nolisten", "tcp"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = Path(f"/tmp/.X11-unix/X{disp[1:]}")
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.1)
    os.environ["DISPLAY"] = disp
    return True


_REGISTRY_APP = "tilastot.syoparekisteri.fi/syovat"
_CHALLENGE = re.compile(r"just a moment|turvatarkistuksen|checking your browser|cf-chall", re.I)

_CHARTS_JS = """
() => [...document.querySelectorAll('.js-plotly-plot')].map(el => {
  const r = el.getBoundingClientRect(); const lay = el.layout || {};
  const tt = v => (v && typeof v === 'object') ? (v.text || '') : (v || '');
  const arr = a => { try { return Array.from(a || []).slice(0, 80); } catch (e) { return []; } };
  let sec = ''; let n = el;
  while (n && !sec) { let p = n.previousElementSibling;
    while (p && !sec) { if (/^H[1-5]$/.test(p.tagName)) sec = p.innerText; else { const h = p.querySelectorAll ? p.querySelectorAll('h1,h2,h3,h4,h5') : []; if (h.length) sec = h[h.length-1].innerText; } p = p.previousElementSibling; }
    n = n.parentElement; }
  let cap = ''; const fig = el.closest('.figure, figure, .cell, .quarto-figure'); if (fig) { const c = fig.querySelector('figcaption, .caption, .figure-caption'); if (c) cap = c.innerText; }
  return { y: r.top + window.scrollY, h: r.height, section: sec.slice(0, 200), caption: cap.slice(0, 300),
    title: String(tt(lay.title)).slice(0, 300), xaxis: String(tt(lay.xaxis && lay.xaxis.title)), yaxis: String(tt(lay.yaxis && lay.yaxis.title)),
    traces: (el.data || []).map(t => ({ name: t.name, type: t.type, orientation: t.orientation, x: arr(t.x), y: arr(t.y),
      text: Array.isArray(t.text) ? t.text.slice(0, 80) : t.text })) };
})
"""


_EXPAND_JS = """
() => { let n = 0;
  document.querySelectorAll('.tab-pane, [role=tabpanel]').forEach(p => {
    const hidden = getComputedStyle(p).display === 'none' || !p.classList.contains('active'); if (hidden) n++;
    p.classList.add('active', 'show', 'in'); p.style.display = 'block'; p.style.opacity = '1'; p.style.visibility = 'visible'; p.removeAttribute('hidden');
    const id = p.id; let tab = null;
    try { tab = id && document.querySelector('[href="#' + CSS.escape(id) + '"], [data-bs-target="#' + CSS.escape(id) + '"], [aria-controls="' + CSS.escape(id) + '"]'); } catch (e) {}
    if (tab && !p.querySelector(':scope > .__tabtitle')) { const h = document.createElement('div'); h.className = '__tabtitle';
      h.textContent = '[Tab: ' + tab.innerText.trim() + ']'; h.style.cssText = 'font:bold 17px sans-serif;color:#a00;margin:10px 0 4px'; p.prepend(h); }
  });
  document.querySelectorAll('details').forEach(d => { if (!d.open) { d.open = true; n++; } });
  window.dispatchEvent(new Event('resize')); return n; }
"""

# Tables rendered inside shadow roots (R flextable) are invisible to innerText: read them as text.
_SHADOW_TABLES_JS = r"""
() => { let out = '';
  document.querySelectorAll('*').forEach(h => { if (!h.shadowRoot) return;
    h.shadowRoot.querySelectorAll('table').forEach(t => {
      const fig = h.closest('figure, .figure, .quarto-float'); const cap = fig && fig.querySelector('figcaption, .caption');
      const y = h.getBoundingClientRect().top + window.scrollY;
      out += '\n\n[TABLE on screenshot ' + (Math.floor(y / 1600) + 1) + ': ' + (cap ? cap.innerText.trim() : '') + ']\n';
      t.querySelectorAll('tr').forEach(tr => { out += [...tr.querySelectorAll('th,td')].map(c => c.innerText.replace(/\s+/g, ' ').trim()).join(' | ') + '\n'; });
    }); });
  return out; }
"""

_FIGURES_JS = """
async () => { const out = [];
  for (const img of document.querySelectorAll('img')) {
    if (img.naturalWidth < 500 || img.naturalHeight < 300) continue;
    const r = img.getBoundingClientRect(); if (r.width < 200) continue;
    const fig = img.closest('.figure, figure, .quarto-figure, .cell-output-display');
    const capEl = fig && fig.querySelector('.caption, figcaption, .figure-caption');
    const pane = img.closest('.tab-pane, [role=tabpanel]'); const tt = pane && pane.querySelector(':scope > .__tabtitle');
    let b64 = null;
    try { if (img.src.startsWith('data:')) b64 = img.src.split(',')[1];
      else { const b = await (await fetch(img.src)).blob(); b64 = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(',')[1]); fr.readAsDataURL(b); }); } } catch (e) {}
    const mime = img.src.startsWith('data:') ? img.src.slice(5, img.src.indexOf(';')) : 'image/png';
    out.push({ y: r.top + window.scrollY, caption: ((capEl ? capEl.innerText : img.alt) || '').slice(0, 400), tab: tt ? tt.innerText : '', mime, w: img.naturalWidth, h: img.naturalHeight, b64 });
  } return out; }
"""


_CONSENT_JS = r"""
() => { const box = /cookie|consent|cmp|onetrust|cybot|gdpr|evaste/i;
  const no = /^(decline all|reject all|deny all|only necessary|necessary only|hylkää kaikki|kiellä kaikki|vain välttämättömät|hyväksy vain välttämättömät|avvisa alla|endast nödvändiga)$/i;
  const yes = /^(accept all|allow all|accept|agree|ok|hyväksy kaikki|salli kaikki|hyväksy|godkänn alla|acceptera alla)$/i;
  const inBox = el => { for (let n = el; n && n !== document.body; n = n.parentElement) {
      const id = (n.id || '') + ' ' + (typeof n.className === 'string' ? n.className : '') + ' ' + (n.getAttribute('aria-label') || '');
      if (box.test(id) || n.getAttribute('role') === 'dialog' || n.tagName === 'DIALOG') return true; } return false; };
  const btns = [...document.querySelectorAll('button, a[role=button], input[type=button], input[type=submit]')]
      .filter(b => b.offsetParent !== null && inBox(b));
  const label = b => (b.innerText || b.value || '').replace(/\s+/g, ' ').trim();
  const pick = btns.find(b => no.test(label(b))) || btns.find(b => yes.test(label(b)));
  if (pick) { pick.click(); return 'clicked: ' + label(pick); }
  let hid = 0;   // no button we recognise: take the banner out of the picture
  document.querySelectorAll('[id], [class]').forEach(n => { const id = (n.id || '') + ' ' + (typeof n.className === 'string' ? n.className : '');
    if (box.test(id)) { const cs = getComputedStyle(n); if (cs.position === 'fixed' || cs.position === 'sticky') { n.style.display = 'none'; hid++; } } });
  return hid ? 'hidden: ' + hid : ''; }
"""


def _dismiss_consent(page) -> str:
    """Close a cookie-consent dialog (it covers the content on the screenshots Gemini reads)."""
    try:
        done = page.evaluate(_CONSENT_JS)
        if done:
            page.wait_for_timeout(700)
        return done or ""
    except Exception:
        return ""


def _all_text_len(page) -> int:
    n = 0
    for fr in page.frames:
        try:
            n += int(fr.evaluate("document.body ? document.body.innerText.length : 0"))
        except Exception:
            continue
    return n


def _pending_iframes(page) -> int:
    """Visible iframes whose document has not arrived yet. The statistics app on cancerregistry.fi
    answers about 10 s after its parent page went idle; until then the frame is blank."""
    try:
        srcs = page.evaluate("""() => [...document.querySelectorAll('iframe[src]')].filter(f => /^https?:/.test(f.src)
            && f.getBoundingClientRect().width > 200 && getComputedStyle(f).display !== 'none').map(f => f.src.split('#')[0].split('?')[0])""")
    except Exception:
        return 1  # the page is navigating
    loaded = [fr.url.split("#")[0].split("?")[0] for fr in page.frames if fr != page.main_frame]
    return sum(1 for s in srcs if s not in loaded)


def _settle(page, quiet_s: float = 1.5, max_s: float = 15.0, frames_max_s: float = 25.0) -> float:
    """Wait until every visible iframe has loaded and the text of the page AND of every frame has
    stopped changing: embedded apps load long after the parent page is idle, and count-up
    animations change numbers for a second or two. Returns the seconds waited."""
    t0 = time.time()
    last, same_since = -1, time.time()
    while True:
        waited = time.time() - t0
        pending = _pending_iframes(page) if waited < frames_max_s else 0
        if waited >= max_s and not pending:
            break
        n = _all_text_len(page)
        if n != last:
            last, same_since = n, time.time()
        elif not pending and time.time() - same_since >= quiet_s:
            break
        page.wait_for_timeout(400)
    return round(time.time() - t0, 1)


def _frames(page) -> list[dict]:
    """Text and chart data of embedded frames (innerText of the top document does not include them)."""
    out = []
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            text = fr.evaluate("document.body ? document.body.innerText : ''") or ""
        except Exception:
            continue
        if not fr.url.startswith("http"):
            continue
        top = 0.0
        try:
            box = fr.frame_element().bounding_box()
            top = (box or {}).get("y", 0.0) + float(page.evaluate("window.scrollY"))
        except Exception:
            pass
        try:
            charts = fr.evaluate(_CHARTS_JS)
        except Exception:
            charts = []
        for c in charts:
            c["y"] = c.get("y", 0) + top
        out.append({"url": fr.url, "text": text, "charts": charts, "top": top})
    return out


def _open_browser(p):
    headed = _ensure_display()
    kw: dict = {"headless": not headed, "args": ["--disable-blink-features=AutomationControlled"],
                "env": dict(os.environ)}
    if headed and (shutil.which("google-chrome") or shutil.which("google-chrome-stable")):
        kw["channel"] = "chrome"
    browser = p.chromium.launch(**kw)
    ctx = browser.new_context(user_agent=UA, locale="fi-FI", viewport={"width": TILE_W, "height": TILE_H})
    return browser, ctx


def _wait_challenge(page, seconds: float = 25.0) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if not _CHALLENGE.search(page.title() + " " + page.evaluate("document.body ? document.body.innerText.slice(0,400) : ''")):
                return
        except Exception:
            pass
        page.wait_for_timeout(1000)


def browser_fetch_bytes(url: str) -> bytes:
    """Download a file through a real browser session (passes bot checks that block curl)."""
    from urllib.parse import urlsplit

    from playwright.sync_api import sync_playwright

    u = urlsplit(url)
    with sync_playwright() as p:
        browser, ctx = _open_browser(p)
        try:
            page = ctx.new_page()
            page.goto(f"{u.scheme}://{u.netloc}/", wait_until="domcontentloaded", timeout=60000)
            _wait_challenge(page)
            b64 = page.evaluate(
                """async (url) => { const r = await fetch(url, {credentials:'include'}); if (!r.ok) throw new Error('HTTP '+r.status);
                const b = await r.blob(); return await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(',')[1]); fr.readAsDataURL(b); }); }""",
                url,
            )
            return base64.b64decode(b64)
        finally:
            browser.close()


def render_page(url: str, actions=None, settle_ms: int = 3500) -> dict:
    """Render an HTML page or web app. Returns {title, text, tiles:[png], charts:[...], links:[...]}.
    `actions(page)` may drive the app (click, select) before capture."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, ctx = _open_browser(p)
        try:
            page = ctx.new_page()
            for attempt in (1, 2, 3):  # ERR_NETWORK_CHANGED and similar are transient
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    page.wait_for_timeout(2500)
            _wait_challenge(page)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1200)
            consent = _dismiss_consent(page)
            waited = _settle(page, max_s=max(6.0, settle_ms / 1000 * 4))
            if actions:
                actions(page)
                page.wait_for_timeout(settle_ms)
                _settle(page, max_s=8.0)
            try:
                n_hidden = page.evaluate(_EXPAND_JS)  # show every tab panel / <details>, labelled with its tab title
            except Exception:
                n_hidden = 0
            page.wait_for_timeout(800 if n_hidden else 0)
            height = int(page.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
            for y in range(0, height, TILE_H):  # trigger lazy charts
                page.evaluate("y => window.scrollTo(0, y)", y)
                page.wait_for_timeout(120)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(400)
            _settle(page, quiet_s=1.2, max_s=8.0)  # scrolling starts lazy charts and count-up animations
            height = int(page.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
            tiles = []
            n_tiles = min(MAX_TILES, max(1, -(-height // TILE_H)))
            for i in range(n_tiles):
                h = min(TILE_H, height - i * TILE_H)
                if h < 40:
                    break
                try:
                    tiles.append(page.screenshot(full_page=True, type="png",
                                                 clip={"x": 0, "y": i * TILE_H, "width": TILE_W, "height": h}))
                except Exception:
                    if not tiles:
                        raise
                    break  # the page got shorter while we were capturing it
            try:
                charts = page.evaluate(_CHARTS_JS)
            except Exception:
                charts = []
            frames = _frames(page)
            for fr in frames:
                charts += fr.pop("charts")
            for c in charts:
                c["screenshot"] = int(c.pop("y", 0) // TILE_H) + 1
                c.pop("h", None)
            figures = []
            try:
                for f in page.evaluate(_FIGURES_JS)[:MAX_FIGURES]:
                    b64 = f.pop("b64", None)
                    if b64:
                        f["data"] = base64.b64decode(b64)
                        f["screenshot"] = int(f.pop("y", 0) // TILE_H) + 1
                        figures.append(f)
            except Exception:
                figures = []
            links = page.evaluate("[...document.querySelectorAll('a[href]')].map(a => ({href: a.href, text: a.innerText.trim().slice(0,120)}))")
            text = page.evaluate("document.body.innerText") + page.evaluate(_SHADOW_TABLES_JS)
            for fr in frames:
                if len(fr["text"].strip()) >= 80:
                    text += (f"\n\n[EMBEDDED FRAME {fr['url']} (starts on screenshot {int(fr['top'] // TILE_H) + 1})]\n" + fr["text"])
            return {
                "title": page.title(), "url": page.url, "text": text,
                "tiles": tiles, "charts": charts, "links": links, "figures": figures,
                "truncated": height > n_tiles * TILE_H,
                "frames": [{"url": fr["url"], "chars": len(fr["text"])} for fr in frames],
                "consent": consent, "settled_s": waited,
            }
        finally:
            browser.close()


def _sniff(data: bytes) -> str:
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "text/html"


def _load(source, mime: str | None, actions=None) -> dict:
    """-> {kind: pdf|image|page, data|page, url, mime}"""
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        m = mime or _sniff(data)
        return {"kind": "pdf" if m == "application/pdf" else "image", "data": data, "mime": m, "url": None}
    s = str(source)
    if not re.match(r"^https?://", s):
        data = Path(s).read_bytes()
        m = mime or _sniff(data)
        if m == "text/html":
            return {"kind": "page", "page": render_page(Path(s).resolve().as_uri(), actions), "url": s, "mime": m}
        return {"kind": "pdf" if m == "application/pdf" else "image", "data": data, "mime": m, "url": s}
    looks_pdf = mime == "application/pdf" or s.lower().split("?")[0].endswith(".pdf")
    if not actions:
        try:
            import requests

            r = requests.get(s, headers={"User-Agent": UA}, timeout=40)
            if r.ok and _sniff(r.content) != "text/html":
                m = _sniff(r.content)
                return {"kind": "pdf" if m == "application/pdf" else "image", "data": r.content, "mime": m, "url": s}
        except Exception:
            pass
    if looks_pdf:
        data = browser_fetch_bytes(s)
        if _sniff(data) != "application/pdf":
            raise RuntimeError(f"could not download a PDF from {s}")
        return {"kind": "pdf", "data": data, "mime": "application/pdf", "url": s}
    return {"kind": "page", "page": render_page(s, actions), "url": s, "mime": "text/html"}


# ----------------------------------------------------------------- gemini

def _client():
    from google import genai

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key)


def _model() -> str:
    return os.environ.get("GEMINI_READER_MODEL", "").strip() or DEFAULT_MODEL


def _out_cap(max_out: int) -> int:
    return min(max_out, _OUT_LIMIT.get(_model(), 65536))


def _generate(client, parts: list, schema, max_out: int = 60000, tries: int = 3):
    from google.genai import types

    max_out = _out_cap(max_out)
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema,
        temperature=0, max_output_tokens=max_out,
    )
    last = None
    for attempt in range(tries):
        try:
            resp = client.models.generate_content(model=_model(), contents=parts, config=cfg)
            if resp.parsed is not None:
                return resp.parsed
            return schema.model_validate_json(resp.text or "")
        except Exception as exc:  # 429/5xx/truncated JSON: back off and retry
            last = exc
            print(f"[gemini_reader] attempt {attempt + 1} failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr, flush=True)
            time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"Gemini call failed after {tries} tries: {type(last).__name__}: {str(last)[:300]}")


def _salvage(text: str) -> tuple[Optional[_Doc], list[_Item]]:
    """The complete items of an answer that was cut off mid-list (output limit reached)."""
    dec = json.JSONDecoder()
    doc = None
    m = re.search(r'"document"\s*:\s*', text)
    if m:
        try:
            doc = _Doc.model_validate(dec.raw_decode(text, m.end())[0])
        except Exception:  # noqa: BLE001 - the document block itself was cut
            doc = None
    items: list[_Item] = []
    m = re.search(r'"extracted"\s*:\s*\[', text)
    pos = m.end() if m else len(text)
    while pos < len(text):
        while pos < len(text) and text[pos] in " \r\n\t,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            break
        try:
            obj, pos = dec.raw_decode(text, pos)
            items.append(_Item.model_validate(obj))
        except Exception:  # noqa: BLE001 - the cut-off item
            break
    return doc, items


def _extract(client, parts: list, rounds: int = 6) -> _Extraction:
    """Pass 1. When the answer stops at the model's output limit, keep the complete items and ask for the rest."""
    from google.genai import types

    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=_Extraction,
                                      temperature=0, max_output_tokens=_out_cap(60000))
    doc, notes, items, seen = None, "", [], set()

    def add(new) -> int:
        n = 0
        for it in new:
            key = (it.indicator_guess, it.area, it.period, it.value, it.page, it.label)
            if key not in seen:
                seen.add(key)
                items.append(it)
                n += 1
        return n

    for rnd in range(rounds):
        more = []
        if items:
            more = [f"CONTINUE. The answer stopped at the output limit. These {len(items)} values are already extracted "
                    "(indicator | area | period | value | page). Do not repeat them. Extract only the values still "
                    "missing, by the same rules, in document order. If nothing is missing, return an empty list.\n"
                    + "\n".join(f"{it.indicator_guess} | {it.area} | {it.period} | {it.value} | {it.page}" for it in items)]
        cut, last = False, None
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=_model(), contents=parts + more, config=cfg)
                reason = str(getattr((resp.candidates or [None])[0], "finish_reason", "") or "")
                if "MAX_TOKENS" in reason:
                    d, got = _salvage(resp.text or "")
                    doc, cut = doc or d, True
                    n = add(got)
                    print(f"[gemini_reader] pass 1 round {rnd + 1}: output limit reached, {n} more values kept", file=sys.stderr, flush=True)
                    if not n:
                        cut = False  # nothing complete came back: stop instead of asking again
                    break
                out = resp.parsed if resp.parsed is not None else _Extraction.model_validate_json(resp.text or "")
                doc = doc or out.document
                notes = " ".join(x for x in (notes, (out.notes or "").strip()) if x)
                add(out.extracted)
                break
            except Exception as exc:  # 429/5xx/broken JSON: back off and retry
                last = exc
                print(f"[gemini_reader] attempt {attempt + 1} failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr, flush=True)
                time.sleep(2 + 3 * attempt)
        else:
            if not items:
                raise RuntimeError(f"Gemini call failed after 3 tries: {type(last).__name__}: {str(last)[:300]}")
            notes = (notes + " A later round of the read failed, so the list may be incomplete.").strip()
        if not cut:
            break
    else:
        notes = (notes + f" The read stopped after {rounds} rounds at the output limit, so the list may be incomplete.").strip()
    return _Extraction(document=doc or _Doc(title="", publisher="", pages=0), extracted=items, notes=notes)


def _pdf_part(data: bytes):
    from google.genai import types

    return types.Part.from_bytes(data=data, mime_type="application/pdf")


def _img_part(data: bytes, mime: str = "image/png"):
    from google.genai import types

    return types.Part.from_bytes(data=data, mime_type=mime)


def _prompt(hint: str, unit_word: str) -> str:
    areas = "\n".join(
        f'  {a["id"]}: {a["name_fi"]} / {a["name_en"]} / {a["name_sv"]} (collaborative area {a["yta"]})'
        for a in load_areas()
    )
    keys = "\n".join(f"  {k}: {v}" for k, v in INDICATOR_KEYS.items())
    return f"""You are reading a public health report about cancer care in Finland. Extract every
numeric indicator value it reports about lung cancer (and cancer care waiting times / pathway
performance), as structured data. The document may be Finnish, Swedish or English.

{('What we need most: ' + hint) if hint else ''}

Rules
- Only values that are printed in the document or clearly readable from a chart, table or the
  attached chart data. Never compute, average, sum or estimate a value. Never use outside knowledge.
- One item per (indicator, area, period, subgroup). Put any subgroup (sex, stage, cell type, age
  group, treatment type) into `label` and `label_en`.
- `indicator_guess`: use one of these keys when it fits exactly, otherwise invent a clear
  snake_case key (prefix lung_ for lung cancer):
{keys}
- `area`: the area name exactly as written. `area_id`: the id from this list, "FI" for the whole
  country, "yta:HUS|TYKS|TAYS|KYS|OYS" for a collaborative area (yhteistyöalue), else null.
{areas}
- `value`: a plain number (decimal point). `unit`: "%", "n", "days", "per 100 000", "EUR"...
- `period`: the years the value covers, as written (e.g. "2019-2023").
- `page`: the {unit_word} where the value is visible (1-based). For a web page, full-resolution
  figures are attached as extra numbered images after the screenshots: cite that image number.
- `quote`: a short VERBATIM snippet (max 160 characters) containing the number; for a chart, the
  chart title plus the axis or series label the value was read from.
- `read_from`: "text", "table" or "chart". `confidence`: 0-1; below 0.7 when read off a chart
  without printed data labels.
- `label`: the indicator in the document's language. `label_en`: the same in English.
- If the document has per-area (wellbeing services county / hyvinvointialue) results, extract
  them for EVERY area shown, not just examples.
- `document.pages`: the number of {unit_word}s. `notes`: anything a user must know (definitions,
  what could not be read, charts without readable values)."""


_TARGETS_PROMPT = """Second question about the same document. It reports no measured result, so list instead the
TARGETS it states for cancer care as numbers: maximum or recommended waiting times (referral to first visit, to
diagnosis, to start of treatment), deadlines and thresholds. National targets and targets for a named cancer both
count; skip examples from other countries, code lists and page numbers. Same fields and rules as before (verbatim
quote, page), with these differences: `indicator_guess` starts with "target_" (for example
target_days_referral_to_treatment), `label` and `label_en` say that it is a target or recommendation and whose
(for example "recommended maximum, Ministry of Social Affairs and Health 2010"), `area` is "Koko maa" for a national
target, `period` is the year the target was set or took effect. Convert nothing: give the number and unit as printed
(weeks stay weeks). If the document states no such target, return an empty list."""


def _in_text(value: float, text: str) -> bool:
    """True if the number is printed literally in the page text (dot or comma decimals, optional thousands space)."""
    v = float(value)
    forms = set()
    if v == int(v):
        n = str(int(v))
        forms.add(n)
        if len(n) > 3:
            forms.add(f"{int(v):,}".replace(",", "[  ,]"))
    else:
        for nd in (1, 2, 3):
            if abs(round(v, nd) - v) < 1e-9:
                forms.add(f"{v:.{nd}f}".replace(".", "[.,]"))
                break
        else:
            forms.add(repr(v).replace(".", "[.,]"))
    if len(max(forms, key=len).replace("[.,]", ".")) < 3:
        return False  # one- and two-character numbers match by accident
    return any(re.search(r"(?<![\d.,])" + f + r"(?![\d]|[.,]\d)", text) for f in forms)


def _num_close(a: float, b: Optional[float], chart: bool) -> bool:
    if b is None:
        return False
    tol = max(1.5, abs(a) * 0.04) if chart else max(0.051, abs(a) * 0.0006)
    return abs(a - b) <= tol


def _verify_group(client, part_list: list, items: list[tuple[int, dict]]) -> dict[int, dict]:
    claims = [
        {"i": i, "label": it["label"], "area": it["area"], "value": it["value"], "unit": it["unit"],
         "period": it["period"], "quote": it["quote"]}
        for i, it in items
    ]
    prompt = (
        "Independent check. Look ONLY at the attached page / screenshot (and its chart data, if "
        "given). For each claim below, find the value for that indicator, area and period and "
        "report what you see in `value_seen`. status = 'confirmed' if the attachment shows that "
        "value, 'mismatch' if it shows a different value for the same thing (give it), "
        "'not_visible' if the value is not on this page. Do not trust the claim; read the page.\n"
        "Claims:\n" + json.dumps(claims, ensure_ascii=False)
    )
    try:
        res = _generate(client, part_list + [prompt], _Checks, max_out=30000, tries=2)
    except Exception as exc:
        return {i: {"status": "unchecked", "note": str(exc)[:120]} for i, _ in items}
    return {c.i: c.model_dump() for c in res.checks}


def read_report(source, hint: str = "", mime: str | None = None, *, verify: bool = True,
                actions=None, source_url: str | None = None) -> dict:
    """Read a report (URL to PDF/HTML/web app, local path, or raw bytes) into cited numbers.

    Returns {document:{title,publisher,url,pages}, extracted:[{indicator_guess,label,label_en,
    area,area_id,value,unit,period,page,quote,read_from,confidence,verified,check}], model, notes}.
    """
    t0 = time.time()
    client = _client()
    src = _load(source, mime, actions)
    url = source_url or src.get("url")
    notes: list[str] = []

    # The Cancer Registry statistics pages show their numbers inside an embedded R Shiny app that
    # opens on "all cancers". Reading that default view finds no lung cancer value, so open the app
    # itself and set it to lung cancer for every area (the same clicks a person would make).
    if src["kind"] == "page" and actions is None:
        pg0 = src["page"]
        if any(_REGISTRY_APP in (f.get("url") or "") for f in pg0.get("frames") or []) or _REGISTRY_APP in (pg0.get("url") or ""):
            try:
                from . import syoparekisteri_app as sa

                act = sa.make_actions("theme_inc", "_latest5", ".rate_finland_2014")
                src = {**src, "page": render_page(sa.APP_URL, act)}
                hint = ("This is the Finnish Cancer Registry statistics app showing a table for lung cancer (Keuhkot, henkitorvi "
                        "C33-34), both sexes together, one row per area: lung cancer incidence per 100 000, age-standardised "
                        "(Finland 2014), latest five-year period. Indicator lung_incidence_per_100k; say 'age-standardised "
                        "(Finland 2014)' in the label. Extract the value for EVERY area row, with the period shown in the table. "
                        + (hint or ""))
                notes.append("This page shows its numbers inside the Cancer Registry statistics app (an embedded frame that opens on "
                             "all cancers together). Kello opened the app itself and set it to lung cancer (C33-34), both sexes, "
                             "all areas, age-standardised incidence for the latest five-year period; other views of the app were not read")
            except Exception as exc:
                notes.append("This page embeds the Cancer Registry statistics app; setting it to lung cancer failed "
                             f"({type(exc).__name__}), so only the default view (all cancers together) was read")

    if src["kind"] == "pdf":
        parts = [_pdf_part(src["data"]), _prompt(hint, "PDF page")]
    elif src["kind"] == "image":
        parts = [_img_part(src["data"], src["mime"]), _prompt(hint, "image")]
    else:
        pg = src["page"]
        parts = [_prompt(hint, "screenshot")]
        for i, tile in enumerate(pg["tiles"], start=1):
            parts += [f"Screenshot {i} of {len(pg['tiles'])}:", _img_part(tile)]
        n_t = len(pg["tiles"])
        for k, f in enumerate(pg.get("figures") or [], start=1):
            parts += [f"Image {n_t + k} (cite as page {n_t + k}): a figure from the page at full resolution. "
                      f"Caption: {f['caption'] or '-'} {f['tab']} (it appears on screenshot {f['screenshot']}). "
                      "Read numbers printed in this figure from THIS image, not from the smaller screenshot:",
                      _img_part(f["data"], f.get("mime") or "image/png")]
        parts.append("PAGE TEXT (innerText of the rendered page):\n" + pg["text"][:150000])
        if pg["charts"]:
            cd = json.dumps(pg["charts"], ensure_ascii=False)
            if len(cd) > 400000:
                notes.append("chart data truncated to 400k characters")
            parts.append(
                "CHART DATA (exact values behind the interactive charts, read from the rendered "
                "page; `screenshot` says where each chart is). Prefer these values over reading "
                "bar heights, and cite the chart title / series name as the quote:\n" + cd[:400000]
            )
        if pg.get("truncated"):
            notes.append(f"page longer than {MAX_TILES} screenshots; the rest was read from text only")

    print(f"[gemini_reader] loaded {src['kind']} in {time.time() - t0:.1f} s; pass 1 with {_model()}", file=sys.stderr, flush=True)
    out = _extract(client, parts)
    print(f"[gemini_reader] pass 1: {len(out.extracted)} values at {time.time() - t0:.1f} s; pass 2 (re-read cited pages)", file=sys.stderr, flush=True)
    items = [it.model_dump() for it in out.extracted]
    targets_read = False
    if not items and src["kind"] in ("pdf", "image"):
        # A guideline or definitions document reports no measured value. What a planner can still use
        # from it are the stated targets (maximum waiting times, thresholds), so ask once for those.
        try:
            out2 = _generate(client, parts + [_TARGETS_PROMPT], _Extraction, max_out=20000, tries=2)
            items = [it.model_dump() for it in out2.extracted][:30]
            for it in items:
                it["value_kind"] = "target"
                if not str(it.get("indicator_guess") or "").startswith("target_"):
                    it["indicator_guess"] = "target_" + str(it.get("indicator_guess") or "value")
            targets_read = bool(items)
            print(f"[gemini_reader] no measured value; targets pass: {len(items)} at {time.time() - t0:.1f} s", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001 - the note from pass 1 is still returned
            print(f"[gemini_reader] targets pass failed: {type(exc).__name__}", file=sys.stderr, flush=True)
    for it in items:
        it.setdefault("value_kind", "measured")
        it["area_id"] = map_area(it["area"], it.get("area_id"))

    dropped = text_kept = 0
    if verify and items:
        groups: dict[int, list[tuple[int, dict]]] = {}
        for i, it in enumerate(items):
            groups.setdefault(int(it["page"] or 0), []).append((i, it))
        jobs = []
        if src["kind"] == "pdf":
            import pymupdf as fitz

            doc = fitz.open(stream=src["data"], filetype="pdf")
            for page_no, group in groups.items():
                if not 1 <= page_no <= doc.page_count:
                    jobs.append((None, group))
                    continue
                one = fitz.open()
                one.insert_pdf(doc, from_page=page_no - 1, to_page=page_no - 1)
                jobs.append(([_pdf_part(one.tobytes())], group))
        elif src["kind"] == "image":
            jobs = [([_img_part(src["data"], src["mime"])], g) for g in groups.values()]
        else:
            pg = src["page"]
            figs = pg.get("figures") or []
            for shot, group in groups.items():
                if len(pg["tiles"]) < shot <= len(pg["tiles"]) + len(figs):
                    f = figs[shot - len(pg["tiles"]) - 1]
                    jobs.append(([f"Figure. Caption: {f['caption']} {f['tab']}", _img_part(f["data"], f.get("mime") or "image/png")], group))
                    continue
                if not 1 <= shot <= len(pg["tiles"]):
                    jobs.append((None, group))
                    continue
                pl = [_img_part(pg["tiles"][shot - 1])]
                cd = [c for c in pg["charts"] if c.get("screenshot") in (shot, shot - 1, shot + 1)]
                if cd:
                    pl.append("Chart data for charts on or next to this screenshot:\n" + json.dumps(cd, ensure_ascii=False)[:200000])
                jobs.append((pl, group))

        def run(job):
            pl, group = job
            if pl is None:
                return {i: {"status": "not_visible", "note": "cited page out of range"} for i, _ in group}
            res: dict[int, dict] = {}
            for k in range(0, len(group), 60):
                res.update(_verify_group(client, pl, group[k:k + 60]))
            return res

        checks: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            for res in ex.map(run, jobs):
                checks.update(res)
        kept = []
        for i, it in enumerate(items):
            c = checks.get(i) or {"status": "unchecked", "note": "no answer"}
            chart = it.get("read_from") == "chart"
            printed = src["kind"] == "page" and it.get("read_from") != "chart" and _in_text(it["value"], src["page"]["text"])
            if c["status"] == "confirmed" and (c.get("value_seen") is None or _num_close(it["value"], c.get("value_seen"), chart)):
                it["verified"] = True
            elif printed:
                # Printed literally in the page text. The screenshot may not show it (wide or scrolled
                # table) or may show another number for a moment (count-up animation, a frame still
                # loading): the text of the settled page wins, so the value is kept, not dropped.
                it["verified"] = c["status"] != "mismatch"
                if not it["verified"]:
                    it["confidence"] = round(min(float(it["confidence"]), 0.6), 2)
                    text_kept += 1
                c = {"status": "text_match", "screenshot_read": c.get("value_seen")}
            elif c["status"] in ("confirmed", "mismatch") and c.get("value_seen") is not None \
                    and not _num_close(it["value"], c["value_seen"], chart):
                dropped += 1
                continue  # second read saw a different number and the page text does not print ours: drop
            else:
                it["verified"] = False
                it["confidence"] = round(min(float(it["confidence"]), 0.5), 2)
            it["check"] = c["status"]
            kept.append(it)
        items = kept
        if dropped:
            notes.append(f"{dropped} value(s) dropped: the second read of the cited page saw a different number")
        if text_kept:
            notes.append(f"{text_kept} value(s) kept unverified: printed in the page text, but the screenshot showed another number")
    else:
        for it in items:
            it["verified"] = False
            it["check"] = "skipped"

    notes_en = " | ".join(x for x in [(out.notes or "").strip()] + notes if x)
    if targets_read and items:
        notes_en = (f"No measured lung cancer value is reported in this document. The {len(items)} value(s) listed are targets or "
                    "recommended maximum times it states (value_kind \"target\"), not results. " + notes_en).strip()
    elif not items:
        notes_en = ("No lung cancer value was read from this document. " + notes_en).strip()
    title = out.document.title or (src.get("page") or {}).get("title", "")
    n_pages = out.document.pages
    if src["kind"] == "page":
        n_pages = len(src["page"]["tiles"]) + len(src["page"].get("figures") or [])
    return {
        "document": {"title": title, "publisher": out.document.publisher, "url": url, "pages": n_pages,
                     "kind": src["kind"]},
        "extracted": items,
        "model": _model(),
        "notes": notes_en,
        "notes_en": notes_en,  # what Gemini said about the document; the UI shows it, also when no value was found
        "seconds": round(time.time() - t0, 1),
    }


# ----------------------------------------------------------------- a figure published only as an image

class _Seg(BaseModel):
    series: str
    start: float
    end: float


class _Bar(BaseModel):
    area: str
    segments: list[_Seg]


class _Chart(BaseModel):
    chart_type: str
    axis_label: str
    series: list[str]
    bars: list[_Bar]
    notes: str


_CHART_PROMPT = """This image is a stacked horizontal bar chart from a Finnish Cancer Registry report. Each bar is
one area and runs from 0 to 100 on the horizontal axis (share of patients, %). Each coloured segment is one series
of the legend.

Read every bar, top to bottom. For each bar give `area` exactly as its label is written, and its segments in
left-to-right order. For each segment give `series` (the legend name of its colour) and the axis positions where
it starts and ends (`start`, `end`, in axis units, one decimal). Read the positions from the axis tick marks
(0, 25, 50, 75, 100) and the gridlines, as carefully as you can; the first segment starts at 0, each next segment
starts where the previous one ends, the last one ends at 100. Include thin segments (1 to 3 units wide); leave a
series out of a bar only when its colour is really not there. Ignore any numbers printed inside the bars: they are
patient counts, not shares. `notes`: anything you could not read."""


def read_chart(image: bytes, *, figure: str, caption: str = "", mime: str = "image/png", model: str | None = None) -> dict:
    """Read a 100 % stacked bar chart that is published only as an image into shares per area and series.

    -> {figure, caption, model, chart_type, series, bars:[{area, area_id, shares:{series: pct}, sum}], notes, seconds}
    The values are estimates read off the axis (see README for the measured error); never mark them verified.
    """
    t0 = time.time()
    client = _client()
    old = os.environ.get("GEMINI_READER_MODEL")
    if model:
        os.environ["GEMINI_READER_MODEL"] = model
    try:
        out = _generate(client, [_img_part(image, mime), f"Figure: {figure}. Caption: {caption}\n\n" + _CHART_PROMPT],
                        _Chart, max_out=30000)
        used = _model()
    finally:
        if model:
            if old is None:
                os.environ.pop("GEMINI_READER_MODEL", None)
            else:
                os.environ["GEMINI_READER_MODEL"] = old
    bars = []
    for b in out.bars:
        shares: dict[str, float] = {}
        for sg in b.segments:
            shares[sg.series] = round(shares.get(sg.series, 0.0) + max(0.0, sg.end - sg.start), 1)
        bars.append({"area": b.area, "area_id": map_area(b.area), "shares": shares, "sum": round(sum(shares.values()), 1)})
    return {"figure": figure, "caption": caption, "model": used, "chart_type": out.chart_type, "axis_label": out.axis_label,
            "series": out.series, "bars": bars, "notes": out.notes, "seconds": round(time.time() - t0, 1)}


def to_rows(result: dict, source_url: str | None = None, lang: str = "fi") -> list[dict]:
    """read_report() result -> rows for data/processed/gemini_extracted.jsonl (mapped areas only)."""
    rows = []
    url = source_url or result["document"].get("url")
    for it in result["extracted"]:
        if not it.get("area_id"):
            continue
        rows.append({
            "area_id": it["area_id"], "indicator": it["indicator_guess"],
            "label_en": it.get("label_en") or it["label"],
            "label_fi": it["label"] if lang == "fi" else None,
            "value": it["value"], "unit": it["unit"], "period": it["period"],
            "source_url": url, "page": it["page"], "quote": it["quote"],
            "kind": "measured", "read_by": f"gemini:{result['model']}",
            "confidence": it["confidence"], "verified": bool(it.get("verified")),
            "read_from": it.get("read_from"), "area_name": it["area"],
        })
    return rows


def append_rows(rows: list[dict], path: Path = OUT_JSONL) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m integrations.gemini_reader",
                                 description="Read a report/chart/web page with Gemini into cited numbers.")
    ap.add_argument("source", help="URL (PDF, HTML, web app) or local file")
    ap.add_argument("--hint", default="")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--append", action="store_true", help=f"append rows to {OUT_JSONL}")
    ap.add_argument("--out", help="write the full JSON result here")
    ap.add_argument("--model", help=f"Gemini model for this read (default {DEFAULT_MODEL}; reads done ahead of time use {OFFLINE_MODEL})")
    a = ap.parse_args(argv)
    if a.model:
        os.environ["GEMINI_READER_MODEL"] = a.model
    res = read_report(a.source, hint=a.hint, verify=not a.no_verify)
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    if a.append:
        n = append_rows(to_rows(res))
        print(f"appended {n} rows to {OUT_JSONL}", file=sys.stderr)
    slim = {**res, "extracted": res["extracted"][:40]}
    print(json.dumps(slim, ensure_ascii=False, indent=1))
    print(f"{len(res['extracted'])} values, {sum(1 for i in res['extracted'] if i.get('verified'))} confirmed, "
          f"{res['seconds']} s, model {res['model']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
