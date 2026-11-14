"""Saved copies of the cancer registry pages Kello cites.

The registry sites ask a browser to pass a check before they show a page, so a
source link can open a robot check instead of the report.  For each cited
registry URL this looks once, server-side, whether the Internet Archive already
holds a copy (https://web.archive.org/web/2026/<url>).  It never asks the archive
to make a new copy and never stores the pages themselves; only the copy's
address is kept, in data/processed/archive_copies.json.

    python app/server/integrations/archive_copies.py      # look again and rewrite the file
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "processed" / "archive_copies.json"
REGISTRY = re.compile(r"https?://(?:tilastot\.)?(?:syoparekisteri|cancerregistry)\.fi[^\"'\s<>\\]*")
WAYBACK = "https://web.archive.org/web/2026/"
MAX_URLS = 10


def cited_urls() -> list[str]:
    """Registry URLs in the processed data, most cited first."""
    counts: dict[str, int] = {}
    for f in sorted((ROOT / "data" / "processed").glob("*.json")):
        if f == OUT:
            continue
        for u in REGISTRY.findall(f.read_text(encoding="utf-8", errors="ignore")):
            u = u.rstrip(").,")
            counts[u] = counts.get(u, 0) + 1
    return [u for u, _ in sorted(counts.items(), key=lambda x: -x[1])][:MAX_URLS]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # keep the 302 so we can read where it points
        return None


def look(url: str) -> dict:
    """One request to the archive's lookup address. A redirect to a dated copy means a copy exists."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(WAYBACK + url, method="HEAD", headers={"User-Agent": "kello-source-check/1.0"})
    try:
        with opener.open(req, timeout=40) as r:
            status, loc = r.status, r.headers.get("Location")
    except urllib.error.HTTPError as e:
        status, loc = e.code, e.headers.get("Location")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "copy_url": None, "checked": "failed", "reason": type(e).__name__}
    if status in (301, 302, 303, 307, 308) and loc:
        if loc.startswith("/"):
            loc = "https://web.archive.org" + loc
        m = re.search(r"/web/(\d{8,14})/", loc)
        return {"url": url, "copy_url": loc, "captured": m.group(1)[:8] if m else None, "checked": "ok"}
    if status == 200:
        return {"url": url, "copy_url": WAYBACK + url, "captured": None, "checked": "ok"}
    return {"url": url, "copy_url": None, "checked": "ok" if status == 404 else f"http {status}"}


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"copies": []}


def main() -> None:
    rows = []
    for u in cited_urls():
        rows.append(look(u))
        print(("copy  " if rows[-1]["copy_url"] else "none  ") + u[:100], file=sys.stderr)
        time.sleep(1.0)
    OUT.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                               "note": "Existing Internet Archive copies of cited registry pages; none were requested.",
                               "copies": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
