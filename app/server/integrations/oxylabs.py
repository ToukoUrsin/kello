"""Oxylabs Web API client (https://webapi.oxylabs.io): search to find, scrape to read.

Docs: https://developers.oxylabs.io/products/web-api/for-agents.md
Auth: `Authorization: Bearer <key>`; key from env `JUNCTION_OXYLABS_API_KEY`
(fallback `OXYLABS_WEB_API_KEY`). The key is never logged or put in errors.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://webapi.oxylabs.io"
RETRYABLE = {408, 429, 500, 502, 503, 504}
_KEY_ENVS = ("JUNCTION_OXYLABS_API_KEY", "OXYLABS_WEB_API_KEY")

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_session = requests.Session()


class OxylabsError(RuntimeError):
    """Any Oxylabs Web API failure. `.status` holds the HTTP status if there was one."""

    def __init__(self, message: str, status: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.request_id = request_id


class OxylabsAuthError(OxylabsError):
    """No key, or the key was rejected (401). Retrying cannot help."""


def has_credentials() -> bool:
    return any(os.environ.get(k, "").strip() for k in _KEY_ENVS)


def _key() -> str:
    for name in _KEY_ENVS:
        key = os.environ.get(name, "").strip()
        if key:
            return key
    raise OxylabsAuthError(
        "No Oxylabs Web API key: set JUNCTION_OXYLABS_API_KEY "
        "(dashboard.oxylabs.io -> Web API instance -> API key)."
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _post(path: str, payload: dict, timeout: float = 60.0, attempts: int = 3) -> dict:
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    last = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            resp = _session.post(f"{API}{path}", json=payload, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = f"{type(exc).__name__}"
            if attempt == attempts:
                raise OxylabsError(f"{path}: network failure after {attempts} attempts ({last})") from None
            time.sleep(min(2 ** attempt, 8) * 0.5 + random.random())
            continue
        if resp.ok:
            try:
                return resp.json()
            except ValueError:
                raise OxylabsError(f"{path}: 2xx with a non-JSON body", resp.status_code) from None
        if resp.status_code == 401:
            raise OxylabsAuthError(
                f"{path}: 401, the API key was rejected (wrong product, revoked, or unverified account).", 401
            )
        detail, request_id = resp.text[:300], None
        try:
            problem = resp.json()
            request_id = str((problem.get("metadata") or {}).get("request_id") or "") or None
            fields = "; ".join(f"{e.get('pointer')}: {e.get('detail')}" for e in problem.get("errors") or [])
            detail = f"{problem.get('title')}: {problem.get('detail')}" + (f" [{fields}]" if fields else "")
        except ValueError:
            pass
        last = f"{resp.status_code} {detail}"
        if resp.status_code not in RETRYABLE or attempt == attempts:
            hint = " (rate limit or spent credits)" if resp.status_code == 429 else ""
            raise OxylabsError(f"{path}: {last}{hint}", resp.status_code, request_id)
        time.sleep(min(2 ** attempt, 8) * 0.5 + random.random())
    raise OxylabsError(f"{path}: {last}")


def search(query: str, n: int = 6, country: str = "fi", lang: str | None = None) -> list[dict]:
    """Live web search. Returns [{url, title, snippet, rank}], best first.

    `country` is an ISO 3166-1 alpha-2 code (results as seen from that country).
    The Web API has no language field; `lang` ("fi", "en", "sv") is applied as a
    light query hint only when the query does not already look like that language.
    """
    query = " ".join(query.split())[:2000]
    if not query:
        raise ValueError("search: empty query")
    payload: dict = {"query": query, "max_results": max(1, min(int(n), 20))}
    if country:
        payload["location"] = country.upper()
    data = _post("/v1/search", payload, timeout=45.0)
    out: list[dict] = []
    for i, r in enumerate(data.get("results") or [], start=1):
        url = r.get("url")
        if not url:
            continue
        outline = r.get("outline") or r.get("snippet") or r.get("description") or ""
        if isinstance(outline, list):
            outline = " ".join(str(x) for x in outline)
        out.append(
            {
                "url": url,
                "title": (r.get("title") or "").strip(),
                "snippet": str(outline).strip()[:500],
                "rank": int((r.get("metadata") or {}).get("position") or i),
            }
        )
    out.sort(key=lambda r: r["rank"])
    return out[:n]


# ----------------------------------------------------------------- reading pages

PAGE_CACHE = Path(__file__).resolve().parents[1] / "cache" / "pages"
PAGE_TTL_S = 24 * 3600
_NORDIC = {"fi", "se", "no", "dk", "ee", "ax"}


EXTRACT_V = "4"  # raise when the text extraction changes: older cached pages are then ignored


def _cache_file(url: str) -> Path:
    return PAGE_CACHE / (hashlib.sha256(f"{EXTRACT_V}|{url}".encode()).hexdigest()[:20] + ".json")


def _cache_get(url: str) -> dict | None:
    with _cache_lock:
        hit = _cache.get(url)
    if hit and time.time() - hit.get("_t", 0) < PAGE_TTL_S:
        return hit
    f = _cache_file(url)
    try:
        if f.exists() and time.time() - f.stat().st_mtime < PAGE_TTL_S:
            hit = json.loads(f.read_text(encoding="utf-8"))
            hit["_t"] = f.stat().st_mtime
            with _cache_lock:
                _cache[url] = hit
            return hit
    except Exception:
        pass
    return None


def _cache_put(url: str, page: dict) -> None:
    page = {**page, "_t": time.time()}
    with _cache_lock:
        _cache[url] = page
    try:
        PAGE_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = _cache_file(url).with_suffix(".tmp%d" % threading.get_ident())
        tmp.write_text(json.dumps({k: v for k, v in page.items() if k != "_t"}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_cache_file(url))
    except Exception:
        pass


def _scrape_once(url: str, run_js: bool, country: str | None, timeout: float, fmt: str = "html",
                 attempts: int = 2) -> dict:
    payload: dict = {"url": url, "output": [fmt]}
    if run_js:
        payload["run_js"] = True
    if country:
        payload["location"] = country.upper()
    data = _post("/v1/scrape", payload, timeout=timeout, attempts=attempts)
    results = data.get("results") or []
    return results[0] if results else {}


_HEX = re.compile(rb"\\x([0-9a-fA-F]{2})")


def _binary_body(body: str) -> bytes:
    """/v1/scrape returns a binary file (PDF) as text: the bytes decoded as UTF-8, with every byte
    that is not valid UTF-8 written as `\\xNN`. Undo that to get the original bytes."""
    raw = body.encode("utf-8", errors="surrogatepass")
    return _HEX.sub(lambda m: bytes([int(m.group(1), 16)]), raw)


_EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def _epmc_search(query: str) -> tuple[str, str]:
    return (f"{_EPMC}/search?query={quote(query, safe=':')}&resultType=core&format=json", "epmc_json")


def _read_via(url: str) -> list[tuple[str, str]]:
    """Journal records that /v1/scrape cannot read directly: Oxylabs refuses pubmed / PMC URLs
    (400 "Value not supported"), europepmc.org pages are a JavaScript app, and doi.org redirects
    to publisher sites that block or stall the scraper. Read the same record from the Europe PMC
    REST API instead, still through /v1/scrape. -> [(url to scrape, kind), ...] to try in order."""
    m = re.match(r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url) \
        or re.match(r"^https?://(?:www\.)?europepmc\.org/(?:article|abstract)/MED/(\d+)", url, re.I)
    if m:
        return [_epmc_search(f"EXT_ID:{m.group(1)} AND SRC:MED")]
    m = re.match(r"^https?://(?:pmc\.ncbi\.nlm\.nih\.gov|www\.ncbi\.nlm\.nih\.gov/pmc)/articles/(PMC\d+)", url) \
        or re.match(r"^https?://(?:www\.)?europepmc\.org/(?:article|articles)/(?:PMC/)?(PMC\d+)", url, re.I)
    if m:  # full text when Europe PMC holds it, else the abstract
        return [(f"{_EPMC}/{m.group(1)}/fullTextXML", "epmc_xml"), _epmc_search(f"PMCID:{m.group(1)}")]
    m = re.match(r"^https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$", url, re.I)
    if m:
        return [_epmc_search(f'DOI:"{m.group(1)}"')]
    return []


def _parse(body: str, url: str, kind: str = "") -> dict:
    """Scraped body -> {title, text, kind, pages?, published?}"""
    from . import pagetext

    if kind == "epmc_json":
        rec = ((json.loads(body).get("resultList") or {}).get("result") or [{}])[0]
        text = "\n\n".join(x for x in [
            f"{rec.get('journalInfo', {}).get('journal', {}).get('title', '')} {rec.get('pubYear', '')}".strip(),
            "Authors: " + rec.get("authorString", "") if rec.get("authorString") else "",
            "## Abstract", re.sub(r"<[^>]+>", "", html.unescape(rec.get("abstractText", "") or ""))] if x)
        return {"title": re.sub(r"<[^>]+>", "", html.unescape(rec.get("title") or "")).strip(), "text": text, "kind": "abstract",
                "published": rec.get("firstPublicationDate") or str(rec.get("pubYear") or "")}
    if kind == "epmc_xml":
        return {**pagetext.jats_text(body), "kind": "article"}
    if body.lstrip()[:5] == "%PDF-":
        data = _binary_body(body.lstrip())
        return {**pagetext.pdf_text(data), "kind": "pdf"}
    return {**pagetext.extract_main(body, url), "kind": "html"}


def scrape(url: str, max_chars: int | None = None, timeout: float = 60.0, use_cache: bool = True,
           budget_s: float | None = None) -> dict:
    """Read one page or PDF through Oxylabs /v1/scrape.

    Returns {url, requested_url, title, text, kind, fetched_at, status, from_cache, chars, pages?, published?}.
    `text` is the MAIN CONTENT (navigation, cookie banners and footers removed; headings, lists,
    tables and numbers kept); it is not cut unless `max_chars` is given. PDFs are fetched through
    the same endpoint and parsed with PyMuPDF. Successful reads are cached on disk for 24 h
    (`from_cache: true` on a hit). `status` is "ok", "ok_js" (needed a JavaScript render), "ok_thin"
    (little text, and `budget_s` left no time for the slower JavaScript render; not cached), "empty"
    or "error: ...". Never raises for a single bad page; raises OxylabsAuthError when the key is bad.
    """
    t_start = time.time()
    if not re.match(r"^https?://", url or ""):
        raise ValueError(f"scrape: not an absolute http(s) URL: {url!r}")
    url = url.split("#")[0]
    if use_cache:
        hit = _cache_get(url)
        if hit and hit.get("kind", "html") == "html" and "links" not in hit:
            hit = None  # stored before pages kept their links: read it again
        if hit:
            out = {k: v for k, v in hit.items() if k != "_t"}
            out["from_cache"] = True
            if max_chars:
                out["text"] = out["text"][:max_chars]
            return out

    via = _read_via(url)
    target = url
    is_pdf = url.lower().split("?")[0].endswith(".pdf")
    status, parsed, err = "empty", None, None
    # each plan: (url to scrape, kind of body, JavaScript render, country)
    plans: list[tuple[str, str, bool, str | None]] = [(t, k, False, None) for t, k in via]
    if not via or "doi.org/" in url:  # a DOI that Europe PMC does not hold is read from the publisher
        plans.append((url, "", False, None))
        if not is_pdf:
            plans.append((url, "", True, None))
        tld = url.split("//", 1)[1].split("/", 1)[0].lower().rsplit(".", 1)[-1]
        if tld in _NORDIC:
            plans.append((url, "", not is_pdf, tld if tld != "ax" else "fi"))
    used_via = direct = False
    final_url = url
    thin_stop = False
    for target, kind, run_js, country in plans:
        # a JavaScript render takes 11-18 s: with a short budget, a thin plain read beats no read
        if budget_s is not None and parsed is not None and len(parsed["text"].strip()) >= 80 \
                and time.time() - t_start + (14.0 if run_js else 5.0) > budget_s:
            thin_stop = True
            break
        try:
            if kind:  # Europe PMC answers in 2-4 s; a missing full text must not eat the time for the abstract
                page = _scrape_once(target, False, None, 6.0 if kind == "epmc_xml" else 9.0, attempts=1)
            else:
                page = _scrape_once(target, run_js, country, timeout)
        except OxylabsAuthError:
            raise
        except OxylabsError as exc:
            err = str(exc)
            if kind == "epmc_json":
                # the scraper sometimes stalls on this public API: ask Europe PMC directly (no key, ~1 s)
                try:
                    r = requests.get(target, timeout=8, headers={"User-Agent": "Mozilla/5.0 (compatible; research-reader)"})
                    cand = _parse(r.text, target, kind) if r.ok else None
                except Exception:  # noqa: BLE001
                    cand = None
                if cand and len(cand["text"]) > 80:
                    parsed, status, err, used_via, direct = cand, "ok", None, True, True
                    break
            if exc.status in (400, 429) and not kind:
                break
            continue
        body = page.get("html") or ""
        if isinstance(body, dict):
            body = body.get("content") or body.get("text") or ""
        meta = page.get("metadata") or {}
        code = ((meta.get("statuses") or {}).get("http_request") or {}).get("code")
        if code and int(code) >= 400:
            err = f"the site answered HTTP {code}"
            if int(code) in (404, 410) and not kind:
                break
            continue
        try:
            cand = _parse(str(body), target, kind)
        except Exception as exc:  # unreadable PDF, broken JSON
            err = f"could not parse the page ({type(exc).__name__})"
            continue
        if len(cand["text"].strip()) >= 300 or (cand["kind"] == "abstract" and len(cand["text"]) > 80):
            parsed, status, err = cand, ("ok_js" if run_js else "ok"), None
            used_via = bool(kind)
            if not kind:
                final_url = meta.get("url") or page.get("url") or url
            break
        if parsed is None or len(cand["text"]) > len(parsed["text"]):
            parsed = cand  # keep the best thin read in case nothing better comes
    if not status.startswith("ok") and parsed and len(parsed["text"].strip()) >= 80:
        status, err = ("ok_thin" if thin_stop else "ok"), None
    text = parsed["text"] if (parsed and status.startswith("ok")) else ""
    out = {
        "url": final_url,
        "requested_url": url,
        "title": (parsed or {}).get("title", "") if status.startswith("ok") else "",
        "text": text,
        "kind": (parsed or {}).get("kind", "html"),
        "fetched_at": _now(),
        "status": status if status.startswith("ok") else (f"error: {err}" if err else "empty"),
        "from_cache": False,
        "chars": len(text),
    }
    if parsed and parsed.get("pages"):
        out["pages"] = parsed["pages"]
    if parsed and parsed.get("published"):
        out["published"] = parsed["published"]
    if out["kind"] == "html":
        out["links"] = (parsed or {}).get("links") or []
    if used_via:
        out["read_via"] = target
    if direct:
        out["direct"] = True  # fetched from the Europe PMC API without the scraper
    if status.startswith("ok") and status != "ok_thin":
        _cache_put(url, out)
    if max_chars:
        out = {**out, "text": text[:max_chars]}
    return out


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "keuhkosyövän seulonta pilotti Suomi"
    hits = search(q, n=5)
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    if hits:
        p = scrape(hits[0]["url"], max_chars=1500)
        print(json.dumps(p, ensure_ascii=False, indent=2))
