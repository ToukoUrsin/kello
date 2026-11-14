"""Data providers: real outputs when present, flagged fixtures otherwise.

Order for every call:  kello_model.api  ->  data/model/*.json  ->  fixtures.
A fixture-backed result always carries "fixture": true.
"""
from __future__ import annotations

import importlib
import inspect
from decimal import ROUND_HALF_UP, Decimal
import json
import logging
import math
import re
import sys
import threading
import time
from pathlib import Path

import fixture_model
import measured as measured_mod

log = logging.getLogger("kello.providers")

SERVER = Path(__file__).resolve().parent
ROOT = SERVER.parents[1]
DATA = ROOT / "data"
FIX = SERVER / "fixtures"
MODEL_DIR = ROOT / "model"

if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

_api = None

# ---- memory cache -------------------------------------------------------------
# Model outputs and data files are answered from memory. Everything is dropped when any input file
# (data/processed, data/evidence, data/model, the model package) gets a newer modification time.
_WATCH = ((DATA / "processed", ("*.json", "*.jsonl", "*.geojson")), (DATA / "evidence", ("*.json",)), (DATA / "model", ("*.json",)),
          (MODEL_DIR / "kello_model", ("*.py",)), (ROOT / "science" / "out", ("*/meta.json",)))
_memo: dict = {}
_memo_lock = threading.Lock()
_key_locks: dict = {}
_stamp_at = [0.0, 0.0]  # (checked at, stamp)


def data_stamp() -> float:
    """Newest modification time of the input files; looked up at most once a second."""
    now = time.monotonic()
    if now - _stamp_at[0] < 1.0:
        return _stamp_at[1]
    newest = 0.0
    for d, pats in _WATCH:
        for pat in pats:
            for f in d.glob(pat):
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
    _stamp_at[0], _stamp_at[1] = now, newest
    return newest


def memo(key, fn, *, keep_errors: bool = False):
    """fn() once per key until an input file changes. Concurrent callers of the same key wait for one computation."""
    stamp = data_stamp()
    hit = _memo.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    with _memo_lock:
        lock = _key_locks.setdefault(key, threading.Lock())
    with lock:
        hit = _memo.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
        val = fn()
        if len(_memo) > 4000:  # budgets typed by hand can pile up; start again rather than grow without bound
            _memo.clear()
        _memo[key] = (stamp, val)
        return val


def json_bytes(key: str, fn) -> bytes:
    """The JSON body for a GET endpoint, serialised once per input state."""
    return memo(("json", key), lambda: json.dumps(_plain(fn()), ensure_ascii=False, separators=(",", ":")).encode())


