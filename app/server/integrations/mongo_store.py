"""MongoDB Atlas behind the web checks.

What Atlas holds (database `kello`):
  checks  one document per action and county: the stored answer every screen shows (the JSON of cache/verify).
  quotes  one document per sentence a check quoted from a public page, with the county, the action and what the
          page was read for. An Atlas Search index (Finnish and English analyzers) makes them searchable:
          "which counties' hospital pages say anything about stereotactic radiotherapy?"
  runs    every live run a visitor starts. On the public site the shown answer is pinned, so without this a
          visitor's run would leave no trace; here it is kept and counted. No visitor data is stored, only the run.

Set MONGODB_URI to switch it on. Without it, or when Atlas does not answer, every function here answers from the
JSON files in cache/verify instead: the search is then a plain word match over the same sentences, and the answer
says which of the two it was (`backend`).

    python -m integrations.mongo_store seed      # load the stored checks and build the search index
    python -m integrations.mongo_store search "sädehoito"
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlparse

DB_NAME = "kello"
INDEX = "quotes"
ATLAS, FILES = "mongodb_atlas", "files"
RETRY_S = 60.0          # after a failed connection, answer from the files for this long before trying again

INDEX_DEFINITION = {"mappings": {"dynamic": False, "fields": {
    "quote": {"type": "string", "analyzer": "lucene.finnish",
              "multi": {"en": {"type": "string", "analyzer": "lucene.english"}}},
    "title": {"type": "string", "analyzer": "lucene.finnish"},
    "intervention_name_en": {"type": "string", "analyzer": "lucene.english"},
    "area_name_en": {"type": "string", "analyzer": "lucene.standard"},
    "area_id": {"type": "token"},
}}}

_lock = threading.Lock()
_client = None
_down_until = 0.0
_file_quotes: tuple[float, list[dict]] | None = None


def uri() -> str | None:
    return os.environ.get("MONGODB_URI") or os.environ.get("JUNCTION_MONGODB_URI") or None


def _db():
    """The database, or None when no URI is set or Atlas did not answer in the last RETRY_S seconds."""
    global _client, _down_until
    u = uri()
    if not u or time.time() < _down_until:
        return None
    with _lock:
        if _client is None:
            try:
                from pymongo import MongoClient

                c = MongoClient(u, serverSelectionTimeoutMS=4000, connectTimeoutMS=4000, socketTimeoutMS=10000,
                                appname="kello")
                c.admin.command("ping")
                _client = c
            except Exception:  # noqa: BLE001  (no driver, no network, wrong URI: the files answer)
                _down_until = time.time() + RETRY_S
                return None
        return _client[DB_NAME]


def _failed() -> None:
    global _client, _down_until
    with _lock:
        _client, _down_until = None, time.time() + RETRY_S


# ----------------------------------------------------------------- the sentences

def _domain(url: str) -> str:
    return re.sub(r"^www\.", "", urlparse(url or "").netloc.lower())


def quotes_from(check: dict) -> list[dict]:
    """One row per quoted sentence of one stored check."""
    out = []
    iid, area = str(check.get("intervention_id") or ""), str(check.get("area_id") or "FI")
    for s in check.get("sources") or []:
        quote, url = (s.get("quote") or "").strip(), s.get("url") or ""
        if not quote or not url:
            continue
        out.append({
            "_id": hashlib.sha1(f"{iid}|{area}|{url}|{quote}".encode("utf-8")).hexdigest()[:20],
            "intervention_id": iid, "intervention_name_en": check.get("intervention_name_en") or iid,
            "area_id": area, "area_name_en": check.get("area_name_en") or area,
            "url": url, "domain": _domain(url), "title": s.get("title") or "", "quote": quote,
            "about": s.get("about") or "context", "advice": check.get("advice"),
            "in_use_here": check.get("in_use_here"), "checked_at": check.get("checked_at"),
        })
    return out


def _stored_checks() -> list[dict]:
    from . import verify

    out = []
    for f in sorted(verify.STORE.glob("*__*.json")):
        try:
            out.append(verify.present(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def file_quotes() -> list[dict]:
    """The same sentences, read from the JSON files (the fallback, and what `seed` loads)."""
    global _file_quotes
    from . import verify

    try:
        stamp = max((f.stat().st_mtime for f in verify.STORE.glob("*__*.json")), default=0.0)
    except OSError:
        stamp = 0.0
    if _file_quotes is None or _file_quotes[0] != stamp:
        seen, rows = set(), []
        for c in _stored_checks():
            for q in quotes_from(c):
                if q["_id"] not in seen:
                    seen.add(q["_id"])
                    rows.append(q)
        _file_quotes = (stamp, rows)
    return _file_quotes[1]


# ----------------------------------------------------------------- seed

def seed() -> dict:
    """Load every stored check and its quoted sentences into Atlas, and make sure the search index exists.
    Safe to run again: documents are replaced by id, sentences no check quotes any more are removed."""
    db = _db()
    if db is None:
        return {"backend": FILES, "error": "MongoDB Atlas is not configured or did not answer"}
    from pymongo import ReplaceOne

    checks, quotes = _stored_checks(), file_quotes()
    try:
        if checks:
            db.checks.bulk_write([ReplaceOne({"_id": f"{c.get('intervention_id')}:{c.get('area_id') or 'FI'}"},
                                             {k: v for k, v in c.items() if k != "_id"}, upsert=True) for c in checks],
                                 ordered=False)
        if quotes:
            db.quotes.bulk_write([ReplaceOne({"_id": q["_id"]}, q, upsert=True) for q in quotes], ordered=False)
            db.quotes.delete_many({"_id": {"$nin": [q["_id"] for q in quotes]}})
        db.quotes.create_index("area_id")
        db.runs.create_index([("area_id", 1), ("intervention_id", 1), ("ran_at", -1)])
        index = "exists"
        if not any(i.get("name") == INDEX for i in db.quotes.list_search_indexes()):
            db.quotes.create_search_index({"name": INDEX, "definition": INDEX_DEFINITION})
            index = "created"
    except Exception as e:  # noqa: BLE001
        _failed()
        return {"backend": FILES, "error": type(e).__name__}
    return {"backend": ATLAS, "checks": len(checks), "quotes": len(quotes), "search_index": index}


# ----------------------------------------------------------------- every live run is kept

def log_run(res: dict, outcome: str | None = None) -> None:
    """Keep one live run (in the background; a failure here never reaches the visitor)."""
    if not uri() or not res or res.get("error"):
        return
    doc = {
        "intervention_id": str(res.get("intervention_id") or ""), "area_id": str(res.get("area_id") or "FI"),
        "ran_at": res.get("checked_at"), "outcome": outcome, "advice": res.get("advice"),
        "in_use_here": res.get("in_use_here"), "verdict": res.get("verdict"), "seconds": res.get("seconds"),
        "searches": res.get("searches"), "pages_read": len(res.get("pages_read") or []),
        "quotes_dropped": res.get("quotes_dropped"), "model": res.get("model"),
        "search_backend": res.get("search_backend"), "queries": res.get("queries") or [],
        "sources": [{k: s.get(k) for k in ("url", "title", "quote", "about")} for s in res.get("sources") or []],
    }

    def work():
        db = _db()
        if db is None:
            return
        try:
            db.runs.insert_one(doc)
        except Exception:  # noqa: BLE001
            _failed()

    threading.Thread(target=work, daemon=True).start()


def history(area_id: str | None = None) -> dict:
    """Per action of one county: how many live runs are kept, and how many gave each advice."""
    area = area_id or "FI"
    db = _db()
    if db is None:
        return {"backend": FILES, "area_id": area, "actions": []}
    try:
        rows = list(db.runs.aggregate([
            {"$match": {"area_id": area}},
            {"$sort": {"ran_at": -1}},
            {"$group": {"_id": "$intervention_id", "runs": {"$sum": 1}, "last_run": {"$first": "$ran_at"},
                        "advice": {"$push": "$advice"}}},
            {"$sort": {"_id": 1}},
        ]))
    except Exception:  # noqa: BLE001
        _failed()
        return {"backend": FILES, "area_id": area, "actions": []}
    out = []
    for r in rows:
        counts: dict[str, int] = {}
        for a in r.get("advice") or []:
            counts[str(a)] = counts.get(str(a), 0) + 1
        out.append({"intervention_id": r["_id"], "runs": r["runs"], "last_run": r.get("last_run"), "advice": counts})
    return {"backend": ATLAS, "area_id": area, "actions": out}


def stats() -> dict:
    fq = file_quotes()
    out = {"backend": FILES, "quotes": len(fq), "checks": len({(q["intervention_id"], q["area_id"]) for q in fq}),
           "counties": len({q["area_id"] for q in fq if q["area_id"] != "FI"}), "runs": None}
    db = _db()
    if db is None:
        return out
    try:
        n = db.quotes.estimated_document_count()
        if n:
            out.update(backend=ATLAS, quotes=n, checks=db.checks.estimated_document_count(),
                       runs=db.runs.estimated_document_count())
    except Exception:  # noqa: BLE001
        _failed()
    return out


# ----------------------------------------------------------------- search

SHOWN = ("intervention_id", "intervention_name_en", "area_id", "area_name_en", "url", "domain", "title", "quote",
         "about", "advice")


def _parts(quote: str, words: list[str]) -> list[dict]:
    """The sentence cut into pieces, the matched words marked."""
    words = sorted({w for w in words if w and w.strip()}, key=len, reverse=True)
    if not words:
        return [{"t": quote, "hit": False}]
    out, at = [], 0
    for m in re.finditer("|".join(re.escape(w) for w in words), quote, flags=re.IGNORECASE):
        if m.start() > at:
            out.append({"t": quote[at:m.start()], "hit": False})
        out.append({"t": m.group(0), "hit": True})
        at = m.end()
    if at < len(quote):
        out.append({"t": quote[at:], "hit": False})
    return out or [{"t": quote, "hit": False}]


def _short(name: str | None) -> str:
    return re.sub(r" wellbeing services county$", "", name or "")


def _answer(backend: str, q: str, area_id: str | None, hits: list[dict], limit: int = 30) -> dict:
    """One row per sentence: counties that share a university hospital often quote the same page, and two actions
    of one county the same sentence. Each row lists the counties and actions it was quoted for."""
    rank = {"in_use": 0, "effect": 1}
    rows: dict[tuple, dict] = {}
    for h in hits:
        key = (h.get("url"), h.get("quote"))
        r = rows.get(key)
        if r is None:
            r = rows[key] = {k: h.get(k) for k in ("url", "domain", "title", "quote", "about", "parts")}
            r.update(areas=[], actions=[])
        if rank.get(h.get("about"), 2) < rank.get(r["about"], 2):
            r["about"] = h.get("about")
        area = {"id": h.get("area_id"), "name": _short(h.get("area_name_en"))}
        if area not in r["areas"]:
            r["areas"].append(area)
        if h.get("intervention_name_en") not in r["actions"]:
            r["actions"].append(h.get("intervention_name_en"))
    out = list(rows.values())[:limit]
    return {"backend": backend, "query": q, "area_id": area_id, "hits": out,
            "counties": sorted({a["name"] for h in out for a in h["areas"] if a["id"] != "FI"})}


def _search_files(q: str, area_id: str | None, limit: int) -> list[dict]:
    words = [w for w in re.findall(r"\w+", q.lower()) if len(w) >= 2]
    scored = []
    for row in file_quotes():
        if area_id and row["area_id"] != area_id:
            continue
        text, more = row["quote"].lower(), f"{row['title']} {row['intervention_name_en']} {row['area_name_en']}".lower()
        got = sum(3 for w in words if w in text) + sum(1 for w in words if w in more)
        if got:
            scored.append((got, row))
    scored.sort(key=lambda x: -x[0])
    return [{**{k: r.get(k) for k in SHOWN}, "parts": _parts(r["quote"], words)} for _, r in scored[:limit * 3]]


def search(q: str, area_id: str | None = None, limit: int = 30) -> dict:
    """Sentences the checks quoted that match `q`, best first. Atlas Search when it answers, else a word match
    over the files."""
    q = " ".join((q or "").split())[:120]
    limit = max(1, min(60, int(limit)))
    if len(q) < 2:
        return _answer(FILES, q, area_id, [])
    db = _db()
    if db is not None:
        both = ["quote", {"value": "quote", "multi": "en"}]
        compound: dict = {"should": [
            {"text": {"query": q, "path": both, "fuzzy": {"maxEdits": 1, "prefixLength": 3},
                      "score": {"boost": {"value": 3}}}},
            {"text": {"query": q, "path": ["title", "intervention_name_en", "area_name_en"]}},
        ], "minimumShouldMatch": 1}
        if area_id:
            compound["filter"] = [{"equals": {"path": "area_id", "value": area_id}}]
        try:
            rows = list(db.quotes.aggregate([
                {"$search": {"index": INDEX, "compound": compound, "highlight": {"path": both}}},
                {"$limit": limit * 3},
                {"$project": {**{k: 1 for k in SHOWN}, "_id": 0, "hl": {"$meta": "searchHighlights"}}},
            ]))
            hits = []
            for r in rows:
                words = [t["value"] for h in r.pop("hl", None) or [] for t in h.get("texts") or [] if t.get("type") == "hit"]
                hits.append({**r, "parts": _parts(r.get("quote") or "", words)})
            # An index that is still building answers with nothing: let the files answer until it is ready.
            if hits or _index_ready(db):
                return _answer(ATLAS, q, area_id, hits, limit)
        except Exception:  # noqa: BLE001
            _failed()
    return _answer(FILES, q, area_id, _search_files(q, area_id, limit), limit)


_ready = False


def _index_ready(db) -> bool:
    global _ready
    if not _ready:
        try:
            _ready = any(i.get("name") == INDEX and i.get("queryable") for i in db.quotes.list_search_indexes())
        except Exception:  # noqa: BLE001
            return False
    return _ready


def main(argv: list[str]) -> int:
    if argv[:1] == ["seed"]:
        print(json.dumps(seed(), indent=1))
    elif argv[:1] == ["search"] and len(argv) > 1:
        r = search(" ".join(argv[1:]))
        print(r["backend"], len(r["hits"]), "hits;", ", ".join(r["counties"]))
        for h in r["hits"][:8]:
            print(f"- [{', '.join(a['name'] for a in h['areas'])} · {h['about']}] "
                  + "".join(f"<{p['t']}>" if p["hit"] else p["t"] for p in h["parts"])[:220])
    elif argv[:1] == ["stats"]:
        print(json.dumps(stats(), indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
