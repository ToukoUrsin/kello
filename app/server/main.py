"""Kello API (FastAPI, port 8742). Run via app/run.sh.

Real data and model outputs are used when present; otherwise flagged fixtures
("fixture": true) so the UI can show a "sample data" badge.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import importlib
import inspect
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

SERVER = Path(__file__).resolve().parent
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import frontpage  # noqa: E402
import plan as plan_mod  # noqa: E402
import providers  # noqa: E402
import stage as stage_mod  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("kello")

DIST = Path(os.environ.get("KELLO_DIST") or SERVER.parent / "web" / "dist")  # KELLO_DIST: serve another build while testing
UPLOADS = SERVER / "cache" / "uploads"
REPORTS = SERVER / "cache"
EXAMPLES = SERVER / "integrations" / "examples"
SCIENCE = SERVER.parents[1] / "science" / "out"
# The reader's own prompt says "extract every value"; on a 60-page registry report that overruns the model's
# output limit and the JSON comes back cut off. The hint keeps one read to what a county decision needs.
DEFAULT_HINT = ("Differences between areas in lung cancer care. Return at most 70 values, choosing in this order: "
                "(1) days from diagnosis to treatment, by collaborative area and treatment type; "
                "(2) shares of patients treated (surgery, radiotherapy, drug therapy, curative intent, no treatment) by wellbeing services county or collaborative area; "
                "(3) survival by area; (4) national totals for the same indicators. "
                "Skip single-year time series, age groups, cell types and stage breakdowns unless nothing else is reported.")
READ_TIMEOUT_S = 480

app = FastAPI(title="Kello API", version="0.1")
app.add_middleware(GZipMiddleware, minimum_size=2000)


class SimulateBody(BaseModel):
    area_id: str
    interventions: list[str] = Field(default_factory=list)
    seed: int | None = None


class OptimizeBody(BaseModel):
    scope: str
    budget_eur: float = Field(ge=0, le=1e9)
    objective: str | None = None
    exclude: list[str] = Field(default_factory=list)


class SiteBody(BaseModel):
    lat: float = Field(ge=59, le=71)
    lon: float = Field(ge=19, le=32)
    kind: str = "radiotherapy"


class ScenarioBody(BaseModel):
    sites: list[SiteBody] = Field(default_factory=list, max_length=6)
    cost_eur_per_year: float | None = Field(default=None, ge=0, le=1e9)


class CurveBody(BaseModel):
    scope: str
    objective: str | None = None
    exclude: list[str] = Field(default_factory=list)


class SimulatePlanBody(BaseModel):
    scope: str
    budget_eur: float = Field(ge=0, le=1e9)
    objective: str | None = None
    exclude: list[str] = Field(default_factory=list)
    runs: int = Field(default=300, ge=50, le=1000)
    seed: int = 1


class VerifyBody(BaseModel):
    intervention_id: str
    area_id: str | None = None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _not_found(what: str):
    raise HTTPException(status_code=404, detail=f"Unknown {what}")


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):
    body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/api/status")
def status():
    return providers.status()


@app.get("/api/geo")
def geo():
    return providers.geo()


def _json(key: str, fn) -> Response:
    """A GET answered from memory: the JSON is serialised once and reused until a data or model file changes."""
    return Response(providers.json_bytes(key, fn), media_type="application/json")


@app.get("/api/overview")
def overview():
    return _json("overview", providers.overview)


@app.get("/api/areas")
def areas():
    return providers.areas_list()


@app.get("/api/areas/{area_id}")
def area(area_id: str):
    try:
        return providers.area(area_id)
    except KeyError:
        _not_found(f"area {area_id}")


@app.get("/api/interventions")
def interventions():
    ivs, fx = providers.interventions()
    roadmap, rfx = providers.roadmap_measures()
    out = {"interventions": ivs, "roadmap_measures": roadmap}
    if fx or rfx:
        out["fixture"] = True
    return out


@app.post("/api/simulate")
def simulate(body: SimulateBody):
    try:
        return providers.simulate(body.area_id, body.interventions, body.seed)
    except KeyError as e:
        _not_found(f"area or intervention {e}")


@app.post("/api/optimize")
def optimize(body: OptimizeBody):
    try:
        return providers.optimize(body.scope, body.budget_eur, body.objective, body.exclude)
    except KeyError as e:
        _not_found(f"scope {e}")


@app.get("/api/stage")
def stage():
    return Response(providers.json_bytes("stage_json", stage_mod.stage), media_type="application/json")


@app.post("/api/scenario")
def scenario(body: ScenarioBody):
    try:
        return stage_mod.scenario([s.model_dump() for s in body.sites], body.cost_eur_per_year)
    except KeyError as e:
        _not_found(f"data {e}")


@app.post("/api/budget-curve")
def budget_curve(body: CurveBody):
    try:
        return stage_mod.budget_curve(body.scope, body.objective, body.exclude)
    except KeyError as e:
        _not_found(f"scope {e}")


@app.post("/api/simulate-plan")
def simulate_plan(body: SimulatePlanBody):
    try:
        return stage_mod.simulate_plan(body.scope, body.budget_eur, body.exclude, body.runs, body.seed, body.objective)
    except KeyError as e:
        _not_found(f"scope {e}")


@app.get("/api/sources")
def sources():
    return providers.sources()


@app.get("/api/reader")
def reader():
    out = dict(providers.reader())
    # "values" = what one live read returned (capped by the hint); "in_kello" = rows of that document in the dataset the map uses.
    in_kello = {str(d.get("url")).rstrip("/"): d.get("rows") for d in out.get("documents") or []}
    out["pre_read"] = [{**p, "in_kello": in_kello.get(str(p["url"]).rstrip("/"))} for p in _pre_read()]
    return out


@app.get("/api/science")
def science():
    return providers.science()


@app.get("/api/goal3")
def goal3():
    """Strategy Goal 3 scoreboard: survival targets, the mortality target, and age-standardised county rates by cancer."""
    try:
        return _json("goal3", frontpage.goal3)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail={"error": "Goal 3 data is not loaded", "detail": str(e)})


@app.get("/api/expert-review")
def expert_review():
    """Words of a named clinician or sponsor expert who has looked at a plan. Shown only with their consent; empty until then."""
    try:
        doc = json.loads((providers.DATA / "processed" / "expert_review.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"reviews": []}
    ok = [r for r in doc.get("reviews") or [] if isinstance(r, dict) and r.get("consent") is True and str(r.get("quote_en") or "").strip() and str(r.get("name") or "").strip()]
    return {"reviews": ok}


@app.get("/api/funnel")
def funnel():
    """County funnel plot of the curative-intent share, from the registry's counts, with exact binomial limits."""
    try:
        return _json("funnel", frontpage.funnel)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail={"error": "County counts are not loaded", "detail": str(e)})


