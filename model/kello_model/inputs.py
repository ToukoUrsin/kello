"""Reads the other agents' files when present, falls back to defaults.py when absent.

`Inputs.provenance` says, per input, whether the real file or the built-in default was used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import defaults, priors

ROOT = Path(os.environ.get("KELLO_ROOT") or Path(__file__).resolve().parents[2])
PROC = ROOT / "data" / "processed"
EVID = ROOT / "data" / "evidence"
MODEL = ROOT / "data" / "model"

STEPS = ["patient", "primary", "referral", "diagnosis", "treatment"]
STEP_LABEL = {
    "patient": "First symptom to first primary care contact",
    "primary": "First primary care contact to referral",
    "referral": "Referral to first specialist visit",
    "diagnosis": "First specialist visit to diagnosis",
    "treatment": "Diagnosis to treatment start",
}
FILES = {
    "indicators": PROC / "indicators.jsonl",
    "catalog": PROC / "indicators_catalog.json",
    "sources": PROC / "sources.json",
    "gemini": PROC / "gemini_extracted.jsonl",
    "parameters": EVID / "parameters.json",
    "interventions": EVID / "interventions.json",
    "queue_series": PROC / "thl_queue_series.jsonl",
    "registry_tables": EVID / "registry_tables.json",   # county counts n/N parsed from the registry report (care path)
    "goal3": PROC / "goal3.json",                       # registry age-standardised incidence and mortality, deaths, cases
}


def _read_json(p: Path):
    try:
        if p.exists() and p.stat().st_size > 2:
            return json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return None


def _read_jsonl(p: Path):
    rows = []
    try:
        if not p.exists() or p.stat().st_size == 0:
            return None
        with p.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue  # a file being written may end in a partial line
    except OSError:
        return None
    return rows or None


def fingerprint() -> str:
    h = hashlib.sha1()
    for k, p in sorted(FILES.items()):
        try:
            st = p.stat()
            h.update(f"{k}:{st.st_size}:{int(st.st_mtime)}".encode())
        except OSError:
            h.update(f"{k}:absent".encode())
    for f in sorted(Path(__file__).parent.glob("*.py")):   # any change to the model code invalidates precomputed files
        if f.name != "precompute.py":
            h.update(str(f.stat().st_mtime_ns).encode())
    return h.hexdigest()[:12]


def _num(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.replace(",", ".").replace("%", "").strip())
        except ValueError:
            return None
    return None


def _vlh(node, default=None):
    """Normalise a `{value, lo, hi, ...}` node (or bare number) to a dict with floats."""
    if node is None:
        return copy.deepcopy(default)
    if not isinstance(node, dict):
        v = _num(node)
        return {"value": v, "lo": v, "hi": v} if v is not None else copy.deepcopy(default)
    v = _num(node.get("value", node.get("median", node.get("days"))))
    if v is None:
        return copy.deepcopy(default)
    out = dict(node)
    lo, hi = _num(node.get("lo")), _num(node.get("hi"))
    out.update(value=v, lo=v if lo is None else lo, hi=v if hi is None else hi)
    return out


@dataclass
class Inputs:
    areas: list
    values: dict            # indicator -> area_id -> row (latest period, both sexes)
    catalog: dict
    sources: dict
    params: dict
    interventions: list
    provenance: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    fingerprint: str = ""
    series: dict = field(default_factory=dict)   # indicator -> area_id -> {period: value}
    gemini: list = field(default_factory=list)   # rows Gemini read from registry reports (value/confidence as numbers)
    goal3: dict = field(default_factory=dict)    # (area_id, metric) -> registry row for lung cancer, both sexes
    goal3_raw: dict = field(default_factory=dict)

    def g3(self, metric, area_id):
        """Registry statistics row (lung, both sexes): cases_n, deaths_n, incidence_asr, mortality_asr."""
        return self.goal3.get((str(area_id), metric))

    def mean_recent(self, indicator, area_id, n=5):
        """Mean of the last n yearly values (small counties are noisy from year to year)."""
        d = self.series.get(indicator, {}).get(area_id)
        if not d:
            return None
        ks = sorted(d)[-n:]
        return sum(d[k] for k in ks) / len(ks)

    def get(self, indicator, area_id):
        for key in [indicator] + priors.ALIASES.get(indicator, []):
            row = self.values.get(key, {}).get(area_id)
            if row is not None:
                return row
        return None

    def val(self, indicator, area_id):
        row = self.get(indicator, area_id)
        return None if row is None else row["value"]


# ---------------------------------------------------------------- indicators
def _latest_values(rows):
    """Keep one row per (indicator, area): both sexes if available, latest period."""
    best = {}
    for r in rows:
        v = _num(r.get("value"))
        ind, area = r.get("indicator"), r.get("area_id")
        if v is None or not ind or area is None:
            continue
        sex = (r.get("sex") or "total").lower()
        rank = (1 if sex in ("total", "all", "both", "yhteensä") else 0, str(r.get("period", "")))
        key = (ind, str(area))
        if key not in best or rank > best[key][0]:
            rr = dict(r)
            rr["value"] = v
            rr["area_id"] = str(area)
            best[key] = (rank, rr)
    out = {}
    for (ind, area), (_, r) in best.items():
        out.setdefault(ind, {})[area] = r
    return out


# ---------------------------------------------------------------- parameters
def _find(raw, *patterns):
    """Depth-first search for the first dict/number whose key path matches all regexes."""
    hits = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}/{k}".lower()
                if all(re.search(pt, p) for pt in patterns) and (
                        _num(v) is not None or (isinstance(v, dict) and _vlh(v) is not None)):
                    hits.append((len(p), p, v))
                walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}/{i}")

    walk(raw, "")
    return sorted(hits, key=lambda h: h[0])[0][2] if hits else None


COUNTRY = {"FI": "Finland", "SE": "Sweden", "DK": "Denmark", "NO": "Norway", "IS": "Iceland"}


def _widen(v, d):
    """No interval published: add +-d as an assumption so the uncertainty is not zero."""
    v = dict(v)
    if abs(v["hi"] - v["lo"]) < 1e-12:
        v["lo"], v["hi"], v["interval_kind"] = v["value"] - d, v["value"] + d, "assumption"
    return v


def normalise_parameters(raw, notes):
    """Map the evidence agent's parameters.json onto the internal schema; every field that
    cannot be found keeps its default and is listed in `notes`."""
    P = copy.deepcopy(defaults.PARAMETERS)
    P["_real_fields"] = []
    if not isinstance(raw, dict):
        return P
    real = P["_real_fields"]

    def take(name, node, setter):
        v = _vlh(node)
        if v is None:
            notes.append(f"parameters.json has no usable '{name}': built-in default kept")
            return False
        setter(v)
        real.append(name)
        return True

    # national step medians
    base = raw.get("baseline_days") or raw.get("national_baseline_days") or {}
    steps_node = base.get("steps") if isinstance(base.get("steps"), dict) else base
    for s in STEPS:
        take(f"steps.{s}", (steps_node or {}).get(s),
             lambda v, s=s: P["steps"].__setitem__(s, {**v, "kind": v.get("kind", "measured"),
                                                       "source": v.get("method") or v.get("note") or v.get("url")}))

    # benchmarks: total days symptom -> treatment
    bm = raw.get("nordic_benchmarks_total_days") or raw.get("benchmarks") or {}
    out = []
    if isinstance(bm, dict):
        for code, node in bm.items():
            v = _vlh(node) if isinstance(node, dict) else None
            if v:
                out.append({"country": COUNTRY.get(code, code), "days": v["value"], "source_id": v.get("url"),
                            "kind": v.get("kind", "measured"), "verified": v.get("verified")})
    if out:
        P["benchmarks"] = out
        real.append("benchmarks")
    else:
        notes.append("parameters.json has no benchmarks: built-in default kept")

    # best Nordic standard time referral -> treatment, for the floor of the three specialist steps
    best = None
    for prog, node in (raw.get("target_times") or {}).items():
        if prog.startswith("FI") or not isinstance(node, dict):
            continue
        for k in ("referral_to_treatment", "suspicion_to_treatment"):
            v = _vlh(node.get(k))
            if v and (best is None or v["value"] < best[0]):
                best = (v["value"], prog, v.get("url"))
    spec = _vlh(base.get("specialist_total"))
    if best and spec:
        P["specialist_floor"] = {"days": best[0], "programme": best[1], "url": best[2], "fi_days": spec["value"]}
        real.append("specialist_floor")

    hr = ((raw.get("delay_mortality") or {}).get("hr_per_4_weeks") or {})
    take("hazard_per_4w", hr.get("lung_surgery") or hr.get("surgery") or raw.get("hazard_per_4w"),
         lambda v: P.__setitem__("hazard_per_4w", {**v, "source": "Hanna et al., BMJ 2020: " + str(v.get("note", ""))[:160]}))
    facts = raw.get("finland_lung_facts") or {}
    take("curative_share", facts.get("curative_intent_share_pct") or raw.get("curative_share"),
         lambda v: P.__setitem__("curative_share", _widen(_share(v), 0.05)))
    surv = raw.get("stage_survival_5y_pct") or {}
    take("survival_5y.early", surv.get("stage_I"), lambda v: P["survival_5y"].__setitem__("early", _widen(_share(v), 0.05)))
    take("survival_5y.late", surv.get("stage_IV"), lambda v: P["survival_5y"].__setitem__("late", _widen(_share(v), 0.03)))
    for name, key in (("incidence", "annual_new_cases"), ("deaths", "annual_deaths")):
        v = _vlh(facts.get(key))
        if v and v["value"] > 500:
            P["national"][name] = v
            real.append(f"national.{name}")
    fs = facts.get("five_year_survival_pct")
    if isinstance(fs, dict):
        for k, node in fs.items():
            v = _vlh(node) if isinstance(node, dict) else None
            if v:
                c, _, sex = k.partition("_")
                P["survival"].append({"country": COUNTRY.get(c, c), "sex": sex or "all", "value": v["value"], "source_id": v.get("url")})

    mh = raw.get("measured_hospital_times")
    if isinstance(mh, list):
        got = []
        for m in mh:
            if not isinstance(m, dict):
                continue
            area = m.get("area_id")
            cands = [(m.get("steps") or _span(m.get("from_step"), m.get("to_step")), _num(m.get("days", m.get("value")))),
                     (["referral", "diagnosis", "treatment"], _num(m.get("referral_to_treatment_days"))),
                     (["referral"], _num(m.get("referral_to_first_visit_days")))]
            ok = [(st, d) for st, d in cands if st and d is not None and area is not None]
            if not ok:
                notes.append(f"measured_hospital_times: {m.get('hospital', area)} has no value the evidence agent could open "
                             "(left empty rather than filled from memory): its steps stay estimated")
                continue
            st, d = ok[0]
            got.append({**m, "area_id": str(area), "days": d, "steps": [x for x in st if x in STEPS],
                        "what_en": m.get("what_en") or f"{st[0]} to end of {st[-1]}"})
        P["measured_hospital_times"] = got
        real.append(f"measured_hospital_times({len(got)} usable)")
    return P


def _share(v):
    """Accept 27 or 0.27 for a share."""
    v = dict(v)
    if v["value"] > 1.0:
        for k in ("value", "lo", "hi"):
            v[k] = v[k] / 100.0
    return v


def _span(a, b):
    if a in STEPS and b in STEPS:
        return STEPS[STEPS.index(a): STEPS.index(b) + 1]
    return None


# ---------------------------------------------------------------- interventions
CAPACITY_WORDS = r"capacity|extra (ct|slots|clinic)|more (ct|slots|scanner)|scanner|additional (ct|slots|radiolog|staff)|kapasiteet|mobile ct|weekend|evening (ct|scan)"
DEMAND_WORDS = r"\bai\b|artificial intelligence|tekoäly|triage of (chest )?x-?ray|x-?ray triage|computer-aided|cad\b"
SCREEN_WORDS = r"screen|seulon|ldct"
# intervention id -> capacity|demand|process|screening (checked by hand against interventions.json)
MECHANISM_OVERRIDES: dict[str, str] = {
    "same_day_cxr_ct": "capacity",       # radiologist reporting time + CT slots that can act on a flag
    "ebus_capacity": "capacity",
    "ai_cxr_triage_alone": "demand",     # flags patients sooner, adds no slots
    "gp_capacity_econsult": "process",   # primary care is not modelled as a queue
    "cpp_pathway": "process", "nurse_navigator": "process",
    "nssc_rapid_dx_centre": "process", "gp_direct_ct": "process",
}


METRICS = ("days", "relative_days", "stage_shift_pp", "mortality_rr", "curative_share_pp")


def normalise_intervention(iv):
    iv = dict(iv)
    eff = iv.get("effect") or {}
    metric = eff.get("metric")
    v = _vlh(eff)
    if v is None or metric not in METRICS:
        return None
    lo, hi = sorted((v["lo"], v["hi"]))
    val = min(max(v["value"], lo), hi)
    # sign convention (parameters.json _meta): days / relative_days are days SAVED, positive = faster.
    iv["metric"], iv["value"], iv["lo"], iv["hi"] = metric, val, lo, hi
    step = eff.get("applies_to_steps") or iv.get("step")
    steps = step if isinstance(step, list) else re.split(r"[+,/ ]+", str(step or ""))
    iv["steps"] = [s for s in steps if s in STEPS]
    if any(s in ("all", "pathway", "whole") for s in steps):
        iv["steps"] = list(STEPS)
    text = " ".join(str(iv.get(k, "")) for k in ("id", "name_en", "what_en")).lower()
    mech = iv.get("mechanism") or MECHANISM_OVERRIDES.get(iv.get("id"))
    if metric == "curative_share_pp":
        iv["steps"] = []          # changes who is treated, not how long a step takes
    if mech not in ("capacity", "demand", "process", "screening", "access"):
        if metric == "curative_share_pp":
            mech = "access"
        elif metric in ("stage_shift_pp", "mortality_rr") or (re.search(SCREEN_WORDS, text) and not iv["steps"]):
            mech = "screening"
        elif re.search(DEMAND_WORDS, text):
            mech = "demand"
        elif re.search(CAPACITY_WORDS, text):
            mech = "capacity"
        else:
            mech = "process"
    iv["mechanism"] = mech
    cost = iv.get("cost") or {}
    iv["cost"] = {**cost, "eur_setup": _num(cost.get("eur_setup")) or 0.0, "eur_per_year": _num(cost.get("eur_per_year")) or 0.0,
                  "scales_with": cost.get("scales_with") or "county", "kind": cost.get("kind") or "assumption"}
    iv["confidence"] = iv.get("confidence") or "low"
    iv["requires"] = list(iv.get("requires") or [])
    iv["owner_level"] = iv.get("owner_level") or "county"
    iv.setdefault("targets_stage", None)
    iv.setdefault("modality", None)
    return iv


# ---------------------------------------------------------------- load
_CACHE: dict = {}


def load_inputs(force=False) -> Inputs:
    fp = fingerprint()
    if not force and _CACHE.get("fp") == fp:
        return _CACHE["inp"]
    prov, notes = {}, []
    areas = _read_json(PROC / "areas.json") or []

    rows = _read_jsonl(FILES["indicators"])
    prov["indicators"] = "real" if rows else "default (absent)"
    values = _latest_values(rows or [])
    series: dict = {}
    for r in rows or []:
        if r.get("indicator") in ("lung_deaths_n", "lung_cases_n") and _num(r.get("value")) is not None and not r.get("sex"):
            series.setdefault(r["indicator"], {}).setdefault(str(r["area_id"]), {})[str(r.get("period"))] = _num(r["value"])
    grows = _read_jsonl(FILES["gemini"])
    prov["gemini_extracted"] = "absent"
    gemini = []
    for r in grows or []:
        v = _num(r.get("value"))
        if v is None or not r.get("indicator"):
            continue
        c = _num(r.get("confidence"))
        gemini.append({**r, "value": v, "area_id": str(r.get("area_id")), "confidence": 0.0 if c is None else c,
                       "verified": str(r.get("verified")).strip().lower() in ("true", "1"),
                       "sex": (r.get("sex") or "all").lower(), "period": str(r.get("period") or "")})
    if grows:
        # only verified, confident reads enter the model's indicator table
        usable = [r for r in gemini if r["verified"] and r["confidence"] >= 0.7]
        gv = _latest_values([r for r in usable if r.get("indicator")])
        known = {a["id"] for a in areas} | {"FI"}
        n = 0
        for ind, per_area in gv.items():
            for area, r in per_area.items():
                if area in known and area not in values.get(ind, {}):
                    r.setdefault("kind", "measured")
                    r.setdefault("source_id", "gemini_extracted")
                    values.setdefault(ind, {})[area] = r
                    n += 1
        prov["gemini_extracted"] = f"real ({n} values merged)"

    catalog = _read_json(FILES["catalog"]) or {}
    prov["indicators_catalog"] = "real" if catalog else "default (absent)"
    sources = _read_json(FILES["sources"]) or {}
    prov["sources"] = "real" if sources else "default (absent)"

    raw_p = _read_json(FILES["parameters"])
    params = normalise_parameters(raw_p, notes)
    prov["parameters"] = (f"real ({len(params['_real_fields'])} fields mapped: {', '.join(params['_real_fields'])})"
                          if raw_p else "default (absent)")

    raw_i = _read_json(FILES["interventions"])
    if isinstance(raw_i, dict):
        raw_i = raw_i.get("interventions") or list(raw_i.values())
    ivs = [x for x in (normalise_intervention(i) for i in (raw_i or []) if isinstance(i, dict)) if x]
    if ivs:
        prov["interventions"] = f"real ({len(ivs)} usable of {len(raw_i)})"
    else:
        ivs = [normalise_intervention(i) for i in defaults.INTERVENTIONS]
        prov["interventions"] = "default (absent)"

    g3raw = _read_json(FILES["goal3"]) or {}
    goal3 = {}
    for r in (g3raw.get("county") or []) + (g3raw.get("national") or []):
        if r.get("cancer") == "lung" and r.get("sex") == "all" and _num(r.get("value")) is not None:
            goal3[(str(r["area_id"]), r["metric"])] = r
    prov["goal3"] = f"real ({len(goal3)} lung rows)" if goal3 else "absent"
    for k in ("curative_access", "screening"):
        if isinstance((raw_p or {}).get(k), dict):
            params[k] = raw_p[k]

    inp = Inputs(areas=areas, values=values, catalog=catalog, sources=sources, params=params,
                 interventions=ivs, provenance=prov, notes=notes, fingerprint=fp, series=series, gemini=gemini,
                 goal3=goal3, goal3_raw=g3raw)
    _CACHE.update(fp=fp, inp=inp)
    return inp