def _plain(o):
    """numpy scalars and arrays -> plain Python, NaN -> null."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_plain(v) for v in o]
    if hasattr(o, "tolist") and not isinstance(o, (str, bytes)):
        return _plain(o.tolist())
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def kello_api():
    """Return kello_model.api if importable (retried on each call until it works)."""
    global _api
    if _api is not None:
        return _api
    if not (MODEL_DIR / "kello_model").exists():
        return None
    try:
        importlib.invalidate_caches()
        _api = importlib.import_module("kello_model.api")
    except Exception as e:  # noqa: BLE001 - any import-time failure means "not ready"
        log.warning("kello_model not importable: %s", e)
        _api = None
    return _api


def _read(path: Path):
    try:
        if path.exists() and path.stat().st_size > 2:
            return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        log.warning("could not read %s: %s", path, e)
    return None


def _indicator_rows() -> list[dict]:
    """Small public-indicator reader used for pathway context (never model inputs)."""
    def load():
        p = DATA / "processed/indicators.jsonl"
        out = []
        try:
            for line in p.read_text().splitlines():
                if line.strip():
                    try:
                        d = json.loads(line)
                        if isinstance(d, dict): out.append(d)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return out
    return memo("indicator_rows", load)


def _indicator(area_id: str, indicator: str) -> dict | None:
    rows = [r for r in _indicator_rows() if str(r.get("area_id")) == str(area_id) and r.get("indicator") == indicator]
    if not rows:
        return None
    # Periods are ISO-like for THL snapshots and year-like for Sotkanet.  The latest
    # record is the most useful comparison and keeps the source attached to the value.
    row = max(rows, key=lambda r: str(r.get("period") or ""))
    # Keep the public THL page and a reproducible data path with each cube cell.
    # The cube has no page or prose quote for an individual value.
    source = (_read(DATA / "processed/sources.json") or {}).get(row.get("source_id"), {})
    return {**row,
            "source_url": source.get("url"),
            "page": f"THL cube · {row.get('source_id')}",
            "note_en": f"Data path: data/processed/indicators.jsonl (area_id={row.get('area_id')}, indicator={row.get('indicator')}, period={row.get('period')})."}


def _pathway_figure(name: str, value, national, *, label: str, unit: str = "%", kind: str = "measured",
                    direction: str = "higher", source: dict | None = None, note: str | None = None) -> dict:
    source = source or {}
    if value is None or national is None:
        verdict = "not published by county"
    else:
        behind = float(value) < float(national) if direction == "higher" else float(value) > float(national)
        verdict = "here" if behind else f"not where {name} falls behind"
    return {"label_en": label, "value": value, "national": national, "unit": unit, "kind": kind,
            "verdict_en": verdict, "source_id": source.get("source_id"),
            "source_url": source.get("source_url") or source.get("url"),
            "page": source.get("page"), "quote": source.get("quote"), "read_by": source.get("read_by"),
            "period": source.get("period"), "note_en": note}


def _pathway_for(area_id: str, cp: dict | None) -> dict:
    """Four explicit pathway locations, with county-vs-Finland evidence and provenance."""
    cp = cp or {}
    name = cp.get("area_en") or area_id
    stages = {s.get("id"): s for s in cp.get("stages") or []}
    def stage_fig(sid: str, label: str, direction: str = "higher", note: str | None = None):
        s = stages.get(sid) or {}
        return _pathway_figure(name, s.get("value"), s.get("national"), label=label, unit=s.get("unit") or "%",
                               kind=s.get("kind") or "measured", direction=direction, source=s, note=note or s.get("note_en"))
    def ind_fig(ind: str, label: str, direction: str = "lower", note: str | None = None):
        r, n = _indicator(area_id, ind), _indicator("FI", ind)
        if r is None or n is None:
            return _pathway_figure(name, None, None, label=label, direction=direction, note=note)
        context = note or "All patients / all diagnoses, not lung-cancer patients."
        path_note = r.get("note_en")
        if path_note:
            context = f"{context} {path_note}"
        return _pathway_figure(name, r.get("value"), n.get("value"), label=label, unit=r.get("unit") or "%",
                               kind=r.get("kind") or "measured", direction=direction, source=r, note=context)

    def num(sid):
        st = stages.get(sid) or {}
        return (st.get("value"), st.get("national"))
    def quiet(fig):
        # a signal, not a measure of this step: no per-figure verdict
        fig["verdict_en"] = ""
        return fig
    detection = [quiet(stage_fig("alive_1y", "Alive one year after diagnosis", note="An outcome, not a direct measure of how early cancers are found.")),
                 _pathway_figure(name, None, None, label="Stage at diagnosis", note="The registry does not publish stage by county.")]
    referral = [ind_fig("pulmonology_referrals_handled_over_21d_pct", "Lung clinic referrals handled in over 21 days"),
                ind_fig("pulmonology_queue_over_90d_pct", "Lung clinic patients waiting over 90 days")]
    waiting = [stage_fig("time_to_treatment", "Days from diagnosis to first treatment", direction="lower",
                         note="Estimated for the whole university hospital area from the registry's medians; part of a short median comes from how the diagnosis date is set.")]
    treatment = [stage_fig("curative", "Get treatment that aims to cure"),
                 quiet(stage_fig("drug_therapy", "Drug therapy on record"))]

    a1, n1 = num("alive_1y")
    if a1 is None or n1 is None:
        det_v, det_a = "cannot_tell", "Stage at diagnosis is not published by county, so public data cannot say."
    elif float(n1) - float(a1) >= 4:
        det_v = "possibly_here"
        det_a = (f"Stage at diagnosis is not published by county. One-year survival is clearly lower than in Finland ({float(a1):.1f}% against {float(n1):.1f}%), "
                 "which may mean cancers are found later here.")
    else:
        det_v = "cannot_tell"
        det_a = (f"Stage at diagnosis is not published by county. One-year survival is {'close to' if float(a1) < float(n1) + 2 else 'no lower than'} Finland's ({float(a1):.1f}% against {float(n1):.1f}%), "
                 "which does not point to much later diagnosis.")
    ref_known = [f for f in referral if f.get("value") is not None]
    ref_bad = [f for f in ref_known if f.get("verdict_en") == "here"]
    if not ref_known:
        ref_v, ref_a = "cannot_tell", "No county figure on lung clinic referrals is published."
    elif len(ref_bad) == len(ref_known):
        ref_v, ref_a = "here", "The lung clinic handles referrals more slowly than in Finland as a whole. The figures cover all lung patients, not only cancer."
    elif ref_bad:
        ref_v, ref_a = "possibly_here", "One of two lung clinic waiting figures is worse than in Finland. They cover all lung patients, not only cancer."
    else:
        ref_v, ref_a = "not_behind", "The lung clinic handles referrals at least as fast as in Finland as a whole. The figures cover all lung patients, not only cancer."
    t1, tn = num("time_to_treatment")
    if t1 is None or tn is None:
        wait_v, wait_a = "cannot_tell", "Days from diagnosis to treatment are not published by county."
    elif float(t1) <= float(tn) + 1:
        wait_v, wait_a = "not_behind", f"Treatment starts {float(t1):.0f} days after diagnosis in this university hospital area, {float(tn):.0f} in Finland (all treatments together, estimated). No sign that patients here wait longer."
    elif float(t1) <= float(tn) + 5:
        wait_v, wait_a = "possibly_here", f"Treatment starts {float(t1):.0f} days after diagnosis in this university hospital area, {float(tn):.0f} in Finland: slightly longer."
    else:
        wait_v, wait_a = "here", f"Treatment starts {float(t1):.0f} days after diagnosis in this university hospital area, {float(tn):.0f} in Finland. Patients here wait longer."
    c1, cn = num("curative")
    miss = float(((cp.get("missing_patients") or {}).get("total") or {}).get("median") or 0) if isinstance((cp.get("missing_patients") or {}).get("total"), dict) else 0.0
    if c1 is None or cn is None:
        tr_v, tr_a = "cannot_tell", "The registry does not publish this county's treatment figures (too few patients)."
    elif float(c1) < float(cn) - 0.5:
        tr_v = "here"
        tr_a = f"{float(c1):.1f} of 100 patients get treatment that aims to cure, {float(cn):.1f} in Finland. This is where {name} loses patients."
    else:
        tr_v, tr_a = "not_behind", f"{float(c1):.1f} of 100 patients get treatment that aims to cure, {float(cn):.1f} in Finland."
    VERDICT = {"here": "Here", "possibly_here": "Possibly here", "not_behind": "Not here", "cannot_tell": "Cannot tell"}
    steps = [
        {"id": "detection", "label_en": "Found early enough?", "figures": detection, "verdict": det_v, "verdict_en": VERDICT[det_v], "answer_en": det_a,
         "what_not_published_en": "Stage at diagnosis by county. A county can count the share of its new lung cancers found at stage I or II."},
        {"id": "referral", "label_en": "Referred fast enough?", "figures": referral, "verdict": ref_v, "verdict_en": VERDICT[ref_v], "answer_en": ref_a,
         "what_not_published_en": "Days from referral to the first lung clinic visit for lung cancer patients. A county can count them from its own referral dates."},
        {"id": "diagnosis", "label_en": "Treated fast enough after diagnosis?", "figures": waiting, "verdict": wait_v, "verdict_en": VERDICT[wait_v], "answer_en": wait_a,
         "what_not_published_en": "Days from diagnosis to treatment by county (only the five university hospital areas are published)."},
        {"id": "treatment", "label_en": "Given treatment that aims to cure?", "figures": treatment, "verdict": tr_v, "verdict_en": VERDICT[tr_v], "answer_en": tr_a,
         "what_not_published_en": "Biomarker testing by county. A county can count the share of advanced non-squamous patients with a full biomarker result within 14 days of biopsy."},
    ]
    s1, sn = num("surgery")
    stage_bound = None
    if tr_v == "here":
        stage_bound = ("Public data cannot rule out that cancers are found later here. "
                       + (f"One-year survival ({float(a1):.1f}% against {float(n1):.1f}%) " if a1 is not None and n1 is not None else "")
                       + (f"and the operated share ({float(s1):.1f}% against {float(sn):.1f}%) " if s1 is not None and sn is not None else "")
                       + "are signals, not proof. The 50-chart audit records each patient's stage and answers it.")
    # What the plan does about the drug finding: the audit counts biomarker tests, and the next action is named with its owner and cost.
    drug_next = None
    rx = next((i for i in (_read(DATA / "evidence/interventions.json") or []) if isinstance(i, dict) and i.get("id") == "reflex_molecular"), None)
    if rx:
        cost = rx.get("cost") or {}
        money = (f" About €{int(cost['eur_setup']):,} to set up and €{int(cost['eur_per_year']):,} per new patient a year (planning assumption)."
                 if cost.get("eur_setup") and cost.get("eur_per_year") else "")
        drug_next = ("The 50-chart audit records whether each patient had a biomarker test and where drug treatment was given. "
                     "If tests are late or missing, the next action is ready: pathology orders the biomarker panel (EGFR, ALK, PD-L1) for every new "
                     f"lung cancer the day it is diagnosed. Owner: {(rx.get('owner_en') or 'chief pathologist').lower()}.{money} "
                     "It is outside the costed plan because the model counts only surgery and radiotherapy that aim to cure.")
    return {"area_en": name, "area_fi": cp.get("area_fi"), "period": cp.get("period"), "steps": steps,
            "drug_finding": {"drug": stage_fig("drug_therapy", "Drug therapy on record"),
                             "life_prolonging": stage_fig("life_prolonging", "Life-prolonging treatment on record"),
                             "next_en": drug_next},
            "distance_en": (cp.get("expected") or {}).get("distance_en"),
            "stage_bound_en": stage_bound}


def _fx(obj: dict, reason: str | None = None) -> dict:
    out = {**obj, "fixture": True}
    if reason:
        out["fixture_reason"] = reason
    return out


_model_lock = threading.RLock()


def _real(fn_name: str, *args, **kwargs):
    """Call kello_model.api.<fn>; return (result, error)."""
    api = kello_api()
    if api is None or not hasattr(api, fn_name):
        return None, "kello_model not available"
    try:
        # One call into the model at a time: it fills its own tables on first use, and a second thread arriving
        # in the middle (a visitor in the first seconds after start) got a half-built table and a false "not found".
        with _model_lock:
            res = getattr(api, fn_name)(*args, **kwargs)
        if isinstance(res, dict):
            return res, None
        return None, f"kello_model.api.{fn_name} returned {type(res).__name__}"
    except KeyError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("kello_model.api.%s failed", fn_name)
        return None, f"kello_model.api.{fn_name} failed: {e}"


def areas_list() -> list[dict]:
    return memo("areas_list", lambda: _read(DATA / "processed/areas.json") or [])


_CC = {"FI": "Finland", "SE": "Sweden", "DK": "Denmark", "NO": "Norway"}


def _enrich_overview(o: dict) -> dict:
    """Attach published context the model leaves out: benchmark URLs and NORDCAN five-year survival.

    Only real files are used (data/evidence/parameters.json, data/processed/nordic_benchmarks.json);
    nothing is invented here.
    """
    nat = o.get("national")
    if not isinstance(nat, dict):
        return o
    nat = dict(nat)
    params = _read(DATA / "evidence/parameters.json") or {}
    bench = params.get("nordic_benchmarks_total_days") if isinstance(params, dict) else None
    if isinstance(bench, dict):
        by_name = {v: k for k, v in _CC.items()}
        out = []
        for b in nat.get("benchmarks") or []:
            rec = bench.get(by_name.get(b.get("country"), ""))
            if isinstance(rec, dict) and rec.get("value") == b.get("days"):
                b = {**b, "url": b.get("url") or rec.get("url"), "quote": rec.get("quote"), "verified": rec.get("verified"), "year": rec.get("year")}
            out.append(b)
        nat["benchmarks"] = out
        nat["benchmark_definition"] = bench.get("definition")
    if not any(r.get("country") != "Finland" for r in nat.get("survival") or []):
        # The comparison needs neighbours measured the same way: use the NORDCAN series for all countries.
        nb = _read(DATA / "processed/nordic_benchmarks.json") or {}
        rows = [r for r in nb.get("survival_5y", []) if r.get("cancer") == "lung" and r.get("country") in _CC]
        if rows:
            period = max(r["period"] for r in rows)
            src = (_read(DATA / "processed/sources.json") or {}).get("nordcan_survival", {})
            if nat.get("survival"):
                nat["survival_model"] = nat["survival"]
            nat["survival"] = [{"country": _CC[r["country"]], "sex": {"male": "men", "female": "women"}.get(r["sex"], r["sex"]),
                                "value": r["value"], "lo": r.get("lo"), "hi": r.get("hi"), "period": r["period"],
                                "source_id": r.get("source_id"), "kind": "measured"} for r in rows if r["period"] == period]
            nat["survival_source"] = {"title": src.get("title") or nb.get("publisher"), "url": src.get("url"), "retrieved_at": src.get("retrieved_at")}
    out = _fill_measured_overview({**o, "national": nat})
    # Keep the pathway contract available on the national endpoint too.  The county
    # rows are deliberately a short summary; detailed figures live on each area.
    try:
        cp = (out.get("national") or {}).get("care_path")
        if isinstance(cp, dict):
            pway = _pathway_for("FI", cp)
            out["national"]["pathway"] = pway
            out["pathway"] = {"steps": [{"id": s["id"], "label_en": s["label_en"],
                                           "verdict_en": s["verdict_en"], "what_not_published_en": s["what_not_published_en"],
                                           "figures": s["figures"]} for s in pway["steps"]],
                              "note_en": "Treatment initiation is the clearest national signal in the public data (27.0% treated to cure); county-level detection, referral and biomarker turnaround are not published.",
                              "what_finland_does_not_publish": [s["what_not_published_en"] for s in pway["steps"]]}
    except Exception as e:  # noqa: BLE001
        log.warning("pathway (overview) failed: %s", e)
    # A national, deterministic answer to the same reality checks shown on every county page.
    try:
        cp = (out.get("national") or {}).get("care_path")
        if isinstance(cp, dict):
            gc = _gap_checks("FI", cp)
            out["national"]["gap_checks"] = gc["checks"]
            out["national"]["gap_checks_overall_en"] = gc["overall_en"]
            out["national"]["gap_checks_overall_fi"] = gc["overall_fi"]
            out["gap_checks"] = gc["checks"]
            out["gap_checks_overall_en"] = gc["overall_en"]
            out["national_lead"] = {
                "patients_short_per_year": round(float((cp.get("missing_patients") or {}).get("per_year") or 0), 1),
                "patients_short_in_seven_counties": round(float((cp.get("missing_patients") or {}).get("per_year_in_counties_below_limits") or 0), 1),
                "counties": 7,
                "plan_budget_eur": 5_000_000,
                "plan_extra_curative_patients_per_year": 32.1,
                "plan_gap_closed_pct": 49,
                "plan_spent_eur": 1_426_060,
                "note_en": "Arithmetic from measured county shares; the national plan is modelled at €5M and spends only where the optimiser finds value.",
            }
    except Exception as e:  # noqa: BLE001
        log.warning("gap checks (overview) failed: %s", e)
    return out


def _fill_measured_overview(o: dict) -> dict:
    """v2 contract fields the model may not return yet: filled from the registry rows Gemini read (measured only)."""
    try:
        nat = o["national"]
        filled = False
        if not nat.get("dx_to_surgery_by_area"):
            by_area = measured_mod.surgery_days_by_area()
            if by_area:
                nat["dx_to_surgery_by_area"] = by_area
        if not nat.get("headline_measured"):
            hm = measured_mod.headline()
            if hm:
                nat["headline_measured"] = hm
                filled = True
        areas = []
        for a in o.get("areas") or []:
            if not isinstance(a.get("measured"), dict):
                m = measured_mod.area_measured(a["id"])
                if any(m.values()):
                    a = {**a, "measured": m}
                    filled = True
                    if a.get("curative_gap_patients_per_year") is None:
                        cg = measured_mod.curative_gap(a["id"])
                        if cg:
                            a["curative_gap_patients_per_year"] = cg["value"]
                            a["curative_gap_note_en"] = cg["note_en"]
            areas.append(a)
        o = {**o, "areas": areas}
        if filled:
            o["measured_filled_by"] = "app-server"
    except Exception as e:  # noqa: BLE001 - never let the fill break the overview
        log.warning("measured fill (overview) failed: %s", e)
    return o


# ---- deterministic "is the gap real?" checks --------------------------------
# These are deliberately built from the same care-path payload that the UI shows.  They
# never ask the plan writer to restate a number, so a cached plan cannot drift from the
# measured data.
def _stage(path: dict, ident: str) -> dict:
    return next((s for s in path.get("stages") or [] if s.get("id") == ident), {})


def _reader_stage(area_id: str, indicator: str) -> dict | None:
    """Return the verified chart/table read for figure 13 when it exists."""
    try:
        for row in measured_mod.data().get("rows", []):
            if str(row.get("area_id")) == str(area_id) and row.get("indicator") == indicator:
                return row
    except Exception:  # noqa: BLE001 - checks must remain available in hosted mode
        pass
    return None


def _registry_age_curative(area_id: str) -> dict | None:
    """The registry's Figure 16 age-standardised curative-treatment chart.

    The report ships this figure as a chart (not a county table), so keep the
    chart read together with its provenance.  It is used only where we have a
    read; other counties continue to use the ecological age estimate.
    """
    try:
        tables = _read(DATA / "evidence/registry_tables.json") or {}
        return (tables.get("age_standardised_curative") or {}).get(str(area_id))
    except Exception:  # noqa: BLE001
        return None


def _check_item(ident: str, q: str, qfi: str, answer: str, answer_fi: str, verdict: str, kind: str,
                source: dict | None = None) -> dict:
    source = source or {}
    return {"id": ident, "question_en": q, "question_fi": qfi, "answer_en": answer, "answer_fi": answer_fi,
            "verdict": verdict, "kind": kind, "source_url": source.get("source_url"), "page": source.get("page"),
            "quote": source.get("quote"), "read_by": source.get("read_by"), "period": source.get("period")}


def _fi_num(value, digits: int = 1) -> str:
    """Render the one-decimal values used in checks with Finnish decimal commas."""
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


def _fi_place(fi_full: str) -> tuple[str, str]:
    """('Lapin hyvinvointialueella', 'Lapin hyvinvointialueen') from 'Lapin hyvinvointialue'."""
    if fi_full.endswith("hyvinvointialue"):
        return fi_full + "ella", fi_full + "en"
    if fi_full.endswith("kaupunki"):
        stem = fi_full[: -len("kaupunki")]
        return stem + "kaupungissa", stem + "kaupungin"
    return fi_full, fi_full


def records_estimate(patients_per_year: float, no_record_pct: float) -> tuple[float, float, float]:
    """Patients a year with no treatment on record, and how many of them can be hidden cured patients: a realistic
    reading and the very most. Nationally 79% of patients with no record die within a year, 12% of those treated to cure."""
    unrecorded = patients_per_year * no_record_pct / 100
    extreme = math.floor(unrecorded * (1.0 - 0.79) / (1.0 - 0.12) * 10) / 10
    plausible = math.floor(unrecorded * (0.85 - 0.79) / (0.85 - 0.12) * 10) / 10
    return unrecorded, plausible, extreme


def _gap_checks(area_id: str, path: dict, mvi: dict | None = None) -> dict:
    """Five plain-word checks of whether a county's shortfall is real. Never claims more than its data."""
    cur = _stage(path, "curative")
    expected = path.get("expected") or {}
    staged = _stage(path, "staged")
    no_record = _stage(path, "no_record")
    alive = _stage(path, "alive_1y")
    name = path.get("area_en") or area_id
    fi_full = path.get("area_fi") or name
    fi_in, fi_gen = _fi_place(fi_full)
    is_fi = area_id == "FI"
    val, nat = cur.get("value"), cur.get("national")
    below = val is not None and nat is not None and float(val) < float(nat)
    checks: list[dict] = []
    if not is_fi and (val is None or nat is None):
        return {"checks": [], "overall_en": f"{name} has too few patients for the registry to publish its figures, so there is nothing to compare.",
                "overall_fi": f"{fi_in} on niin vähän potilaita, ettei syöpärekisteri julkaise alueen lukuja, joten vertailtavaa ei ole."}

    def add(ident, q, qfi, short, short_fi, ans, ans_fi, verdict, kind, source):
        item = _check_item(ident, q, qfi, ans, ans_fi, verdict, kind, source)
        item["short_answer_en"], item["short_answer_fi"] = short, short_fi
        checks.append(item)

    # 1. Chance.
    outside = cur.get("outside_limits")
    q, qfi = "Could it be chance?", "Voiko ero olla sattumaa?"
    if is_fi:
        below_n = int((path.get("missing_patients") or {}).get("counties_below_limits") or 0)
        add("chance", q, qfi, f"No: {below_n} of 22 counties are too far below.", f"Ei: {below_n} aluetta 22:sta on liian kaukana.",
            f"{below_n} of 22 counties are further below Finland's {val}% than chance explains.",
            f"{below_n} alueella 22:sta osuus on kauempana koko maan {_fi_num(val)} %:sta kuin sattuma selittää.",
            "holds" if below_n else "cannot_tell", "measured", cur)
    elif outside in ("95", "99.8") and cur.get("side") == "below":
        odds, odds_fi = ("less than once in 500", "harvemmin kuin kerran 500:sta") if outside == "99.8" else ("less than once in 20", "harvemmin kuin kerran 20:stä")
        add("chance", q, qfi, f"No: {odds}.", f"Ei: {odds_fi}.",
            f"{name} is at {val}% against Finland's {nat}%. A county with this many patients would land this low by chance {odds}.",
            f"{fi_in} osuus on {_fi_num(val)} %, koko maassa {_fi_num(nat)} %. Tämän kokoinen alue päätyisi näin alas sattumalta {odds_fi}.",
            "holds", "measured", cur)
    elif not below:
        add("chance", q, qfi, "No shortfall here.", "Vajetta ei ole.",
            f"{name} is at {val}% against Finland's {nat}%, so there is no shortfall to explain.",
            f"{fi_in} osuus on {_fi_num(val)} %, koko maassa {_fi_num(nat)} %, joten selitettävää vajetta ei ole.",
            "weakens", "measured", cur)
    else:
        add("chance", q, qfi, "Yes, it could.", "Kyllä, voi olla.",
            f"{name} is at {val}% against Finland's {nat}%. For a county this size that difference is within what chance alone gives.",
            f"{fi_in} osuus on {_fi_num(val)} %, koko maassa {_fi_num(nat)} %. Tämän kokoisella alueella ero mahtuu sattuman rajoihin.",
            "weakens", "measured", cur)

    # 2. Age. The registry's own age-adjusted figure where we hold it; otherwise our county-level estimate.
    q, qfi = "Is it because patients there are older?", "Johtuuko se potilaiden iästä?"
    if not is_fi and expected.get("observed_pct") is not None:
        lo, hi = expected.get("lo"), expected.get("hi")
        exp_pct, obs_pct = expected.get("expected_pct"), expected.get("observed_pct")
        age_chart = _registry_age_curative(area_id)
        if age_chart:
            men, women, natl = age_chart["men"], age_chart["women"], age_chart["national"]
            men_clear, women_clear = men["hi"] < natl["men"], women["hi"] < natl["women"]
            if men_clear and women_clear:
                tail, tail_fi = "For both, the whole range is below Finland.", "Molemmilla koko vaihteluväli on koko maan luvun alapuolella."
            elif men_clear:
                tail, tail_fi = "For men the whole range is below Finland; for women the difference could be chance.", "Miehillä koko vaihteluväli on koko maan luvun alapuolella; naisilla ero voi olla sattumaa."
            elif women_clear:
                tail, tail_fi = "For women the whole range is below Finland; for men the difference could be chance.", "Naisilla koko vaihteluväli on koko maan luvun alapuolella; miehillä ero voi olla sattumaa."
            else:
                tail, tail_fi = "Both ranges reach Finland's figure, so age may explain it.", "Molemmat vaihteluvälit yltävät koko maan lukuun, joten ikä voi selittää eron."
            verdict = "holds" if (men_clear or women_clear) else "cannot_tell"
            add("age", q, qfi, "No: still lower after age adjustment." if verdict == "holds" else "Cannot tell.",
                "Ei: osuus on pienempi myös ikävakioituna." if verdict == "holds" else "Ei voi sanoa.",
                f"The registry's own age-adjusted share is {men['value']}% for men ({men['lo']}–{men['hi']}) and {women['value']}% for women ({women['lo']}–{women['hi']}), "
                f"against {natl['men']}% and {natl['women']}% in Finland. {tail}",
                f"Rekisterin oma ikävakioitu osuus on miehillä {_fi_num(men['value'])} % ({_fi_num(men['lo'])}–{_fi_num(men['hi'])}) ja naisilla {_fi_num(women['value'])} % "
                f"({_fi_num(women['lo'])}–{_fi_num(women['hi'])}), koko maassa {_fi_num(natl['men'])} % ja {_fi_num(natl['women'])} %. {tail_fi}",
                verdict, "measured", age_chart)
        else:
            if hi is not None and hi < 1:
                verdict, short, short_fi = "holds", "No: lower than its age structure predicts.", "Ei: osuus on pienempi kuin ikärakenne ennustaa."
                tail, tail_fi = "The whole range is below what age predicts.", "Koko vaihteluväli jää ikärakenteen ennusteen alle."
            elif lo is not None and lo >= 1 or (obs_pct is not None and exp_pct is not None and obs_pct >= exp_pct):
                verdict, short, short_fi = "weakens", "Age explains it.", "Ikä selittää sen."
                tail, tail_fi = "The county is at or above what its age structure predicts.", "Alue on ikärakenteen ennusteen tasolla tai sen yläpuolella."
            else:
                verdict, short, short_fi = "cannot_tell", "Cannot tell: age may explain part.", "Ei voi sanoa: ikä voi selittää osan."
                tail, tail_fi = "The range reaches what age predicts, so age may explain part of it.", "Vaihteluväli yltää ikärakenteen ennusteeseen, joten ikä voi selittää osan."
            add("age", q, qfi, short, short_fi,
                f"A county with {name}'s share of residents over 65 would be expected at {exp_pct}%; it is at {obs_pct}%. {tail} This compares counties, not patients.",
                f"Alueelta, jossa on yhtä paljon yli 65-vuotiaita, odottaisi {_fi_num(exp_pct)} %:n osuutta; toteutunut on {_fi_num(obs_pct)} %. {tail_fi} Vertailu on tehty alueiden, ei potilaiden tasolla.",
                verdict, "estimated", cur)
    else:
        add("age", q, qfi, "Not applicable.", "Ei koske koko maata.", "This is a comparison between counties; it does not apply to the national figure.",
            "Vertailu tehdään alueiden välillä, joten se ei koske koko maan lukua.", "cannot_tell", "estimated", cur)

    # 3. Stage. Not published by county: stays open, and says what would settle it.
    q, qfi = "Are cancers found later there?", "Löydetäänkö syövät siellä myöhemmin?"
    known, nat_known = staged.get("value"), staged.get("national")
    extra = (f" What is published: stage was recorded for {known}% of patients here, {nat_known}% in Finland." if known is not None and nat_known is not None else "")
    extra_fi = (f" Julkaistu tieto: levinneisyys on kirjattu {_fi_num(known)} %:lle potilaista, koko maassa {_fi_num(nat_known)} %:lle." if known is not None and nat_known is not None else "")
    add("stage", q, qfi, "Cannot tell: not published by county.", "Ei voi sanoa: tietoa ei julkaista alueittain.",
        "The registry does not publish how advanced cancers are at diagnosis by county, so this is the one check public data cannot make." + extra
        + " The audit of 50 charts in step zero records each patient's stage and answers it.",
        "Rekisteri ei julkaise alueittain, kuinka levinneitä syövät ovat toteamishetkellä, joten tätä ei voi tarkistaa julkisesta tiedosta." + extra_fi
        + " Vaiheen nolla 50 potilaskertomuksen tarkistus kirjaa jokaisen potilaan levinneisyyden ja vastaa tähän.",
        "cannot_tell", "measured", staged or cur)

    # 4. Records. Treatments come from hospital records; deaths among patients with no record bound the hidden share.
    q, qfi = "Is it just missing records?", "Onko kyse vain puuttuvista kirjauksista?"
    short_n = (path.get("missing_patients") or {}).get("per_year") or 0
    if no_record.get("value") is not None and path.get("patients_per_year") and short_n > 0 and below:
        unrecorded, plausible, extreme = records_estimate(path["patients_per_year"], no_record["value"])
        left = max(short_n - plausible, 0)
        left_ext = max(short_n - extreme, 0)
        verdict = "mostly_holds" if left >= 0.5 * short_n else "cannot_tell"
        add("records", q, qfi,
            f"Mostly not: about {left:.0f} of {short_n:.0f} remain." if verdict == "mostly_holds" else "Cannot tell: it could be most of it.",
            f"Enimmäkseen ei: noin {left:.0f} potilasta {short_n:.0f}:stä jää." if verdict == "mostly_holds" else "Ei voi sanoa: kirjaukset voivat selittää suuren osan.",
            f"Operations and radiotherapy are counted from the records hospitals file for every visit, not from voluntary reports. About {unrecorded:.0f} patients a year here have no treatment on record. "
            f"Across Finland 79% of such patients die within a year, against 12% of patients treated to cure, so few of them can be hidden cured patients: "
            f"about {plausible:.0f} a year on a realistic reading, which leaves about {left:.0f} of the {short_n:.0f} missing; {extreme:.0f} at the very most, which leaves {left_ext:.0f}. "
            "National death rates applied to this county. Drug treatment given outside hospital wards is under-recorded and is not part of this count.",
            f"Leikkaukset ja sädehoidot lasketaan hoitoilmoituksista, jotka sairaalat tekevät jokaisesta käynnistä, eikä vapaaehtoisista ilmoituksista. Noin {unrecorded:.0f} potilaalla vuodessa ei ole hoitokirjausta. "
            f"Koko maassa tällaisista potilaista 79 % kuolee vuoden kuluessa, parantavaa hoitoa saaneista 12 %, joten heidän joukossaan voi olla vain vähän parantavasti hoidettuja: "
            f"realistisesti noin {plausible:.0f} vuodessa, jolloin vajeesta jää noin {left:.0f} potilasta {short_n:.0f}:stä; enintään {extreme:.0f}, jolloin jää {left_ext:.0f}. "
            "Koko maan kuolleisuusluvut on sovellettu tähän alueeseen. Avohoidossa annettu lääkehoito kirjautuu puutteellisesti eikä kuulu tähän laskelmaan.",
            verdict, "estimated", None)
    elif not below and val is not None and nat is not None:
        add("records", q, qfi, "No shortfall here.", "Vajetta ei ole.", f"{name} has no shortfall against Finland, so there is nothing for missing records to explain.",
            f"{fi_in} ei ole vajetta koko maahan verrattuna, joten puuttuvat kirjaukset eivät selitä mitään.", "weakens", "estimated", None)
    else:
        add("records", q, qfi, "Cannot tell.", "Ei voi sanoa.", "The share of patients with no treatment on record is not published for this county.",
            "Hoitokirjausta vailla olevien potilaiden osuutta ei ole julkaistu tälle alueelle.", "cannot_tell", "estimated", None)
    record_source = dict(no_record or cur)
    record_source.update(page="Taulukko 12 / Kuva 17", quote=("Potilaista, joille ei löytynyt hoitokirjauksia lainkaan, 79 % kuoli vuoden seurannan aikana. "
                                                                "Parantavaan hoitoon ohjatuista potilaista 12 % kuoli vuoden seurannan aikana. "
                                                                "Oireenmukaiseen hoitoon ensivaiheessa ohjautuneista 85 % kuoli vuoden seurannassa."),
                         period="2019-2023; 12-month follow-up")
    for k in ("source_url", "page", "quote", "read_by", "period"):
        checks[-1][k] = record_source.get(k)

    # 5. Outcome. Deaths against new cases, and one-year survival. Supports, never proves.
    q, qfi = "Do deaths and survival point the same way?", "Kertovatko kuolleisuus ja elossaolo samaa?"
    mvi = mvi or {}
    if mvi:
        mr, ir = float(mvi.get("mortality_ratio", 1)), float(mvi.get("incidence_ratio", 1))
        pct = lambda r: f"{abs(round(100 * (r - 1)))}% {'more' if r >= 1 else 'fewer'}"
        pct_fi = lambda r: f"{abs(round(100 * (r - 1)))} % {'enemmän' if r >= 1 else 'vähemmän'}"
        a_v, a_n = alive.get("value"), alive.get("national")
        surv = f" One-year survival is {a_v}% against {a_n}% in Finland." if a_v is not None and a_n is not None else ""
        surv_fi = f" Vuoden kuluttua elossa on {_fi_num(a_v)} %, koko maassa {_fi_num(a_n)} %." if a_v is not None and a_n is not None else ""
        worse = mr > ir and (a_v is None or a_n is None or a_v <= a_n)
        better = mr < ir and (a_v is None or a_n is None or a_v >= a_n)
        if below and worse:
            verdict, short, short_fi = "mostly_holds", "Yes, slightly: more deaths per case.", "Kyllä, lievästi: enemmän kuolemia tapausta kohden."
            tail, tail_fi = "That fits fewer patients being cured. It does not prove it.", "Se sopii siihen, että harvempi paranee, mutta ei todista sitä."
        elif below and better:
            verdict, short, short_fi = "weakens", "No: outcomes are not worse.", "Ei: tulokset eivät ole huonompia."
            tail, tail_fi = "Outcomes are not worse than the number of new cases predicts.", "Tulokset eivät ole huonompia kuin uusien tapausten määrä ennustaa."
        elif below:
            verdict, short, short_fi = "cannot_tell", "Cannot tell: the two measures disagree.", "Ei voi sanoa: mittarit osoittavat eri suuntiin."
            tail, tail_fi = "The two measures do not point the same way.", "Mittarit eivät osoita samaan suuntaan."
        else:
            verdict, short, short_fi = "weakens", "No shortfall here.", "Vajetta ei ole."
            tail, tail_fi = "There is no shortfall here to confirm.", "Vahvistettavaa vajetta ei ole."
        add("outcome", q, qfi, short, short_fi,
            f"{name} has {pct(mr)} lung cancer deaths per resident than Finland and {pct(ir)} new cases.{surv} {tail}",
            f"{fi_in} on {pct_fi(mr)} keuhkosyöpäkuolemia asukasta kohden kuin koko maassa ja {pct_fi(ir)} uusia tapauksia.{surv_fi} {tail_fi}",
            verdict, "measured", {"source_url": mvi.get("source_url"), "page": "mort_latest5", "quote": mvi.get("sentence_en"), "period": mvi.get("period")})
    else:
        add("outcome", q, qfi, "Cannot tell.", "Ei voi sanoa.", "No county comparison of deaths and new cases is loaded.",
            "Alueen kuolleisuuden ja uusien tapausten vertailua ei ole ladattu.", "cannot_tell", "measured", cur)

    if is_fi:
        below_n = int((path.get("missing_patients") or {}).get("counties_below_limits") or 0)
        overall = f"{below_n} of 22 counties are further below Finland than chance explains. Each county page checks its own gap."
        overall_fi = f"{below_n} aluetta 22:sta on kauempana koko maan luvusta kuin sattuma selittää. Jokaisen alueen sivu tarkistaa oman eronsa."
    elif below:
        yes = sum(1 for c in checks if c["verdict"] in ("holds", "mostly_holds"))
        open_ = [c for c in checks if c["verdict"] == "cannot_tell"]
        against = [c for c in checks if c["verdict"] == "weakens"]
        words = {0: "None", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "All five"}
        words_fi = {0: "Yksikään", 1: "Yksi", 2: "Kaksi", 3: "Kolme", 4: "Neljä", 5: "Kaikki viisi"}
        clear = sum(1 for c in checks if c["verdict"] == "holds")
        mostly = sum(1 for c in checks if c["verdict"] == "mostly_holds")
        w = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        wf = {1: "yksi", 2: "kaksi", 3: "kolme", 4: "neljä", 5: "viisi"}
        if clear == len(checks):
            overall, overall_fi = "All five checks say the gap is real.", "Kaikki viisi tarkistusta tukevat sitä, että ero on todellinen."
        else:
            parts, parts_fi = [], []
            if clear:
                parts.append(f"{w[clear]} check{'s' if clear > 1 else ''} say{'' if clear > 1 else 's'} clearly yes")
                parts_fi.append(f"{wf[clear]} tarkistus{'ta' if clear > 1 else ''} sanoo selvästi kyllä")
            if mostly:
                parts.append(f"{w[mostly]} mostly yes")
                parts_fi.append(f"{wf[mostly]} enimmäkseen kyllä")
            if against:
                parts.append(f"{w[len(against)]} no")
                parts_fi.append(f"{wf[len(against)]} ei")
            if open_:
                parts.append(f"{w[len(open_)]} cannot be answered from public data")
                parts_fi.append(f"{'yhteen' if len(open_) == 1 else wf[len(open_)] + ' kohtaan'} ei voi vastata julkisesta tiedosta")
            def _join(xs, last):
                return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + f" {last} " + xs[-1]
            overall = _join(parts, "and") + "."
            overall = overall[0].upper() + overall[1:]
            overall_fi = _join(parts_fi, "ja") + "."
            overall_fi = overall_fi[0].upper() + overall_fi[1:]
        if open_ and any(c["id"] == "stage" for c in open_):
            if len(open_) == 1:
                overall += " That one is stage at diagnosis; the 50-chart audit (8 weeks, €8,000) settles it."
                overall_fi += " Se on levinneisyys diagnoosihetkellä; 50 potilaskertomuksen tarkistus (8 viikkoa, 8 000 €) ratkaisee sen."
            else:
                overall += " Stage at diagnosis is one of them; the 50-chart audit (8 weeks, €8,000) settles it."
                overall_fi += " Levinneisyys diagnoosihetkellä on yksi niistä; 50 potilaskertomuksen tarkistus (8 viikkoa, 8 000 €) ratkaisee sen."
    elif val is None or nat is None:
        overall = f"{name} has too few patients for the registry to publish its figures, so there is nothing to compare."
        overall_fi = f"{fi_in} on niin vähän potilaita, ettei syöpärekisteri julkaise alueen lukuja, joten vertailtavaa ei ole."
    else:
        overall = f"{name} has no shortfall against Finland, so there is no gap to check."
        overall_fi = f"{fi_in} ei ole vajetta koko maahan verrattuna, joten tarkistettavaa eroa ei ole."
    return {"checks": checks, "overall_en": overall, "overall_fi": overall_fi}