@app.on_event("startup")
def _warm_memory():
    """Fill the in-memory answers in the background so the first visitor does not pay for them."""
    def run():
        t0 = time.time()
        try:
            providers.json_bytes("overview", providers.overview)
            for fn in (providers.geo, providers.sources, frontpage.funnel, frontpage.goal3):
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    log.info("warm %s skipped: %s", fn.__name__, e)
            for a in [x["id"] for x in providers.areas_list()] + ["FI"]:
                providers.area(a)
                providers.optimize(a, 1_000_000)
            log.info("memory warmed in %.1f s", time.time() - t0)
        except Exception:  # noqa: BLE001
            log.exception("warming memory failed")
    threading.Thread(target=run, name="kello-warm", daemon=True).start()


# ---- plan -----------------------------------------------------------------

def _plan_args(area_id: str, budget_eur: float, lang: str, objective: str | None = None):
    if lang not in ("fi", "en"):
        raise HTTPException(status_code=400, detail="lang must be fi or en")
    if objective not in (None, "", "curative", "deaths", "gap"):
        raise HTTPException(status_code=400, detail="objective must be curative, deaths or gap")
    if budget_eur <= 0:
        raise HTTPException(status_code=400, detail="budget_eur must be positive")
    try:
        providers.area(area_id)
    except KeyError:
        _not_found(f"area {area_id}")


def _without(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()][:20]


@app.get("/api/plan/{area_id}")
async def plan(area_id: str, budget_eur: float = 1_000_000, lang: str = "en", refresh: bool = False, objective: str | None = None,
               without: str | None = None):
    """`without`: comma-separated measure ids left out of the plan (already in place, or switched off on the county page)."""
    _plan_args(area_id, budget_eur, lang, objective)
    async for event, payload in plan_mod.generate(area_id, budget_eur, lang, refresh, objective or None, _without(without)):
        if event == "done":
            return payload
        if event == "error":
            raise HTTPException(status_code=int(payload.get("status") or 502), detail=payload)
    raise HTTPException(status_code=500, detail="plan generator ended without a result")


@app.get("/api/plan/{area_id}/stream")
async def plan_stream(area_id: str, budget_eur: float = 1_000_000, lang: str = "en", refresh: bool = False, objective: str | None = None,
                      without: str | None = None):
    _plan_args(area_id, budget_eur, lang, objective)

    async def gen():
        try:
            async for event, payload in plan_mod.generate(area_id, budget_eur, lang, refresh, objective or None, _without(without)):
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            log.exception("plan stream failed")
            yield f"event: error\ndata: {json.dumps({'error': 'Plan generation failed', 'detail': str(e)[:300]})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- integrations (owned by another agent) ----------------------------------

