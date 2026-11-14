"""HTTP routes of the two integrations (included by main.py before its catch-all).

Live web check (Oxylabs + Claude, or Gemini when Claude is not reachable)
    POST /api/verify {intervention_id, area_id?}             -> result            (handler in main.py calls run_verify)
    GET  /api/verify/stream?intervention_id=&area_id=        -> SSE: step, done | error
    GET  /api/verify/latest?area_id=                         -> {area_id, checks:[result, ...]}
County scout (same loop)
    POST /api/scout {area_id}                                -> result
    GET  /api/scout/stream?area_id=                          -> SSE: step, done | error
    GET  /api/scout/latest?area_id=                          -> result | {area_id, findings: null}
Live runs as jobs (the run goes on whatever the client does; a lost connection loses nothing)
    POST /api/verify/start {intervention_id, area_id?}       -> {job_id, status, steps, next, result?}  (joins a running check)
    POST /api/scout/start {area_id}                          -> same
    GET  /api/live/{job_id}?since=N                          -> poll: steps from N on, result once ended
    GET  /api/live/{job_id}/stream?since=N                   -> SSE: job, step (with id), done | error
What is connected
    GET  /api/integrations/status                            -> {search, claude, gemini, model, stored_checks, stored_scouts}
Report reader (Gemini)
    POST /api/read-report/keep {url, row_index}              -> {added, row}
    GET  /api/read-report/kept[?url=]                        -> {count, rows}
    GET  /api/read-report/charts                             -> {count, rows, accuracy}   (figures read into numbers)

SSE events: `event: step` carries one trace entry, sent twice per call (status "running", then
"done" with result_en and ms); `event: done` carries the full result. A second request for a check
that is already running joins it.

The check and the scout do not end in an error: when Oxylabs or both models fail, or the run takes
longer than its hard limit, the last good result for the same (measure, county) is sent as the
result with `from_cache: true`, `checked_at` and `live_error`. Only when nothing is stored either
does the result carry an `error` field (HTTP 200, plain `verdict_en`); `event: error` is left for
a crash with nothing stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("kello.integrations")
router = APIRouter()

SERVER = Path(__file__).resolve().parents[1]
ROOT = SERVER.parents[1]
REPORTS = SERVER / "cache"
EXAMPLES = Path(__file__).resolve().parent / "examples"
KEPT = ROOT / "data" / "processed" / "reader_added.jsonl"
CHART_ROWS = ROOT / "data" / "processed" / "gemini_chart_read.jsonl"
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------- jobs (one thread per run)

_jobs: dict[str, dict] = {}      # key (what is checked) -> latest job; a second start of the same key joins it
_by_id: dict[str, dict] = {}     # job id -> job, kept 30 min after it ends so a client that lost its connection can fetch the result
_jobs_lock = threading.Lock()


def _start(key: str, fn, *args, fallback=None, limit_s: float = 150.0) -> dict:
    """Start `fn(*args, on_event=...)` in a thread, or join the run with the same key.
    `fallback(reason) -> result | None` answers when the run crashes or passes `limit_s`."""
    with _jobs_lock:
        job = _jobs.get(key)
        if job and not job["done"] and "settled" not in job:
            return job
        for k in [k for k, j in _jobs.items() if j["done"] and time.time() - j["finished"] > 600]:
            _jobs.pop(k, None)
        job = {"key": key, "id": uuid.uuid4().hex[:12], "events": [], "done": False, "result": None, "error": None,
               "finished": 0.0, "started": time.time(), "fallback": fallback, "limit_s": limit_s}
        _jobs[key] = job
        _by_id[job["id"]] = job
        for jid in [i for i, j in _by_id.items() if j["done"] and time.time() - j["finished"] > 1800]:
            _by_id.pop(jid, None)

    def work():
        try:
            job["result"] = fn(*args, on_event=job["events"].append)
        except Exception as exc:  # noqa: BLE001
            log.exception("integration run %s failed", key)
            job["error"] = str(exc)[:300]
        job["finished"] = time.time()
        job["done"] = True

    threading.Thread(target=work, name=f"kello-{key}", daemon=True).start()
    return job


def _settled(job: dict) -> tuple[dict | None, str | None]:
    """(result, error) once the job has an answer, else (None, None). A crash or a run past its hard
    limit is answered with the stored result when there is one."""
    late = not job["done"] and time.time() - job["started"] > job["limit_s"]
    if not job["done"] and not late:
        return None, None
    if job["done"] and not job["error"]:
        return job["result"], None
    if "settled" in job:
        return job["settled"]
    reason = job["error"] or f"the live run did not finish within {int(job['limit_s'])} s"
    old = None
    if job["fallback"]:
        try:
            old = job["fallback"](reason)
        except Exception:  # noqa: BLE001
            log.exception("fallback for %s failed", job["key"])
    job["settled"] = (old, None) if old is not None else (None, reason)
    if not job["done"]:  # past its hard limit: the answer is given now, the thread may still finish in the background
        job["finished"] = time.time()
    return job["settled"]


def _plain_failure(error: str | None) -> str:
    from . import verify

    return verify.failure_en(error)


def job_view(job: dict, since: int = 0) -> dict:
    """What a client needs to follow a run without a stream: the steps from `since` on, and the result once it ends.
    status: running | done (a result, possibly the stored one with live_outcome "failed") | failed (nothing to show)."""
    result, error = _settled(job)
    events = job["events"]
    since = max(0, min(int(since or 0), len(events)))
    out = {"job_id": job["id"], "status": "done" if result is not None else "failed" if error else "running",
           "elapsed_s": round(((job["finished"] or time.time()) if (result is not None or error) else time.time()) - job["started"], 1),
           "since": since, "next": len(events), "steps": events[since:]}
    if result is not None:
        out["result"] = result
    if error:
        out["error_en"] = _plain_failure(error)
    return out


async def _wait(job: dict) -> dict:
    while True:
        result, error = _settled(job)
        if result is not None:
            return result
        if error:
            raise HTTPException(status_code=502, detail={"error": "The live web run failed", "detail": error})
        await asyncio.sleep(0.2)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _stream(job: dict, fail: str, since: int = 0) -> StreamingResponse:
    async def gen():
        sent, last = max(0, int(since or 0)), time.time()
        yield _sse("job", {"job_id": job["id"], "since": sent})
        while True:
            events = job["events"]
            while sent < len(events):
                yield f"id: {sent + 1}\n" + _sse("step", events[sent])
                sent += 1
                last = time.time()
            result, error = _settled(job)
            if (result is not None or error) and sent >= len(job["events"]):
                break
            if time.time() - last > 5:  # a named event, so the page can tell a quiet run from a dead connection
                yield _sse("ping", {"elapsed_s": round(time.time() - job.get("started", time.time()))})
                last = time.time()
            await asyncio.sleep(0.15)
        if result is not None:
            yield _sse("done", result)
        else:
            yield _sse("error", {"error": fail, "detail": _plain_failure(error), "error_en": _plain_failure(error)})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


class StartBody(BaseModel):
    intervention_id: str | None = None
    area_id: str | None = None


def _job(job_id: str) -> dict:
    job = _by_id.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"error": "No such run", "detail": "the run is not known to this server; it may have restarted",
                                                     "gone": True})
    return job


@router.get("/api/live/{job_id}")
def live_job(job_id: str, since: int = 0):
    """Poll a live run (web check or scout): new steps since `since`, and the result once it has ended."""
    return job_view(_job(job_id), since)


@router.get("/api/live/{job_id}/stream")
async def live_job_stream(job_id: str, since: int = 0):
    """SSE for a run already started: `job`, then `step` events from `since` on, then `done` (result) or `error`."""
    return _stream(_job(job_id), "The live run failed", since)


@router.post("/api/verify/start")
def verify_start(body: StartBody):
    """Start a web check, or join the one running for the same measure and county. Returns at once."""
    if not body.intervention_id:
        raise HTTPException(status_code=400, detail="intervention_id is required")
    return job_view(_verify_job(body.intervention_id, body.area_id))


@router.post("/api/scout/start")
def scout_start(body: StartBody):
    """Start a county scout, or join the one running for the same county. Returns at once."""
    return job_view(_scout_job(body.area_id or ""))


@router.get("/api/archive")
def archive():
    """Existing Internet Archive copies of the registry pages Kello cites (looked up once, stored)."""
    from . import archive_copies

    return archive_copies.load()


# ----------------------------------------------------------------- demo reset (back to the state the server started with)

def _demo_files() -> list[Path]:
    from . import scout, verify

    return sorted(verify.STORE.glob("*.json")) + sorted(scout.STORE.glob("*.json")) + ([KEPT] if KEPT.exists() else [])


def _snapshot() -> dict[Path, bytes]:
    out: dict[Path, bytes] = {}
    for f in _demo_files():
        try:
            out[f] = f.read_bytes()
        except OSError:
            pass
    return out


try:
    _SEED = _snapshot()   # stored web checks, county scouts and kept report rows, as they were at start
except Exception:  # noqa: BLE001 - the app must start without it
    _SEED = {}


@router.post("/api/demo/reset")
def demo_reset():
    """Put the stored web checks, county scouts and kept report rows back to what the server started with,
    and forget finished runs, so a demo always begins from the same screen."""
    restored = removed = 0
    with _jobs_lock:
        for f in _demo_files():
            if f not in _SEED:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        for f, data in _SEED.items():
            try:
                if not f.exists() or f.read_bytes() != data:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                    restored += 1
            except OSError:
                pass
        for d in (_jobs, _by_id):
            for k in [k for k, j in d.items() if j["done"]]:
                d.pop(k, None)
    return {"ok": True, "restored": restored, "removed": removed}


@router.get("/api/integrations/status")
def integrations_status():
    """What a live run would use right now, and how much is stored for when it cannot run."""
    from . import llm, oxylabs, scout, verify

    return {"search": oxylabs.has_credentials(), "claude": llm.claude_ready(), "gemini": llm.gemini_ready(),
            "model": llm.default_model() if llm.any_ready() else None,
            "stored_checks": len(list(verify.STORE.glob("*__*.json"))), "stored_scouts": len(list(scout.STORE.glob("*.json")))}


def _intervention(intervention_id: str) -> dict:
    import providers  # app/server/providers.py (on sys.path when main.py runs)

    ivs, _ = providers.interventions()
    iv = next((i for i in ivs if i["id"] == intervention_id), None)
    if iv is None:
        raise HTTPException(status_code=404, detail=f"Unknown intervention {intervention_id}")
    return iv


def _area(area_id: str | None, required: bool = False) -> str | None:
    from . import counties

    if not area_id or area_id == "FI":
        if required:
            raise HTTPException(status_code=400, detail="area_id must be a county id such as 21")
        return None
    if counties.hints(area_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown area {area_id}")
    return area_id


# ----------------------------------------------------------------- live web check

def _verify_job(intervention_id: str, area_id: str | None) -> dict:
    from . import verify

    iv, area = _intervention(intervention_id), _area(area_id)
    return _start(f"verify:{intervention_id}:{area or 'FI'}", verify.check_measure, iv, area,
                  fallback=lambda why: verify.from_store(intervention_id, area, why), limit_s=verify.BUDGET_S + 45)


async def run_verify(intervention_id: str, area_id: str | None = None) -> dict:
    """POST /api/verify: blocks until the check is done (25-75 s)."""
    return await _wait(_verify_job(intervention_id, area_id))


@router.get("/api/verify/stream")
async def verify_stream(intervention_id: str, area_id: str | None = None):
    return _stream(_verify_job(intervention_id, area_id), "Live web check failed")


@router.get("/api/verify/latest")
def verify_latest(area_id: str | None = None):
    from . import verify

    return {"area_id": area_id or "FI", "checks": verify.latest(area_id)}


# ----------------------------------------------------------------- county scout

class ScoutBody(BaseModel):
    area_id: str


def _scout_job(area_id: str) -> dict:
    from . import scout

    area = _area(area_id, required=True)
    return _start(f"scout:{area}", scout.scout, area, fallback=lambda why: scout.from_store(area, why), limit_s=scout.BUDGET_S + 45)


@router.post("/api/scout")
async def scout_run(body: ScoutBody):
    return await _wait(_scout_job(body.area_id))


@router.get("/api/scout/stream")
async def scout_stream(area_id: str):
    return _stream(_scout_job(area_id), "The county scout failed")


@router.get("/api/scout/latest")
def scout_latest(area_id: str):
    from . import scout

    return scout.latest(area_id) or {"area_id": area_id, "findings": None, "checked_at": None}


# ----------------------------------------------------------------- report reader: keep a row

class KeepBody(BaseModel):
    url: str
    row_index: int


def report_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


def stored_report(url: str) -> dict | None:
    """The stored read of this URL: cache/report_<key>.json, then the reads kept under examples/."""
    f = REPORTS / f"report_{report_key(url)}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for ex in sorted(EXAMPLES.glob("read_report_*.json")):
        try:
            data = json.loads(ex.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in (data if isinstance(data, list) else [data]):
            doc = item.get("document") if isinstance(item, dict) else None
            if isinstance(doc, dict) and url.strip() in (doc.get("url"), item.get("requested_url")):
                return item
    return None


def _jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


_keep_lock = threading.Lock()


@router.post("/api/read-report/keep")
def read_report_keep(body: KeepBody):
    """Add one value of a stored read to Kello as user-added, unverified."""
    url = body.url.strip()
    res = stored_report(url)
    if res is None:
        raise HTTPException(status_code=404, detail="No stored read of this URL; read the report first")
    rows = res.get("extracted") or []
    if not 0 <= body.row_index < len(rows):
        raise HTTPException(status_code=400, detail=f"row_index must be between 0 and {len(rows) - 1}")
    it = rows[body.row_index]
    doc = res.get("document") or {}
    row = {
        "area_id": it.get("area_id"), "area_name": it.get("area"),
        "indicator": it.get("indicator_guess"), "label_en": it.get("label_en") or it.get("label"), "label": it.get("label"),
        "value": it.get("value"), "unit": it.get("unit"), "period": it.get("period"),
        "kind": "target" if it.get("value_kind") == "target" else "measured", "verified": False,
        "read_by": f"gemini:{res.get('model')}", "read_from": it.get("read_from"), "confidence": it.get("confidence"),
        "reader_check": it.get("check"), "quote": it.get("quote"), "page": it.get("page"),
        "source_url": url, "source_title": doc.get("title"), "publisher": doc.get("publisher"),
        "read_at": res.get("read_at"), "row_index": body.row_index, "added_at": _now(), "added_by": "report reader (user-added)",
    }
    with _keep_lock:
        for old in _jsonl(KEPT):
            if old.get("source_url") == url and old.get("quote") == row["quote"] and old.get("value") == row["value"] \
                    and old.get("area_id") == row["area_id"] and old.get("indicator") == row["indicator"]:
                return {"added": False, "already": True, "row": old, "count": len(_jsonl(KEPT))}
        KEPT.parent.mkdir(parents=True, exist_ok=True)
        with KEPT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        count = len(_jsonl(KEPT))
    return {"added": True, "already": False, "row": row, "count": count}


@router.get("/api/read-report/kept")
def read_report_kept(url: str | None = None):
    rows = _jsonl(KEPT)
    if url:
        rows = [r for r in rows if r.get("source_url") == url.strip()]
    return {"count": len(rows), "rows": rows}


@router.get("/api/read-report/charts")
def read_report_charts():
    """Numbers Gemini read off figures that the registry publishes only as images, with the accuracy check."""
    rows = _jsonl(CHART_ROWS)
    acc = None
    try:
        acc = json.loads((EXAMPLES / "chart_read_accuracy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"count": len(rows), "rows": rows, "accuracy": acc}