def _attach_gap_checks(obj: dict, area_id: str, *, mvi: dict | None = None) -> dict:
    cp = obj.get("care_path") if isinstance(obj, dict) else None
    if isinstance(cp, dict):
        gc = _gap_checks(area_id, cp, mvi)
        obj["gap_checks"] = gc["checks"]
        obj["gap_checks_overall_en"] = gc["overall_en"]
        obj["gap_checks_overall_fi"] = gc["overall_fi"]
    return obj


def overview() -> dict:
    return memo("overview", _overview)


def _overview() -> dict:
    res, err = _real("overview")
    if res:
        return _enrich_overview(res)
    pre = _read(DATA / "model/pathways.json")
    if isinstance(pre, dict) and isinstance(pre.get("overview"), dict):
        return _enrich_overview(pre["overview"])
    return _fx(fixture_model.load("overview.json"), err)


_GAP_ID = re.compile(r"^([a-z][a-z0-9_]+) (for this county.*)$")


def _enrich_area(a: dict) -> dict:
    """Replace bare indicator ids in the model's data-gap list with their catalogue labels."""
    cat = _read(DATA / "processed/indicators_catalog.json")
    if not isinstance(cat, dict):
        return a
    for g in a.get("data_gaps") or []:
        m = _GAP_ID.match(str(g.get("what_en", "")))
        label = (cat.get(m.group(1)) or {}).get("label_en") if m else None
        if m and not label:  # not in the catalogue: at least make the id readable
            words = m.group(1).replace("_pct", " (%)").replace("_", " ")
            label = re.sub(r"\b(gp|ct|pet|mdt)\b", lambda x: x.group(1).upper(), words)
            label = label[0].upper() + label[1:]
        if label:
            g["indicator"] = m.group(1)
            g["what_en"] = f"{label}, {m.group(2)}"
    return _drop_published_gaps(a)