def _integration(module: str, fn: str):
    try:
        importlib.invalidate_caches()
        mod = importlib.import_module(module)
        return getattr(mod, fn)
    except Exception as e:  # noqa: BLE001 - missing package, missing deps or missing function
        log.info("integration %s.%s unavailable: %s", module, fn, e)
        raise HTTPException(status_code=503, detail={"error": "integration not configured", "integration": f"{module}.{fn}"})


async def _call(fn, *args, **kwargs):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


try:  # /api/verify/stream|latest, /api/scout*, /api/read-report/keep|kept|charts (integrations/api.py)
    from integrations.api import router as _integrations_router
    app.include_router(_integrations_router)
except Exception:  # noqa: BLE001 - the app must start without the integrations
    log.exception("integration routes unavailable")


@app.post("/api/verify")
async def verify(body: VerifyBody):
    # The check is a search-and-read loop (integrations/verify.py); the question, the county names and
    # the stored latest check per (intervention, area) live there. Blocks 25-60 s; the UI can stream instead.
    fn = _integration("integrations.api", "run_verify")
    return await fn(body.intervention_id, body.area_id)


# ---- read a report (Gemini) -------------------------------------------------
# Reads take 85-200 s, so the UI starts a job and polls; results are cached on disk by URL.

_jobs: dict[str, dict] = {}


def _report_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


def _report_cached(url: str) -> dict | None:
    """A finished read of this URL: our disk cache first, then the reads kept under integrations/examples."""
    f = REPORTS / f"report_{_report_key(url)}.json"
    if f.exists():
        try:
            res = json.loads(f.read_text())
            # A read that found no values is stored too (with Gemini's note), but served for one hour only so it can be retried.
            if res.get("extracted") or time.time() - f.stat().st_mtime < 3600:
                res.setdefault("notes_en", res.get("notes") or "")
                res.setdefault("read_at", dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds"))
                return {**res, "cached": True}
        except Exception:  # noqa: BLE001
            pass
    for ex in sorted(EXAMPLES.glob("read_report_*.json")):
        try:
            data = json.loads(ex.read_text())
        except Exception:  # noqa: BLE001
            continue
        for item in (data if isinstance(data, list) else [data]):
            doc = item.get("document") if isinstance(item, dict) else None
            if isinstance(doc, dict) and doc.get("url") == url.strip() and item.get("extracted"):
                return {"notes_en": item.get("notes") or "", "read_at": item.get("read_at"), **item,
                        "cached": True, "cached_from": f"integrations/examples/{ex.name}"}
    return None


def _pre_read() -> list[dict]:
    """Reports already read, offered in the UI so a live demo is instant."""
    out, seen = [], set()
    files = sorted(REPORTS.glob("report_*.json"), key=lambda p: -p.stat().st_mtime) + sorted(EXAMPLES.glob("read_report_*.json"))
    for f in files:
        try:
            data = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        for item in (data if isinstance(data, list) else [data]):
            doc = item.get("document") if isinstance(item, dict) else None
            url = (item.get("requested_url") if isinstance(item, dict) else None) or (doc.get("url") if isinstance(doc, dict) else None)
            if not url or url in seen or not str(url).startswith("http") or not item.get("extracted"):
                continue
            seen.add(url)
            out.append({"url": url, "title": (doc or {}).get("title") if isinstance(doc, dict) else None, "values": len(item["extracted"]),
                        "pages": (doc or {}).get("pages") if isinstance(doc, dict) else None})
    return out


async def _read(fn, source: str, hint: str, url: str | None) -> dict:
    try:
        res = await asyncio.wait_for(_call(fn, source, hint), timeout=READ_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise RuntimeError(f"no result after {READ_TIMEOUT_S // 60} minutes; the report may be too long for one read. Add a narrower 'look for' note and try again") from None
    if not isinstance(res, dict):
        raise RuntimeError("The reader returned an unexpected result")
    res.setdefault("extracted", [])
    res.setdefault("notes_en", res.get("notes") or "")  # what Gemini said about the document; shown in the UI even with 0 values
    res["read_at"] = _now()
    res["cached"] = False
    if url:
        res["requested_url"] = url
        f = REPORTS / f"report_{_report_key(url)}.json"
        # every read is stored by URL; an empty read never replaces a stored read that has values
        if res["extracted"] or not (f.exists() and (json.loads(f.read_text()).get("extracted"))):
            f.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return res


async def _run_job(job: dict, fn, source: str, hint: str, url: str | None):
    try:
        job["result"] = await _read(fn, source, hint, url)
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        log.exception("read_report job failed")
        detail = str(e)
        if "EOF while parsing" in detail or "json_invalid" in detail:
            detail = "the report holds more values than fit in one read. Add a narrower 'look for' note (for example one table or one indicator) and try again"
        job.update(status="error", error="Reading the report failed", detail=detail[:300])
    job["finished"] = time.time()


def _job_view(job: dict) -> dict:
    out = {k: job[k] for k in ("job_id", "status", "what") if k in job}
    out["elapsed_s"] = round((job.get("finished") or time.time()) - job["started"], 1)
    for k in ("result", "error", "detail"):
        if k in job:
            out[k] = job[k]
    return out


async def _report_source(request: Request) -> tuple[str | None, str | None, str | None, bool]:
    """(source, url, hint, refresh) from a JSON body or a multipart upload."""
    ctype = request.headers.get("content-type", "")
    source, url, hint, refresh = None, None, None, False
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        hint = form.get("hint") or None
        up = form.get("file")
        if up is not None and hasattr(up, "read"):
            data = await up.read()
            if len(data) > 40 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="File is larger than 40 MB")
            UPLOADS.mkdir(parents=True, exist_ok=True)
            suffix = Path(getattr(up, "filename", "") or "upload.pdf").suffix.lower()[:8] or ".pdf"
            path = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
            path.write_bytes(data)
            source = str(path)
        elif form.get("url"):
            url = str(form.get("url")).strip()
    else:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        body = body if isinstance(body, dict) else {}
        url, hint, refresh = (str(body["url"]).strip() if body.get("url") else None), body.get("hint"), bool(body.get("refresh"))
    if url:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="url must start with http:// or https://")
        source = url
    if not source:
        raise HTTPException(status_code=400, detail="Send a JSON body with url, or a multipart upload with file")
    return source, url, hint or DEFAULT_HINT, refresh


@app.post("/api/read-report/start")
async def read_report_start(request: Request):
    """Start a read and return at once: {job_id, status}. A URL read before returns status "done" with the result."""
    source, url, hint, refresh = await _report_source(request)
    if url and not refresh:
        hit = _report_cached(url)
        if hit:
            return {"job_id": None, "status": "done", "what": url, "elapsed_s": 0, "result": hit}
        running = next((j for j in _jobs.values() if j.get("url") == url and j["status"] == "running"), None)
        if running:
            return _job_view(running)
    fn = _integration("integrations.gemini_reader", "read_report")
    job = {"job_id": uuid.uuid4().hex[:12], "status": "running", "what": url or "uploaded file", "url": url, "started": time.time()}
    _jobs[job["job_id"]] = job
    job["task"] = asyncio.create_task(_run_job(job, fn, source, hint, url))
    for old in [k for k, j in _jobs.items() if j.get("finished") and time.time() - j["finished"] > 3600]:
        _jobs.pop(old, None)
    return _job_view(job)


@app.get("/api/read-report/job/{job_id}")
def read_report_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        _not_found(f"read job {job_id}")
    return _job_view(job)


@app.post("/api/read-report")
async def read_report(request: Request):
    """Contract endpoint: blocks until the read is done (85-200 s for a new report; instant from cache)."""
    source, url, hint, refresh = await _report_source(request)
    if url and not refresh:
        hit = _report_cached(url)
        if hit:
            return hit
    fn = _integration("integrations.gemini_reader", "read_report")
    try:
        return await _read(fn, source, hint, url)
    except Exception as e:  # noqa: BLE001
        log.exception("read_report failed")
        raise HTTPException(status_code=502, detail={"error": "Reading the report failed", "detail": str(e)[:300]})


@app.api_route("/api/{rest:path}", methods=["GET", "POST"])
def api_404(rest: str):
    raise HTTPException(status_code=404, detail=f"No such endpoint: /api/{rest}")


# ---- Claude Science outputs, read-only ----------------------------------------

@app.get("/science/{path:path}")
def science_file(path: str):
    f = (SCIENCE / path).resolve()
    if not path or SCIENCE.resolve() not in f.parents or not f.is_file() or any(p.startswith(".") for p in Path(path).parts):
        raise HTTPException(status_code=404, detail="No such file")
    return FileResponse(f)


# ---- frontend ---------------------------------------------------------------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
else:
    @app.get("/")
    def no_frontend():
        return {"error": "frontend not built", "hint": "cd app/web && pnpm install && pnpm build"}