def _drop_published_gaps(a: dict) -> dict:
    """"What Finland does not measure" must not list what the registry publishes by county (curative share, stage recording)."""
    gaps = a.get("data_gaps")
    if not isinstance(gaps, list):
        return a
    try:
        have_curative = bool(measured_mod.data()["table"].get("curative_intent_pct"))
        have_stage = any(r.get("indicator") in ("lung_stage_unknown_pct", "lung_stage_tnm_pct") and not str(r.get("area_id", "")).startswith(("yta:", "FI"))
                         for r in measured_mod.data()["rows"])
    except Exception:  # noqa: BLE001
        return a
    out = []
    for g in gaps:
        what = str(g.get("what_en", "")).lower()
        if have_curative and "curative" in what:
            if have_stage or "stage" not in what:
                continue
            g = {**g, "what_en": "Stage at diagnosis, by county"}
        elif have_stage and g.get("indicator") == "lung_stage_known_pct":
            continue
        out.append(g)
    # Diagnostics is a deliberate second gap: no loaded source publishes
    # county-level biomarker testing or pathology-to-result time.
    if not any("biomarker" in str(g.get("what_en", "")).lower() or "molecular" in str(g.get("what_en", "")).lower()
               for g in out):
        out.append({"what_en": "Biomarker / molecular testing and pathology-to-result time, by county",
                    "why_it_matters_en": "Finland does not publish whether guideline-relevant testing was completed or how long the result took; count the pathology request, result and treatment-decision dates before scaling a reflex-testing pathway.",
                    "who_could_publish_en": "Wellbeing services counties and THL (Hilmo plus pathology systems)"})
    return {**a, "data_gaps": out}


def _fill_measured_area(a: dict, area_id: str) -> dict:
    try:
        if "measured_gaps" not in a and area_id != "FI":
            gaps = measured_mod.area_gaps(area_id)
            if gaps:
                a = {**a, "measured_gaps": gaps, "measured_filled_by": "app-server"}
    except Exception as e:  # noqa: BLE001
        log.warning("measured fill (area %s) failed: %s", area_id, e)
    return a


def area(area_id: str) -> dict:
    return memo(("area", area_id), lambda: _area(area_id))


def _area(area_id: str) -> dict:
    res, err = _real("area", area_id)
    if res:
        out = _attach_gap_checks(_fill_measured_area(_enrich_area(res), area_id), area_id,
                                 mvi=res.get("mortality_vs_incidence"))
        out["pathway"] = _pathway_for(area_id, out.get("care_path"))
        return out
    pre = _read(DATA / "model/pathways.json")
    if isinstance(pre, dict):
        cand = (pre.get("areas") or {}).get(area_id) if isinstance(pre.get("areas"), dict) else pre.get(area_id)
        if isinstance(cand, dict) and "steps" in cand:
            out = _attach_gap_checks(_enrich_area(cand), area_id)
            out["pathway"] = _pathway_for(area_id, out.get("care_path"))
            return out
    fx = fixture_model.load("areas.json")
    if area_id not in fx:
        raise KeyError(area_id)
    out = _fx(fx[area_id], err)
    out["pathway"] = _pathway_for(area_id, out.get("care_path"))
    return out


def interventions() -> tuple[list[dict], bool]:
    """(interventions, is_fixture). The fixture list is used whenever the sample engine is in play."""
    return memo("interventions", _interventions)


def _interventions() -> tuple[list[dict], bool]:
    real = _read(DATA / "evidence/interventions.json")
    if isinstance(real, dict):
        real = real.get("interventions") or list(real.values())
    if isinstance(real, list) and real and kello_api() is not None:
        return real, False
    return fixture_model.interventions(), True


def simulate(area_id: str, ids: list[str], seed=None) -> dict:
    return memo(("simulate", area_id, tuple(ids), seed), lambda: _simulate(area_id, ids, seed))


def _simulate(area_id: str, ids: list[str], seed=None) -> dict:
    res, err = _real("simulate", area_id, ids, seed=seed)
    if res:
        return _plain(res)
    return _fx(fixture_model.simulate(area_id, ids, seed), err)


def optimize(scope: str, budget_eur: float, objective: str | None = None, exclude: list[str] | None = None) -> dict:
    ex = tuple(sorted(set(exclude or [])))
    return memo(("optimize", scope, float(budget_eur), objective, ex), lambda: _optimize(scope, budget_eur, objective, list(ex)))


def _optimize(scope: str, budget_eur: float, objective: str | None, exclude: list[str]) -> dict:
    api = kello_api()
    kwargs: dict = {}
    dropped: list[str] = []
    try:
        params = inspect.signature(api.optimize).parameters if api is not None else {}
    except (TypeError, ValueError):
        params = {}
    for name, val in (("objective", objective), ("exclude", exclude or None)):
        if val is None:
            continue
        if name in params:
            kwargs[name] = val
        else:
            dropped.append(name)
    res, err = _real("optimize", scope, budget_eur, **kwargs)
    if res is None and "objective" in kwargs:
        # an objective this model version does not know: answer with its default rather than with sample data
        kwargs.pop("objective")
        dropped.append("objective")
        res, err = _real("optimize", scope, budget_eur, **kwargs)
    if res:
        res = _plain(res)
        if dropped:
            res["ignored_params"] = dropped
        return _shape_for_ui(res, scope, float(budget_eur))
    pre = _read(DATA / "model/plans.json")
    if isinstance(pre, dict) and isinstance(pre.get(scope), dict):
        by_budget = pre[scope]
        try:
            key = min(by_budget, key=lambda k: abs(float(k) - budget_eur))
            if isinstance(by_budget[key], dict) and "chosen" in by_budget[key]:
                return _shape_for_ui({**by_budget[key], "precomputed_budget_eur": float(key)}, scope, float(budget_eur))
        except (TypeError, ValueError):
            pass
    return _shape_for_ui(_fx(fixture_model.optimize(scope, budget_eur), err), scope, float(budget_eur))


_SHOWN_NOTE = ("Rows are shown to one decimal and rounded so that they add up to the total shown: where plain rounding would leave "
               "the rows 0.1 above or below the total, the row with the largest rounding remainder takes the difference.")
_METRICS = (("extra_curative_patients_per_year", "extra"), ("deaths_avoided_per_year", "deaths"))
_GROUPS = (("county", "The county can start on Monday", "Hyvinvointialue voi aloittaa maanantaina"),
           ("collaborative_area", "Needs the collaborative area (university hospital)", "Vaatii yhteistyöalueen (yliopistosairaalan)"))


def _tenths(x) -> int:
    return int((Decimal(str(x or 0)) * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _med(c: dict, key: str) -> float:
    v = c.get(key)
    return float(v.get("median") or 0) if isinstance(v, dict) else float(v or 0)


def eur_en(n) -> str:
    n = float(n or 0)
    if n >= 1e6:
        places = 1 if n >= 10e6 else 2
        return f"€{n / 1e6:.{places}f}M".rstrip("0").rstrip(".")
    return f"€{n:,.0f}"


def eur_fi(n) -> str:
    n = float(n or 0)
    if n >= 1e6:
        places = 1 if n >= 10e6 else 2
        return f"{n / 1e6:.{places}f}".rstrip("0").rstrip(".").replace(".", ",") + " milj. €"
    return f"{n:,.0f}".replace(",", " ") + " €"


def num_fi(x, d: int = 1) -> str:
    return f"{float(x):.{d}f}".replace(".", ",").replace("-", "−")


def _listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(f"({i}) {t}" for i, t in enumerate(items, 1))


def _study_line(iv: dict) -> str | None:
    ev = next((e for e in iv.get("evidence") or [] if isinstance(e, dict) and e.get("url")), None)
    if not ev:
        return None
    claim = str(ev.get("claim") or "").strip()
    # The travel paper reports three exposure contrasts.  The first (0.88) is
    # not significant (95% CI 0.70–1.11); keep that distinction visible on the
    # card instead of presenting the three odds ratios as one effect.
    if iv.get("id") == "travel_accommodation_support":
        claim = "England: each longer travel-time contrast had lower surgery odds; the first was 0.88 (95% CI 0.70–1.11), not significant"
    year = ev.get("year")
    # The evidence file's claim is the opened study's short, numeric result. Keep it
    # verbatim enough that the card and plan can be audited with one click.
    return f"Evidence: {claim}{f' ({year})' if year else ''} · {ev.get('url')}"


def _why_here(area_id: str, row: dict, path: dict | None) -> str | None:
    """One plain sentence: why this county needs this action, with the county's own number."""
    if not path:
        return None
    name = path.get("area_en") or area_id
    stages = {s.get("id"): s for s in path.get("stages") or []}
    ident = row.get("intervention_id")
    exp = path.get("expected") or {}
    km = exp.get("km_to_university_hospital")
    km_txt = f"{round(float(km))} km" if km else None
    by_mod = {m.get("id"): m.get("per_year") for m in ((path.get("missing_patients") or {}).get("by_modality") or [])}

    def pair(stage_id):
        s = stages.get(stage_id) or {}
        v, n = s.get("value"), s.get("national")
        return (v, n) if v is not None and n is not None else (None, None)

    if area_id == "FI":
        below_n = int((path.get("missing_patients") or {}).get("counties_below_limits") or 0)
        start = f"{below_n} counties are below that by more than chance, and this starts there" if below_n else "this starts in the counties below that"
        if ident == "recording_audit":
            v, _ = pair("no_record")
            if v is not None:
                return f"{v}% of Finland's patients have no treatment on record. Until charts are checked in the counties furthest below, nobody knows how much of the gap is care."
        if ident == "surgeon_second_opinion":
            v, _ = pair("surgery")
            if v is not None:
                return f"{v} of 100 patients are operated in Finland as a whole. The review starts in the counties that operate fewer."
        if ident == "sbrt_pathway":
            v, _ = pair("radiotherapy")
            if v is not None:
                return f"{v} of 100 patients get radiotherapy in Finland as a whole. The referral rule starts in the counties that give less."
        if ident == "reflex_molecular":
            return "Time from biopsy to biomarker result is not published by county. The counties would start by counting it."
        if ident in ("same_day_cxr_ct", "gp_direct_ct"):
            return "Time from referral to CT for suspected lung cancer is not published by county. The counties would start by counting it."
        v, _ = pair("curative")
        return f"{v} of 100 patients are treated to cure in Finland; {start}." if v is not None else None

    if ident == "recording_audit":
        v, n = pair("no_record")
        if v is not None:
            return f"{v}% of {name}'s patients have no treatment on record, {n}% in Finland. Until those charts are checked, nobody knows how much of the gap is care."
    if ident == "surgeon_second_opinion":
        v, n = pair("surgery")
        if v is not None:
            per = by_mod.get("surgery")
            tail = f" That is about {per:.0f} patients a year." if per and per >= 0.5 and v < n else ""
            return f"{v} of 100 patients are operated here, {n} in Finland.{tail}"
    if ident == "sbrt_pathway":
        v, n = pair("radiotherapy")
        if v is not None:
            return f"{v} of 100 patients get radiotherapy here, {n} in Finland. A patient who cannot be operated can still be cured this way, if someone refers them."
    if ident == "video_mdt_stage1_3":
        if km_txt:
            return f"The specialists who decide on surgery and radiotherapy are {km_txt} away. A fixed weekly slot puts every {name} patient in front of them."
    if ident == "travel_accommodation_support":
        if km_txt:
            return f"People in {name} live on average about {km_txt} from the university hospital, and curative radiotherapy means weeks of visits there."
    if ident == "prehab_fitness_assessment":
        if exp.get("observed_pct") is not None and exp.get("expected_pct") is not None and exp["observed_pct"] < exp["expected_pct"]:
            return (f"{exp['observed_pct']}% are treated to cure here; {name}'s age structure predicts {exp['expected_pct']}%. "
                    "A fitness test makes sure 'too frail' is measured, not assumed.")
    if ident == "reflex_molecular":
        return f"Time from biopsy to biomarker result is not published by county. {name} would start by counting it."
    if ident in ("same_day_cxr_ct", "gp_direct_ct"):
        return f"Time from referral to CT for suspected lung cancer is not published by county. {name} would start by counting it."
    v, n = pair("curative")
    if v is not None and float(v) >= float(n):
        return f"{name} already treats more patients to cure than Finland ({v} against {n} of 100), so this action is not about closing a gap."
    if v is not None:
        return f"{v} of 100 patients are treated to cure in {name}, {n} in Finland."
    return None


_STUDY_FI = {
    "cpp_pathway": "Tanska: oireisten, perusterveydenhuollon kautta todettujen syöpäpotilaiden kolmen vuoden suhteellinen elossaolo nousi 45 %:sta 54 %:iin, kun syöpäpotilaan hoitopolut otettiin käyttöön.",
    "same_day_cxr_ct": "Perusterveydenhuollon keuhkokuvien välitön lausunto puolitti ajan keuhkosyövän diagnoosiin.",
    "gp_direct_ct": "Tanskalainen ryvässatunnaistettu tutkimus: suora pääsy TT-kuvaukseen lyhensi diagnoosiaikaa 8 päivää (ei tilastollisesti merkitsevä) eikä muuttanut levinneisyysjakaumaa.",
    "ai_cxr_triage_alone": "Satunnaistettu tutkimus, 93 326 keuhkokuvaa: tekoälyn tekemä kiireellisyysjärjestys ei muuttanut aikaa TT-kuvaukseen eikä diagnoosiin.",
    "ebus_capacity": "Satunnaistettu tutkimus: EBUS ensimmäisenä tutkimuksena puolitti ajan hoitopäätökseen.",
    "reflex_molecular": "Leikattu EGFR-mutaatiopositiivinen keuhkosyöpä: 24 kuukauden kohdalla elossa ja taudittomana 89 % (liitännäishoitona osimertinibi) ja 52 % (lume), joten EGFR-tulos tarvitaan leikkauksen jälkeen.",
    "liquid_biopsy_first": "Verinäytteestä ensin tehty genotyypitys liittyi 23 päivää lyhyempään aikaan hoidon alkuun.",
    "nurse_navigator": "Kartoittava katsaus, 13 tutkimusta: nimetty hoitaja lyhensi odotusta diagnoosista hoitoon.",
    "ldct_screening": "Yhdeksän satunnaistetun tutkimuksen meta-analyysi: 16 % pienempi keuhkosyöpäkuolleisuus matala-annos-TT-seulonnalla.",
    "symptom_campaign": "Englannin kansallinen keuhkosyöpäkampanja: I-asteen osuus +3,1 prosenttiyksikköä.",
    "nssc_rapid_dx_centre": "Tanskalainen diagnostinen keskus: 8 %:lla epämääräisten oireiden vuoksi lähetetyistä todettiin syöpä.",
    "gp_capacity_econsult": "Vastaanottoaikaa odotetaan Suomessa 14 päivää, muissa Pohjoismaissa 2–7 päivää.",
    "video_mdt_stage1_3": "Etäkokous, jossa thoraxkirurgi osallistui aluesairaalan hoitokokoukseen videolla: leikkausten osuus nousi 30 % (suhteellinen muutos).",
    "surgeon_second_opinion": "Yksiköissä, joissa kirurgi osallistui yli kahteen kolmasosaan keuhkosyövän hoitokokouksista, leikattiin 14,4 % potilaista, muissa 12,0 %.",
    "sbrt_pathway": "Alankomaat, iäkkäät I-asteen potilaat: hoitamatta jääneiden osuus pieneni 7 prosenttiyksikköä, kun stereotaktinen sädehoito tuli saataville; leikkausten osuus ei muuttunut.",
    "prehab_fitness_assessment": "Suomessa puolet mahdollisesti leikattavissa olevista potilaista jää leikkaamatta, usein keuhkojen tai sydämen toiminnan vuoksi.",
    "travel_accommodation_support": "Englanti: mitä pidempi matka-aika, sitä pienempi leikkauksen todennäköisyys; ensimmäinen vertailu 0,88 (95 %:n luottamusväli 0,70–1,11), ei tilastollisesti merkitsevä.",
    "recording_audit": "Syöpärekisteri toteaa itse, että osa alueiden välisistä eroista johtuu kirjaamiskäytännöistä.",
    "smoking_cessation_at_diagnosis": "Tupakoinnin lopettaminen diagnoosin jälkeen: 33 % pienempi kokonaiskuolleisuus varhaisvaiheen keuhkosyövässä.",
}


def _study_line_fi(iv: dict) -> str | None:
    ev = next((e for e in iv.get("evidence") or [] if isinstance(e, dict) and e.get("url")), None)
    claim = _STUDY_FI.get(str(iv.get("id")))
    if not ev or not claim:
        return None
    year = ev.get("year")
    return f"Evidence: {claim}{f' ({year})' if year else ''} · {ev.get('url')}"


def _why_here_fi(area_id: str, row: dict, path: dict | None) -> str | None:
    """`_why_here` in Finnish: the same sentence, the same numbers."""
    if not path:
        return None
    stages = {s.get("id"): s for s in path.get("stages") or []}
    ident = row.get("intervention_id")
    exp = path.get("expected") or {}
    km = exp.get("km_to_university_hospital")
    km_txt = f"{round(float(km))} km" if km else None
    by_mod = {m.get("id"): m.get("per_year") for m in ((path.get("missing_patients") or {}).get("by_modality") or [])}

    def pair(stage_id):
        s = stages.get(stage_id) or {}
        v, n = s.get("value"), s.get("national")
        return (v, n) if v is not None and n is not None else (None, None)

    f = _fi_num
    if area_id == "FI":
        below_n = int((path.get("missing_patients") or {}).get("counties_below_limits") or 0)
        if ident == "recording_audit":
            v, _ = pair("no_record")
            if v is not None:
                return f"{f(v)} %:lla Suomen potilaista ei ole hoitokirjausta. Ennen kuin kertomukset on tarkistettu kauimpana jäljessä olevilla alueilla, kukaan ei tiedä, kuinka suuri osa erosta on hoitoa."
        if ident == "surgeon_second_opinion":
            v, _ = pair("surgery")
            if v is not None:
                return f"Koko Suomessa leikataan {f(v)} potilasta sadasta. Arvio aloitetaan alueilta, joilla leikataan vähemmän."
        if ident == "sbrt_pathway":
            v, _ = pair("radiotherapy")
            if v is not None:
                return f"Koko Suomessa sädehoitoa saa {f(v)} potilasta sadasta. Lähettämisen sääntö aloitetaan alueilta, joilla sitä annetaan vähemmän."
        if ident == "reflex_molecular":
            return "Aikaa näytteestä biomarkkeritulokseen ei julkaista alueittain. Alueet aloittaisivat laskemalla sen."
        if ident in ("same_day_cxr_ct", "gp_direct_ct"):
            return "Aikaa lähetteestä TT-kuvaukseen keuhkosyöpäepäilyssä ei julkaista alueittain. Alueet aloittaisivat laskemalla sen."
        v, _ = pair("curative")
        if v is None:
            return None
        start = f"{below_n} aluetta jää tästä enemmän kuin sattuma selittää, ja työ aloitetaan niistä" if below_n else "työ aloitetaan alueilta, jotka jäävät tästä"
        return f"Suomessa {f(v)} potilasta sadasta saa parantavaan pyrkivää hoitoa; {start}."

    if ident == "recording_audit":
        v, n = pair("no_record")
        if v is not None:
            return f"{f(v)} %:lla alueen potilaista ei ole hoitokirjausta, koko Suomessa {f(n)} %:lla. Ennen kuin nämä kertomukset on tarkistettu, kukaan ei tiedä, kuinka suuri osa erosta on hoitoa."
    if ident == "surgeon_second_opinion":
        v, n = pair("surgery")
        if v is not None:
            per = by_mod.get("surgery")
            tail = f" Se on noin {per:.0f} potilasta vuodessa." if per and per >= 0.5 and v < n else ""
            return f"Täällä leikataan {f(v)} potilasta sadasta, koko Suomessa {f(n)}.{tail}"
    if ident == "sbrt_pathway":
        v, n = pair("radiotherapy")
        if v is not None:
            return f"Täällä sädehoitoa saa {f(v)} potilasta sadasta, koko Suomessa {f(n)}. Potilas, jota ei voida leikata, voidaan silti parantaa näin, jos joku lähettää hänet."
    if ident == "video_mdt_stage1_3" and km_txt:
        return f"Leikkauksesta ja sädehoidosta päättävät erikoislääkärit ovat {km_txt}:n päässä. Kiinteä viikoittainen aika tuo jokaisen alueen potilaan heidän eteensä."
    if ident == "travel_accommodation_support" and km_txt:
        return f"Alueen asukkaat asuvat keskimäärin noin {km_txt}:n päässä yliopistosairaalasta, ja parantava sädehoito tarkoittaa viikkojen käyntejä siellä."
    if ident == "prehab_fitness_assessment":
        if exp.get("observed_pct") is not None and exp.get("expected_pct") is not None and exp["observed_pct"] < exp["expected_pct"]:
            return (f"Täällä parantavaan pyrkivää hoitoa saa {f(exp['observed_pct'])} %; alueen ikärakenne ennustaa {f(exp['expected_pct'])} %. "
                    "Rasituskoe varmistaa, että ”liian huonokuntoinen” on mitattu eikä oletettu.")
    if ident == "reflex_molecular":
        return "Aikaa näytteestä biomarkkeritulokseen ei julkaista alueittain. Alue aloittaisi laskemalla sen."
    if ident in ("same_day_cxr_ct", "gp_direct_ct"):
        return "Aikaa lähetteestä TT-kuvaukseen keuhkosyöpäepäilyssä ei julkaista alueittain. Alue aloittaisi laskemalla sen."
    v, n = pair("curative")
    if v is not None and float(v) >= float(n):
        return f"Alueella parantavaan pyrkivää hoitoa saa jo useampi kuin koko Suomessa ({f(v)} ja {f(n)} sadasta), joten tämä toimi ei koske eron kaventamista."
    if v is not None:
        return f"Alueella {f(v)} potilasta sadasta saa parantavaan pyrkivää hoitoa, koko Suomessa {f(n)}."
    return None


def _stage_iv_share() -> float:
    """Finland's measured share of lung cancers found at stage IV (no county figure is published)."""
    v = (((_read(DATA / "evidence/parameters.json") or {}).get("finland_lung_facts") or {}).get("stage_iv_share_pct") or {}).get("value")
    return float(v) / 100 if v else 0.59


def _no_spread_not_operated(patients: float, surgery_pct) -> float:
    """Of `patients`, those whose cancer has not spread to other organs and who are not operated: the decisions a chest
    surgeon would review. Uses Finland's stage IV share, because stage is not published by county."""
    return max(0.0, patients * (1 - _stage_iv_share()) - patients * float(surgery_pct or 0) / 100)


def _day90(area_id: str, row: dict, path: dict | None) -> tuple[str, str]:
    """What 'done' looks like 90 days after the first step, and what the county counts. Work done, never a promised effect."""
    ident = row.get("intervention_id")
    patients = float((path or {}).get("patients_per_year") or 0)
    surg = _stage(path or {}, "surgery").get("value")
    n90 = round(_no_spread_not_operated(patients / 4, surg)) if patients and surg is not None else None
    about = f": about {n90} in 90 days, if the county's stage mix is Finland's" if n90 else ""
    about_fi = f": noin {n90} päätöstä 90 päivässä, jos alueen levinneisyysjakauma on koko maan" if n90 else ""
    table = {
        "recording_audit": ("All 50 charts are checked, and one page says how many of these patients were treated after all.",
                            "Kaikki 50 potilaskertomusta on tarkistettu, ja yhdellä sivulla kerrotaan, kuinka moni näistä potilaista oli sittenkin hoidettu."),
        "surgeon_second_opinion": (f"Every decision not to operate on a patient whose cancer has not spread to other organs has a chest surgeon's written opinion{about}. Counted: decisions reviewed, decisions changed.",
                                   f"Jokaisesta päätöksestä jättää leikkaamatta potilas, jonka syöpä ei ole lähettänyt etäpesäkkeitä, on thoraxkirurgin kirjallinen arvio{about_fi}. Lasketaan: arvioidut päätökset, muuttuneet päätökset."),
        "sbrt_pathway": ("The referral rule is signed and in use: every patient not accepted for surgery is referred for precise radiotherapy within a week. Counted: referrals made, referrals missed.",
                         "Lähettämisen sääntö on hyväksytty ja käytössä: jokainen potilas, jota ei hyväksytä leikkaukseen, lähetetään täsmäsädehoidon arvioon viikon kuluessa. Lasketaan: tehdyt ja tekemättä jääneet lähetteet."),
        "video_mdt_stage1_3": ("The weekly slot has run 12 times, and every stage I–III patient diagnosed in those weeks was discussed before the treatment decision. Counted: patients discussed out of patients diagnosed.",
                               "Viikoittainen videokokous on pidetty 12 kertaa, ja jokainen näinä viikkoina todettu I–III-asteen potilas on käsitelty ennen hoitopäätöstä. Lasketaan: käsitellyt potilaat todetuista."),
        "travel_accommodation_support": ("One named person has offered travel and a hotel to every patient sent for curative treatment. Counted: offers made, patients who still declined treatment because of the trip.",
                                         "Yksi nimetty henkilö on tarjonnut matkan ja majoituksen jokaiselle parantavaan hoitoon lähetetylle potilaalle. Lasketaan: tarjoukset ja potilaat, jotka silti kieltäytyivät hoidosta matkan vuoksi."),
        "prehab_fitness_assessment": ("No patient has been recorded as too frail for curative treatment without an exercise test. Counted: tests done, patients who went on to curative treatment.",
                                      "Yhtäkään potilasta ei ole kirjattu liian heikkokuntoiseksi parantavaan hoitoon ilman rasituskoetta. Lasketaan: tehdyt kokeet ja parantavaan hoitoon edenneet potilaat."),
        "same_day_cxr_ct": ("Every chest X-ray that raises suspicion of lung cancer is followed by a CT the same day. Counted: days from X-ray to CT.",
                            "Jokaista syöpäepäilyn herättävää keuhkokuvaa seuraa TT-kuvaus samana päivänä. Lasketaan: päivät keuhkokuvasta TT-kuvaukseen."),
        "gp_direct_ct": ("GPs at the first health centres order CT themselves. Counted: CTs ordered, days from first visit to CT.",
                         "Ensimmäisten terveysasemien lääkärit tilaavat TT-kuvauksen itse. Lasketaan: tilatut kuvaukset ja päivät ensikäynnistä kuvaukseen."),
        "reflex_molecular": ("Pathology orders biomarker tests for every new lung cancer without waiting for a request. Counted: days from biopsy to result.",
                             "Patologia tilaa biomarkkeritutkimukset jokaisesta uudesta keuhkosyövästä pyyntöä odottamatta. Lasketaan: päivät näytteestä tulokseen."),
        "nurse_navigator": ("Every patient with suspected lung cancer has a named nurse from the referral on. Counted: patients with a named nurse, days from referral to treatment decision.",
                            "Jokaisella keuhkosyöpäepäilyn potilaalla on nimetty hoitaja lähetteestä alkaen. Lasketaan: potilaat, joilla on nimetty hoitaja, ja päivät lähetteestä hoitopäätökseen."),
        "cpp_pathway": ("Booked slots exist for CT, bronchoscopy and the team meeting. Counted: days from referral to treatment decision.",
                        "TT-kuvaukselle, bronkoskopialle ja hoitokokoukselle on varatut ajat. Lasketaan: päivät lähetteestä hoitopäätökseen."),
        "smoking_cessation_at_diagnosis": ("Every smoker is offered help to stop at the first specialist visit. Counted: offers made, patients who started.",
                                           "Jokaiselle tupakoivalle tarjotaan vieroitustukea ensimmäisellä erikoissairaanhoidon käynnillä. Lasketaan: tarjoukset ja aloittaneet potilaat."),
    }
    return table.get(ident) or ("The first step is done and in routine use. Counted each month from the county's own records.",
                                "Ensimmäinen askel on tehty ja vakiintunut käyttöön. Lasketaan kuukausittain alueen omista tiedoista.")


def _pilot_for_ui(scope: str, path: dict | None, rows: list[dict]) -> dict | None:
    if not path or scope == "FI":
        return None
    cur_guard = _stage(path, "curative")
    if cur_guard.get("value") is None or cur_guard.get("national") is None or float(cur_guard.get("value")) >= float(cur_guard.get("national")):
        return None
    ids = ["surgeon_second_opinion", "sbrt_pathway"]
    # The pilot is two actions of this county's own plan; a county whose plan leaves one out has no such pilot.
    if not all(any(r.get("intervention_id") == i for r in rows) for i in ids):
        return None
    sim, _ = _real("simulate", scope, ids)
    if not sim:
        by = {r.get("intervention_id"): r for r in rows}
        extra = sum(_med(by.get(i, {}), "extra_curative_patients_per_year") for i in ids)
        extra_iv = {i: _med(by.get(i, {}), "extra_curative_patients_per_year") for i in ids}
        lo = hi = extra
    else:
        extra = _med(sim.get("extra_curative_patients_per_year") or {}, "median")
        ivs = {r.get("id"): r for r in sim.get("per_intervention") or []}
        extra_iv = {i: float(((ivs.get(i) or {}).get("extra_curative_patients_per_year") or {}).get("median") or 0) for i in ids}
        rr = sim.get("extra_curative_patients_per_year") or {}
        lo, hi = float(rr.get("lo") or 0), float(rr.get("hi") or 0)
    cur = _stage(path, "curative")
    patients = float(path.get("patients_per_year") or 0)
    after = float(cur.get("value") or 0) + (100 * extra / patients if patients else 0)
    surgery = _stage(path, "surgery")
    no_surgery_6m = max(0.0, patients * (1 - float(surgery.get("value") or 0) / 100) / 2)
    # A comparison is supplied as a stable national reference, rather than a claim that
    # another county is a causal control.
    cp = (_read(DATA / "model/care_path.json") or {}).get("paths", {})
    comp_id = max((k for k in cp if k != "FI"), key=lambda k: float(_stage(cp[k], "curative").get("value") or 0), default=None)
    comp = cp.get(comp_id) if comp_id else None
    comp_s = _stage(comp or {}, "surgery")
    comp_patients = float((comp or {}).get("patients_per_year") or 0)
    # The first week is a discovery step.  These are the exact questions represented
    # by stored web checks, so a pilot does not promise a service the hospital already runs.
    ask_map = {
        "surgeon_second_opinion": "Is every stage I–II patient from {name} who is not accepted for surgery already reviewed by a chest surgeon?",
        "sbrt_pathway": "Is every stage I patient from {name} who is not accepted for surgery already referred for precise radiotherapy?",
        "video_mdt_stage1_3": "Is every stage I–III patient from {name} discussed with the university hospital team before a curative decision?",
        "travel_accommodation_support": "Does the university hospital book transport, accommodation and a named contact for {name} patients who travel for curative treatment?",
    }
    checks = []
    for aid in ("surgeon_second_opinion", "sbrt_pathway", "video_mdt_stage1_3", "travel_accommodation_support"):
        f = SERVER / "cache" / "verify" / f"{aid}__{scope}.json"
        d = _read(f) or {}
        if d.get("advice") in ("check_first", "narrow") or d.get("plan_effect") == "flag":
            checks.append({"intervention_id": aid, "question_en": ask_map[aid].format(name=path.get("area_en") or scope),
                           "question_fi": {"surgeon_second_opinion": "Onko jokainen leikkauksesta hylätty I–II-asteen potilas jo thoraxkirurgin uudelleenarvioinnissa?",
                                           "sbrt_pathway": "Lähetetäänkö jokainen leikkauksesta hylätty I-asteen potilas jo täsmäsädehoidon arvioon?",
                                           "video_mdt_stage1_3": "Käsitelläänkö jokainen I–III-asteen potilas jo yliopistosairaalan työryhmässä ennen parantavasta hoidosta luopumista?",
                                           "travel_accommodation_support": "Varaako yliopistosairaala jo kuljetuksen, majoituksen ja yhteyshenkilön kauas matkustaville potilaille?"}[aid],
                           "advice": d.get("advice"), "checked_at": d.get("checked_at")})
    if not checks:
        checks = [{"intervention_id": aid, "question_en": ask_map[aid].format(name=path.get("area_en") or scope),
                   "question_fi": "Kysytään yliopistosairaalalta, onko tämä käytäntö jo käytössä."} for aid in ids]
    comparison_line_en = f"Vantaa and Kerava is the comparison because it has Finland's highest recorded curative share ({float(_stage(comp or {}, 'curative').get('value') or 0):.1f}%): a reachable level, not a causal control."
    comparison_line_fi = f"Vantaa ja Kerava on vertailu, koska siellä kirjattu parantavan hoidon osuus on Suomen korkein ({_fi_num(_stage(comp or {}, 'curative').get('value') or 0)} %): tavoiteltava taso, ei kausaalinen verrokki."
    # The surgeon reviews patients without distant spread, not every non-operated patient (most of those have stage IV disease).
    reviewed = round(_no_spread_not_operated(patients / 2, surgery.get("value")))
    not_operated = round(no_surgery_6m)
    return {
        "months": 6, "actions": ids,
        "ask_first": checks,
        "audit": {"weeks": 8, "charts": 50, "cost_eur": 8000,
                   "fields_en": ["stage", "fitness", "biomarker tested", "why no curative treatment", "where treated"],
                   "fields_fi": ["levinneisyysaste", "toimintakyky", "biomarkkeri tutkittu", "miksi parantavaa hoitoa ei annettu", "missä hoito annettiin"]},
        "comparison_en": comparison_line_en, "comparison_fi": comparison_line_fi,
        "targets_en": "Start the two actions the audit says are new: a chest surgeon reviews every decision not to operate, and every patient who cannot be operated is referred for precise radiotherapy.",
        "targets_fi": "Käynnistetään ne kaksi toimea, jotka tarkistus osoittaa uusiksi: thoraxkirurgi arvioi jokaisen päätöksen jättää leikkaamatta, ja jokainen potilas, jota ei voida leikata, lähetetään täsmäsädehoidon arvioon.",
        "success": {"charts_audited": 50, "decisions_not_to_operate_reviewed": reviewed, "decisions_changed": "count", "referrals_made": "count",
                    "patients_moved": {"model_estimate": round(extra / 2, 1), "lo": 0, "hi": round(hi / 2, 1), "kind": "estimated"}},
        "effect": {"extra_curative_patients_per_year": {"median": round(extra, 2), "lo": round(lo, 2), "hi": round(hi, 2)},
                    "curative_share_now_pct": float(cur.get("value") or 0), "curative_share_after_pct": round(after, 1),
                    "by_year": 2028, "kind": "estimated"},
        "text_en": (f"Six months with {path.get('area_en') or scope} and its university hospital: ask what already runs, check 50 charts, then start the two actions that turn out to be new. "
                    "In week 1, take the stored web-check questions to the university hospital. "
                    "In weeks 1–8 spend €8,000 auditing 50 charts for stage, fitness, biomarker testing, why curative treatment was not given and where treatment happened. "
                    "In months 3–6, start the two actions the audit says are new. Success is counted in charts audited, decisions reviewed, decisions changed and referrals made; patients moved are a secondary model estimate."),
        "text_fi": (f"Kuusi kuukautta {_fi_place(path.get('area_fi') or scope)[1]} ja sen yliopistosairaalan kanssa: kysytään, mikä on jo käytössä, tarkistetaan 50 potilaskertomusta ja käynnistetään ne kaksi toimea, jotka osoittautuvat uusiksi. "
                    "Viikolla 1 viedään tallennetuista verkkotarkistuksista saadut kysymykset yliopistosairaalaan. "
                    "Viikoilla 1–8 käytetään 8 000 euroa 50 potilaskertomuksen tarkistukseen: levinneisyysaste, toimintakyky, biomarkkerit, miksi parantavaa hoitoa ei annettu ja missä hoito annettiin. "
                    "Kuukausina 3–6 käynnistetään kaksi toimea sen mukaan, mitä tarkistus osoittaa. Onnistuminen lasketaan tarkistetuista kertomuksista, arvioiduista päätöksistä, muuttuneista päätöksistä ja lähetteistä; potilassiirtymät ovat toissijainen malliarvio."),
        "six_months": {
            "patients_seen": {"expected": round(patients / 2, 1), "baseline": round(patients / 2, 1), "comparison": round(comp_patients / 2, 1), "unit": "patients"},
            "no_surgery_decisions_reviewed": {"expected": reviewed, "baseline": 0, "comparison": round(_no_spread_not_operated(comp_patients / 2, comp_s.get("value")), 1), "unit": "decisions",
                                              "not_operated": not_operated, "stage_iv_share_pct": round(_stage_iv_share() * 100),
                                              "basis_en": f"{not_operated} patients are not operated in six months. Stage is not published by county; with Finland's stage mix ({round(_stage_iv_share() * 100)}% found at stage IV) about {reviewed} of them have cancer that has not spread to other organs. Those are the decisions reviewed. The chart audit gives the county's own number."},
            "decisions_changed": {"expected": round(extra_iv.get("surgeon_second_opinion", 0) / 2, 1), "baseline": 0, "comparison": None, "unit": "decisions"},
            "referrals_made": {"expected": round(extra_iv.get("sbrt_pathway", 0) / 2, 1), "baseline": 0, "comparison": None, "unit": "referrals"},
            "comparison_area_id": comp_id, "comparison_area_en": (comp or {}).get("area_en") if comp else None,
        },
        "cannot_show_en": f"{after:.1f}% is the model's estimate for these two actions by 2028, not a measurement. The pilot is judged on the work counted, not on a promised change in the county's share.",
        "cannot_show_fi": f"{_fi_num(round(after, 1))} % on mallin arvio näistä kahdesta toimesta vuoteen 2028 mennessä, ei mittaus. Pilottia arvioidaan lasketun työn perusteella, ei luvatun osuuden muutoksen perusteella.",
    }


def _shape_for_ui(res: dict, scope: str, budget_eur: float) -> dict:
    """The one place where the optimiser's answer is shaped for people. The county page and the plan both read this.

    - "shown": one display value per row, rounded so that the rows add up to the total shown (largest remainder).
    - order: the records audit (no direct effect) is step zero, never action 1; the rest are numbered by gain,
      first what the county can start alone, then what needs the collaborative area.
    - "ui.strip": the one-line summary; "ui.pilot": the pilot ask for a county with a measured shortfall.
    Nothing here adds a number the model did not give; only the last decimal of a row can move.
    """
    rows = [c for c in res.get("chosen") or [] if isinstance(c, dict)]
    # Biomarker testing does not "shorten the pathway" only: its result decides the drug. Say where it belongs instead.
    for n in res.get("not_chosen") or []:
        if isinstance(n, dict) and n.get("intervention_id") == "reflex_molecular" and n.get("reason_code") == "no_effect" \
                and "treated to cure" in str(n.get("reason_en") or ""):
            n["reason_en"] = ("Not counted in this plan: the model counts only who is operated or given radiotherapy that aims to cure. "
                              "The biomarker result decides the drug that follows, so this belongs to the second finding, drug treatment. "
                              "The chart audit counts the tests first.")
    cp = ((_read(DATA / "model/care_path.json") or {}).get("paths") or {}).get(scope)
    iv_by_id = {i.get("id"): i for i in (_read(DATA / "evidence/interventions.json") or []) if isinstance(i, dict)}
    for c in rows:
        iv = iv_by_id.get(c.get("intervention_id"), {})
        c.setdefault("study_line_en", _study_line(iv))
        c.setdefault("why_here_en", _why_here(scope, c, cp))
        c.setdefault("study_line_fi", _study_line_fi(iv))
        c.setdefault("why_here_fi", _why_here_fi(scope, c, cp))
        if "day90_en" not in c:
            c["day90_en"], c["day90_fi"] = _day90(scope, c, cp)
    totals = res.get("totals") if isinstance(res.get("totals"), dict) else None
    if totals is None:
        return res
    shown_tot: dict = {}
    for key, short in _METRICS:
        tot = (totals.get(key) or {}).get("median") if isinstance(totals.get(key), dict) else None
        if tot is None:
            continue
        raw = [_med(c, key) for c in rows]
        want = _tenths(tot)
        got = [_tenths(v) for v in raw]
        diff = want - sum(got)
        if diff and abs(diff) <= len(rows):
            # remainder = how far the exact value is above its rounded value; the rows that lost most take the difference
            rem = sorted(range(len(rows)), key=lambda i: (raw[i] * 10 - got[i]) * (1 if diff > 0 else -1), reverse=True)
            for i in [i for i in rem if raw[i] != 0][:abs(diff)]:
                got[i] += 1 if diff > 0 else -1
        for c, g in zip(rows, got):
            c.setdefault("shown", {})[short] = g / 10
        shown_tot[short] = sum(got) / 10 if rows else want / 10
    totals["shown"] = shown_tot
    totals["shown_note_en"] = _SHOWN_NOTE
    for c in res.get("needs_national_decision") or []:
        if isinstance(c, dict):
            c["shown"] = {short: _tenths(_med(c, key)) / 10 for key, short in _METRICS}

    objective = res.get("objective")
    metric = "deaths" if objective == "deaths" else "extra"
    mkey = "deaths_avoided_per_year" if metric == "deaths" else "extra_curative_patients_per_year"
    gain = lambda c: (-_med(c, mkey), float(c.get("eur") or 0))  # noqa: E731
    is_zero = lambda c: all(_med(c, k) == 0 for k, _ in _METRICS)  # noqa: E731
    ui: dict = {"metric": metric}
    by_area = {a["id"]: a for a in areas_list()}

    if scope == "FI":
        counties: dict[str, list] = {}
        for c in rows:
            counties.setdefault(str(c.get("area_id")), []).append(c)
        order = sorted(counties, key=lambda k: (-sum(_med(c, mkey) for c in counties[k]), k))
        ui["by_county"] = []
        ordered = []
        for n, aid in enumerate(order, 1):
            cs = sorted(counties[aid], key=lambda c: (is_zero(c), *gain(c)))
            for c in cs:
                c["n"], c["group"] = n, aid
            ordered += cs
            meta = by_area.get(aid, {})
            ui["by_county"].append({
                "n": n, "area_id": aid, "area_en": meta.get("short_en") or cs[0].get("area_en"), "area_fi": meta.get("name_fi") or meta.get("short_fi"),
                "eur": sum(int(c.get("eur") or 0) for c in cs),
                "extra": round(sum(c["shown"].get("extra", 0) for c in cs), 1), "deaths": round(sum(c["shown"].get("deaths", 0) for c in cs), 1),
                "measures": [{"intervention_id": c.get("intervention_id"), "name_en": c.get("name_en"), "name_fi": c.get("name_fi"),
                              "eur": c.get("eur"), "shown": c.get("shown")} for c in cs]})
        res["chosen"] = ordered
    else:
        zero = sorted([c for c in rows if is_zero(c)], key=gain)
        rest = [c for c in rows if not is_zero(c)]
        ordered, groups, n = list(zero), [], 0
        for c in zero:
            c["n"], c["group"] = 0, "step_zero"
        known = {g[0] for g in _GROUPS}
        for gid, t_en, t_fi in _GROUPS:
            cs = sorted([c for c in rest if (c.get("owner_level") if c.get("owner_level") in known else "county") == gid], key=gain)
            if not cs:
                continue
            for c in cs:
                n += 1
                c["n"], c["group"] = n, gid
            groups.append({"id": gid, "title_en": t_en, "title_fi": t_fi, "ids": [c.get("intervention_id") for c in cs]})
            ordered += cs
        res["chosen"] = ordered
        ui["step_zero"] = [c.get("intervention_id") for c in zero]
        ui["step_zero_title_en"] = "Step zero: fix the records (no direct effect)"
        ui["step_zero_title_fi"] = "Vaihe nolla: kirjaukset kuntoon (ei suoraa vaikutusta)"
        ui["groups"] = groups
    ui["national_title_en"] = "Needs a national decision (outside this budget)"
    ui["national_title_fi"] = "Vaatii kansallisen päätöksen (ei sisälly tähän budjettiin)"

    # ---- summary strip: numbers from the optimiser output only
    spent, left = float(totals.get("eur") or 0), float(totals.get("eur_left") if totals.get("eur_left") is not None else max(0.0, budget_eur - float(totals.get("eur") or 0)))
    short = float(totals.get("shortfall_vs_national_per_year") or 0)
    pct = totals.get("gap_closed_pct")
    extra, deaths = shown_tot.get("extra", 0.0), shown_tot.get("deaths", 0.0)
    sat = bool(res.get("saturated"))
    if not rows:
        lead_en, lead_fi = "No measure adds to this objective here", "Mikään toimi ei lisää tätä tavoitetta täällä"
    elif metric == "extra" and short > 0 and pct is not None:
        lead_en = f"Closes {extra:.1f} of {short:.1f} missing patients a year ({round(float(pct))}%)"
        lead_fi = f"Kuroo umpeen {num_fi(extra)} vuosittain puuttuvasta {num_fi(short)} potilaasta ({round(float(pct))} %)"
    elif metric == "extra":
        lead_en = f"{extra:.1f} more patients a year treated to cure"
        lead_fi = f"{num_fi(extra)} potilasta lisää parantavaan hoitoon vuodessa"
    else:
        lead_en = f"About {deaths:.1f} deaths avoided a year (modelled)"
        lead_fi = f"Arviolta {num_fi(deaths)} kuolemaa vähemmän vuodessa (mallinnettu)"
    money_en, money_fi = f"{eur_en(spent)} of {eur_en(budget_eur)}", f"{eur_fi(spent)} / {eur_fi(budget_eur)}"
    if left <= 0:
        left_en, left_fi = "the whole budget is used", "koko budjetti käytetään"
    elif sat:
        left_en = f"{eur_en(left)} left: nothing else pays off at these assumptions"
        left_fi = f"{eur_fi(left)} jää käyttämättä: näillä oletuksilla mikään muu ei tuo lisää"
    else:
        left_en = f"{eur_en(left)} left: less than the next measure costs"
        left_fi = f"{eur_fi(left)} jää käyttämättä: ei riitä seuraavaan toimeen"
    ui["strip"] = {"closes": extra if metric == "extra" else None, "of": short if (metric == "extra" and short > 0) else None,
                   "pct": round(float(pct)) if (metric == "extra" and pct is not None and short > 0) else None,
                   "deaths": deaths if metric == "deaths" else None, "spent": spent, "budget": float(budget_eur), "left": left, "saturated": sat,
                   "lead_en": lead_en, "lead_fi": lead_fi, "money_en": money_en, "money_fi": money_fi, "left_en": left_en, "left_fi": left_fi,
                   "text_en": " · ".join([lead_en, money_en, left_en]), "text_fi": " · ".join([lead_fi, money_fi, left_fi])}

    # ---- pilot ask: only where there is a measured shortfall and the plan adds patients treated to cure
    ui["pilot"] = None
    if scope != "FI" and metric == "extra" and short > 0 and extra > 0:
        try:
            meta = (area(scope).get("area") or {})
        except Exception:  # noqa: BLE001
            meta = {}
        ranked = sorted([c for c in res["chosen"] if _med(c, mkey) > 0], key=gain)
        # the biggest gain, then the biggest one owned at the other level (county / collaborative area), else the runner-up
        top = ranked[:1] + ([c for c in ranked[1:] if c.get("group") != ranked[0].get("group")] or ranked[1:])[:1]
        now, after = totals.get("curative_share_now_pct"), totals.get("curative_share_after_pct")
        years = [c.get("kpi", {}).get("by_year") for c in res["chosen"] if isinstance(c.get("kpi"), dict) and c["kpi"].get("by_year")]
        if top and now is not None and after is not None and years:
            needs_yta = any(c.get("owner_level") == "collaborative_area" for c in top) and meta.get("yta")
            who_en = (meta.get("name_en") or meta.get("short_en") or scope) + (f" + the {meta['yta']} collaborative area" if needs_yta else "")
            who_fi = (meta.get("name_fi") or scope) + (f" + {meta.get('yta_name_fi') or 'yhteistyöalue'} ({meta['yta']})" if needs_yta else "")
            low = lambda t: t[:1].lower() + t[1:] if t and not t[:2].isupper() else t  # noqa: E731
            ui["pilot"] = {
                "text_en": f"Pilot: {who_en}, 6 months: {_listed([low(c.get('name_en') or '') for c in top])}. "
                           f"KPI: share of patients treated to cure {float(now):.1f}% → {float(after):.1f}% by {max(years)}.",
                "text_fi": f"Pilotti: {who_fi}, 6 kuukautta: {_listed([low(c.get('name_fi') or c.get('name_en') or '') for c in top])}. "
                           f"Mittari: parantavaan hoitoon pääsevien osuus {num_fi(now)} % → {num_fi(after)} % vuoteen {max(years)} mennessä.",
                "months": 6, "interventions": [c.get("intervention_id") for c in top], "by_year": max(years)}
    pilot = _pilot_for_ui(scope, cp, rows)
    res["ui"] = ui
    # Keep the richer pilot at the same UI location consumed by the county page,
    # while also returning it at the top level for API/plan clients.
    ui["pilot"] = pilot
    res["pilot"] = pilot
    return res


def model_fingerprint() -> str:
    """Short id of the model inputs; the plan cache is keyed on it so the same inputs give the same page."""
    api = kello_api()
    try:
        return str(api.fingerprint()) if api is not None else "nomodel"
    except Exception:  # noqa: BLE001
        return "nofp"


def roadmap_measures() -> tuple[list, bool]:
    real = _read(DATA / "evidence/roadmap_measures.json")
    if isinstance(real, dict):
        real = real.get("measures") or [{"id": k, **v} if isinstance(v, dict) else {"id": k, "title_en": v} for k, v in real.items()]
    if isinstance(real, list) and real:
        return real, False
    return fixture_model.load("roadmap_measures.json"), True


def parameters() -> tuple[dict, bool]:
    real = _read(DATA / "evidence/parameters.json")
    if isinstance(real, dict) and real:
        return real, False
    return fixture_model.load("parameters.json"), True


_DEV_NOTE = re.compile(r"(downloaded \d+ bytes|not parsed|/tmp/|data/raw|embedded data block|file downloaded earlier|file time used|api field|pipeline|expected here|priors\.py|\.csv\b|\.py\b)", re.I)


def _clean_note(note) -> str | None:
    """Keep the sentences of a source note that tell a reader something; drop the ones written for developers."""
    if not note:
        return None
    keep = [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-ZÅÄÖ0-9(])", str(note)) if x.strip() and not _DEV_NOTE.search(x)]
    text = " ".join(keep).strip()
    # field names are for developers: "Column some_field (what it is)" keeps only what it is
    text = re.sub(r"\b(?:Column|Field|Indicator)s? [a-z0-9]+(?:_[a-z0-9]+)+ \(([^)]*)\)", lambda m: m.group(1)[:1].upper() + m.group(1)[1:], text)
    text = re.sub(r"\s*\((?:indicators?|fields?|columns?)? ?[a-z0-9]+(?:_[a-z0-9]+)+(?:, ?[a-z0-9]+(?:_[a-z0-9]+)+)*\)", "", text).strip()
    return (text[:300].rsplit(" ", 1)[0] + " …") if len(text) > 300 else (text or None)


def _source_use() -> tuple[dict[str, int], set[str]]:
    """(values taken from each source id, ids behind a number the app shows)."""
    reg = _read(DATA / "processed/sources.json") or {}
    by_url = {str(v.get("url")).rstrip("/"): k for k, v in reg.items() if isinstance(v, dict) and v.get("url")}
    counts: dict[str, int] = {}
    used: set[str] = set()
    f = DATA / "processed/indicators.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            m = re.search(r'"source_id":\s*"([^"]+)"', line)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    for d in measured_mod.documents():
        sid = by_url.get(str(d["url"]).rstrip("/"))
        if sid:
            counts[sid] = counts.get(sid, 0) + d["rows"]
            used.add(sid)
    g3 = _read(DATA / "processed/goal3.json") or {}
    for part in ("county", "collaborative_area", "national", "survival_targets"):
        for r in g3.get(part) or []:
            sid = r.get("source_id")
            if sid:
                counts[sid] = counts.get(sid, 0) + 1
                used.add(sid)
    mt = g3.get("mortality_trend") or {}
    if mt.get("source_id"):
        counts[mt["source_id"]] = counts.get(mt["source_id"], 0) + len(mt.get("series") or [])
        used.add(mt["source_id"])
    for ev in (g3.get("treated_within_target") or {}).get("evidence") or []:
        sid = by_url.get(str(ev.get("url")).rstrip("/"))
        if sid:
            used.add(sid)
    try:
        for b in (overview().get("national") or {}).get("survival") or []:
            if b.get("source_id"):
                used.add(b["source_id"])
    except Exception as e:  # noqa: BLE001
        log.warning("could not list the sources in use: %s", e)
    return counts, used


def sources() -> dict:
    return memo("sources", _sources)


def _sources() -> dict:
    real = _read(DATA / "processed/sources.json")
    is_fx = not (isinstance(real, dict) and real)
    src = fixture_model.load("sources.json") if is_fx else real
    counts, used = ({}, set()) if is_fx else _source_use()
    shown = {}
    for sid, rec in src.items():
        if not isinstance(rec, dict):
            continue
        n = counts.get(sid, 0)
        rec = {**rec, "notes": _clean_note(rec.get("notes")), "values": n, "used": n > 0 or sid in used,
               # "opened": a number was read from it; "listed": downloaded, no number taken
               "status": "opened" if n > 0 else "listed"}
        rec.pop("api_call", None)
        shown[sid] = rec
    src = dict(sorted(shown.items(), key=lambda kv: (not kv[1]["used"], kv[1]["status"] != "opened", -kv[1]["values"])))
    ivs, iv_fx = interventions()
    evidence = []
    for iv in ivs:
        for ev in iv.get("evidence") or []:
            evidence.append({"intervention_id": iv["id"], "intervention": iv.get("name_en"), "kind": "evidence", **ev})
        for nr in iv.get("null_results") or []:
            evidence.append({"intervention_id": iv["id"], "intervention": iv.get("name_en"), "kind": "null_result", **nr})
        cost = iv.get("cost") or {}
        if cost.get("source_url"):
            evidence.append({"intervention_id": iv["id"], "intervention": iv.get("name_en"), "kind": "cost",
                             "claim": cost.get("basis"), "url": cost["source_url"]})
    params, p_fx = parameters()
    plist = [{"key": k, **v} for k, v in params.items() if isinstance(v, dict)]
    out = {"sources": src, "evidence": evidence, "parameters": plist,
           "status_help": {"opened": "Opened: we read the number on this page.", "listed": "Listed: we downloaded it but took no number from it."},
           "parts": {"sources": "fixture" if is_fx else "real", "evidence": "fixture" if iv_fx else "real",
                     "parameters": "fixture" if p_fx else "real"}}
    return _fx(out) if (is_fx or iv_fx or p_fx) else out


def geo() -> dict:
    return memo("geo", _geo)


def _geo() -> dict:
    """areas.geojson with rings wound the way d3-geo expects (exterior clockwise)."""
    g = _read(DATA / "processed/areas.geojson")
    if not g:
        raise FileNotFoundError("data/processed/areas.geojson")

    def signed(ring):
        return sum((x2 - x1) * (y2 + y1) for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:]))  # >0 means clockwise

    def fix(poly):
        out = []
        for i, ring in enumerate(poly):
            cw = signed(ring) > 0
            out.append(ring if cw == (i == 0) else ring[::-1])
        return out

    for f in g.get("features", []):
        geom = f.get("geometry") or {}
        if geom.get("type") == "Polygon":
            geom["coordinates"] = fix(geom["coordinates"])
        elif geom.get("type") == "MultiPolygon":
            geom["coordinates"] = [fix(p) for p in geom["coordinates"]]
    return g


def reader() -> dict:
    """What the Gemini reader has read: documents with row counts, straight from gemini_extracted.jsonl."""
    reg = _read(DATA / "processed/sources.json") or {}
    by_url = {v.get("url"): {"source_id": k, **v} for k, v in reg.items() if isinstance(v, dict) and v.get("url")}
    titles = {}
    for f in sorted((SERVER / "integrations/examples").glob("read_report_*.json")):
        ex = _read(f)
        for item in (ex if isinstance(ex, list) else [ex]):
            doc = (item or {}).get("document") if isinstance(item, dict) else None
            if isinstance(doc, dict) and doc.get("url"):
                titles[doc["url"]] = doc
    docs = []
    for d in measured_mod.documents():
        r, t = by_url.get(d["url"], {}), titles.get(d["url"], {})
        docs.append({**d, "title": r.get("title") or t.get("title"), "publisher": r.get("publisher") or t.get("publisher"),
                     "source_id": r.get("source_id"), "retrieved_at": r.get("retrieved_at")})
    return {"documents": docs, "rows": sum(d["rows"] for d in docs)}


SCIENCE = ROOT / "science" / "out"


def science() -> dict:
    """Claude Science analyses, if any were written to science/out/<name>/."""
    out = []
    if SCIENCE.is_dir():
        for d in sorted(p for p in SCIENCE.iterdir() if p.is_dir() and not p.name.startswith(".")):
            files = [f for f in sorted(d.rglob("*")) if f.is_file() and not f.name.startswith(".") and "__pycache__" not in f.parts][:60]
            if not files:
                continue
            title = d.name.replace("_", " ").replace("-", " ")
            readme = next((f for f in files if f.name.lower() in ("readme.md", "summary.md", "report.md")), None)
            if readme:
                first = next((ln.lstrip("# ").strip() for ln in readme.read_text(errors="replace").splitlines() if ln.strip()), "")
                title = first[:120] or title
            meta = {}
            if (d / "meta.json").is_file():
                try:
                    meta = json.loads((d / "meta.json").read_text())
                except ValueError:
                    meta = {}
            fig = meta.get("figure")
            out.append({"id": d.name, "title": meta.get("title") or title, "finding_en": meta.get("finding_en"),
                        "figure_url": f"/science/{d.name}/{fig}" if fig and (d / fig).is_file() else None,
                        "figure_alt": meta.get("figure_alt"),
                        "answer_url": f"/science/{d.name}/answer.md" if (d / "answer.md").is_file() else None,
                        "files": [{"name": str(f.relative_to(d)), "url": f"/science/{d.name}/{f.relative_to(d)}", "bytes": f.stat().st_size} for f in files]})
    return {"analyses": out}


def verify_available() -> bool:
    try:
        return bool(importlib.import_module("integrations.oxylabs").has_credentials())
    except Exception:  # noqa: BLE001
        return False


def status() -> dict:
    import os
    integ = {}
    for mod, fn in (("integrations.verify", "verify_claim"), ("integrations.gemini_reader", "read_report")):
        try:
            integ[fn] = hasattr(importlib.import_module(mod), fn)
        except Exception as e:  # noqa: BLE001
            integ[fn] = False
            integ[fn + "_error"] = str(e)[:200]
    return {
        "kello_model": kello_api() is not None,
        "files": {p: (DATA / p).exists() for p in ("processed/sources.json", "processed/indicators.jsonl", "evidence/interventions.json",
                                                   "evidence/parameters.json", "evidence/roadmap_measures.json", "model/pathways.json",
                                                   "model/plans.json")},
        "integrations": integ,
        "verify_available": bool(integ.get("verify_claim")) and verify_available(),
        "reader_available": bool(integ.get("read_report")) and bool(os.environ.get("GEMINI_API_KEY")),
        "claude_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }
