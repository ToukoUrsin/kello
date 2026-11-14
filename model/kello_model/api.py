"""Public API of the model, in the contract's response shapes (docs/CONTRACT.md, v3).

    care_path(area_id)                    measured: where a county loses patients between diagnosis and curative treatment
    optimize(scope, budget_eur, objective=None, exclude=None)   what closes that gap
    overview() · area(area_id)            the map and one county (care path first, estimated clock second)
    simulate(area_id, interventions)      what a set of measures adds; same evaluator as the optimiser
    early_warning(area_id)

The care path is measured (registry counts). Everything about measures is estimated or assumed and says so.
Interactive calls stay well under 1.5 s: the model is built once per process (about 2 s).
"""
from __future__ import annotations

import json

import numpy as np

from . import carepath, priors
from . import measured as measured_mod
from .engine import GRID, RANGE_EN, Model, q3, span
from .inputs import MODEL, STEPS, STEP_LABEL, fingerprint, load_inputs
from .optimize import BUDGET_BASIS, HANNA_NOTE, OBJECTIVES, Optimizer

N_DRAWS = 2000
_STATE: dict = {}


def get_model() -> Model:
    fp = fingerprint()
    if _STATE.get("fp") != fp:
        m = Model(load_inputs(), n_draws=N_DRAWS)
        cp = carepath.build(m)
        m.set_care_paths(cp["paths"])
        _STATE.clear()
        _STATE.update(fp=fp, model=m, opt=Optimizer(m), plans=None, care=cp)
        b = _STATE["measured"] = measured_mod.build(m)
        _STATE["consistency"] = measured_mod.consistency(m, b)
    return _STATE["model"]


CLOCK_NOTE = ("Secondary view. The symptom-to-treatment clock is estimated, not measured: steps 1-4 are national figures scaled by "
              "public county indicators with assumed effect sizes; only diagnosis to treatment is measured, per collaborative area. "
              "Days saved is not a headline number.")


def _honest(iv):
    """Interval of deaths avoided: keep a negative lower bound and say why."""
    if iv.get("lo", 0) < 0:
        iv["note_en"] = HANNA_NOTE
    return iv


def _plans():
    get_model()
    if _STATE["plans"] is None:
        _STATE["plans"] = {}
        try:
            p = json.loads((MODEL / "plans.json").read_text())
            if p.get("meta", {}).get("fingerprint") == _STATE["fp"]:
                _STATE["plans"] = p.get("plans", {})
        except (OSError, ValueError):
            pass
    return _STATE["plans"]


def meta():
    m = get_model()
    return {"fingerprint": m.inp.fingerprint, "n_draws": m.R,
            "interval": "clock (days): 80% (10th-90th percentile) of the estimate. Measures (patients, deaths): " + RANGE_EN,
            "care_path_interval": "exact binomial 95% interval from the county's own counts; funnel limits 95% and 99.8% around the national share",
            "inputs": m.inp.provenance, "notes": m.notes,
            "incidence_basis": m.N_how, "deaths_basis": m.deaths_how, "population_kind": m.pop_kind,
            "benchmark_floor_en": m.floor_how}


# ------------------------------------------------------------------ care path (measured)
def care_path(area_id):
    """Measured care path of one county (or "FI"): contract shape, straight from the registry's county counts."""
    m = get_model()
    p = _STATE["care"]["paths"].get(area_id)
    if p is None:
        raise KeyError(f"unknown area {area_id}")
    return p


def care_paths():
    """Everything in data/model/care_path.json: every county's path, the national one, and the reference shares."""
    get_model()
    c = _STATE["care"]
    return {"paths": c["paths"], "reference": c["reference"], "stages": c["stages"]}


def _care_summary(area_id):
    """The few care-path numbers the map needs for one county (all measured)."""
    p = _STATE["care"]["paths"].get(area_id) or {}
    cur = next((s for s in p.get("stages") or [] if s["id"] == "curative"), None)
    if not cur:
        return {"curative_share_pct": None, "note_en": p.get("note_en")}
    mp, ex, ml = p.get("missing_patients") or {}, p.get("expected") or {}, p.get("main_leak") or {}
    return {"curative_share_pct": cur["value"], "lo": cur["lo"], "hi": cur["hi"], "n": cur["n"], "national_pct": cur["national"],
            "outside_limits": cur["outside_limits"], "rank": cur["rank"], "of": cur["of"],
            "missing_patients_per_year": mp.get("per_year"), "missing_lo": mp.get("lo"), "missing_hi": mp.get("hi"),
            "main_leak_stage": ml.get("stage_id"), "main_leak_sentence_en": ml.get("sentence_en"),
            "main_leak_sentence_fi": ml.get("sentence_fi"),
            "expected_pct": ex.get("expected_pct"), "observed_vs_expected": ex.get("ratio"),
            "observed_vs_expected_lo": ex.get("lo"), "observed_vs_expected_hi": ex.get("hi"),
            "recording_flag": bool(p.get("artefact_flags")), "period": p.get("period"), "kind": "measured",
            "source_url": cur.get("source_url")}


# ------------------------------------------------------------------ overview
def overview():
    m = get_model()
    B = _STATE["measured"]
    fcp = _STATE["care"]["paths"]["FI"]
    med = np.median(m.total, axis=0)
    order = np.argsort(-med)
    rank = {int(i): r + 1 for r, i in enumerate(order)}
    areas = []
    for i, a in enumerate(m.areas):
        pa = B["per_area"][a["id"]]
        mort, inc = pa.get("lung_mortality_asr"), pa.get("lung_incidence_asr")
        areas.append({
            "care": _care_summary(a["id"]),
            "lung_mortality_asr": mort["value"] if mort else None, "lung_incidence_asr": inc["value"] if inc else None,
            "mortality_vs_incidence": B["mortality_vs_incidence"].get(a["id"]),
            "id": a["id"], "short_en": a.get("short_en"), "short_fi": a.get("short_fi"), "yta": a.get("yta"),
            "total_days": q3(m.total[:, i]), "excess_days_vs_best": round(float(med[i] - med.min()), 1),
            "worst_step": m.worst_step(i), "deaths_per_year": round(float(m.deaths[i]), 1),
            "patients_per_year": round(float(m.N[i]), 1),
            "data_coverage": round(float(m.coverage[i]), 2), "rank": rank[i],
            "has_measured_step": bool(m.measured[i].any()), "kind": "estimated",
            "pre_diagnosis_days": q3(m.days[:, i, :4].sum(1)),
            "measured": B["per_area"][a["id"]],
            "curative_gap_patients_per_year": B["gap"][a["id"]]["value"],
            "curative_gap_note_en": B["gap"][a["id"]]["note_en"],
            "curative_gap": B["gap"][a["id"]]})
    return {
        "headline": {"main_leak": fcp.get("main_leak"), "missing_patients": fcp.get("missing_patients"),
                     "by_county": fcp.get("by_county"), "reference": _STATE["care"]["reference"], "kind": "measured",
                     "note_en": "Measured from Finnish Cancer Registry county counts, patients diagnosed 2019-2023. A difference, not its cause."},
        "clock_note_en": CLOCK_NOTE,
        "national": {
            "care_path": fcp,
            "total_days": q3(m.nat.sum(1)),
            "steps": [{"id": s, "label_en": STEP_LABEL[s], "days": q3(m.nat[:, k]), "kind": m.P["steps"][s].get("kind", "measured"),
                       "level": "national",
                       "source": m.P["steps"][s].get("source"), "url": m.P["steps"][s].get("url"),
                       **({"measured_level": "national", "page": m.P["steps"][s].get("page"), "read_by": m.P["steps"][s].get("read_by"),
                           "period": m.P["steps"][s].get("period")} if s == "treatment" and m.step5 else {})}
                      for k, s in enumerate(STEPS)],
            "total_days_reported": m.total_reported,
            "total_method_en": m.residual_how or "Sum of the national step figures.",
            "headline_measured": B["headline"],
            "measured": B["national"],
            "consistency_check": _STATE["consistency"],
            "benchmarks": [{"country": b["country"], "days": b["days"], "source_id": b.get("source_id")} for b in m.P["benchmarks"]],
            "survival": m.P.get("survival", []),
            "patients_per_year": round(float(m.N.sum())), "deaths_per_year": round(float(m.deaths.sum())),
        },
        "areas": areas,
        "method_en": ("County totals are four estimated steps plus one measured step. Steps 1-4 (first symptom to diagnosis): the national "
                      "figure for each step, scaled by a county factor built from public indicators with assumed (not fitted) effect sizes. "
                      "Step 5 (diagnosis to treatment start) is measured by the Finnish Cancer Registry per collaborative area. "
                      + (m.residual_how or "") + " Rank 1 = longest pathway. Steps 1-4 are estimates with wide intervals, not measurements; "
                      "differences between neighbouring ranks are not meaningful."),
        "measured_note_en": ("`measured` holds values taken straight from public sources, with the national value and the county's rank. "
                             + measured_mod.RANK_NOTE + " curative_gap_patients_per_year is arithmetic, not a causal estimate. "
                             "`care` holds the county's measured care-path summary; lung_mortality_asr and lung_incidence_asr are the "
                             "registry's age-standardised rates per 100,000 (2020-2024). `rank`, `total_days` and `worst_step` belong to "
                             "the estimated clock."),
        "consistency_check": _STATE["consistency"],
        "meta": meta(),
    }


# ------------------------------------------------------------------ area
GAPS = [
    ("Days from referral to first pulmonology visit for suspected lung cancer, by county",
     "The largest controllable wait; today only all-diagnosis queue shares are public.",
     "Wellbeing services counties / THL (Hilmo already holds referral and visit dates)"),
    ("Days from first specialist visit to diagnosis by hospital, and diagnosis to treatment start by county (today: five collaborative areas only)",
     "Without it the model has to estimate where time is lost before diagnosis; the registry already publishes diagnosis to treatment per collaborative area.",
     "University and central hospitals; the national cancer centre (FICAN) quality registers"),
    ("Stage, age and performance status of each county's patients (stage is unknown for 48% nationally), and the curative share by stage",
     "Would separate a gap in care from a difference in who gets ill. Today the adjustment can only use the age of the county's residents.",
     "Finnish Cancer Registry"),
    ("Stereotactic radiotherapy and chemoradiotherapy by county, and the reason when no treatment is on record",
     "The care path can split the missing curative patients into surgery and 'the rest' only by subtraction, and cannot tell an "
     "untreated patient from an unrecorded treatment.",
     "Finnish Cancer Registry; the counties' own records"),
    ("Date of first symptom or first primary care contact for cancer patients",
     "The patient and primary care intervals are the longest part of the pathway and are not recorded anywhere nationally.",
     "Primary care records (Avohilmo) linked to the Cancer Registry by THL / Findata"),
]


def _shown(r):
    """Deaths per 100,000 residents aged 65+ is not shown in any model output: it is not age-standardised. The registry's
    age-standardised rates (measured.lung_mortality_asr, lung_incidence_asr) replace it."""
    return "_deaths_per_100k_65plus" not in r["indicator"]


def area(area_id):
    m = get_model()
    if area_id == "FI":
        ov = overview()["national"]
        return {"area": {"id": "FI", "short_en": "Finland", "short_fi": "Suomi", "patients_per_year": ov["patients_per_year"],
                         "deaths_per_year": ov["deaths_per_year"], "total_days": ov["total_days"]},
                "steps": [{"id": s["id"], "label_en": s["label_en"], "days": s["days"], "national_days": s["days"]["median"],
                           "kind": s["kind"], "method_en": f"National figure: {s['source']}",
                           **({"measured_level": "national"} if s.get("measured_level") else {}),
                           "drivers": ([{"indicator": r["indicator"], "label_en": r["label_en"], "value": r["value"], "national": r["value"],
                                         "unit": "days", "period": r["period"], "source_url": r.get("source_url"), "page": r.get("page"),
                                         "read_by": r.get("read_by"), "quote": r.get("quote"), "kind": "measured", "level": "national"}
                                        for r in m.step5["national"]["rows"].values()] if s["id"] == "treatment" and m.step5 else [])}
                          for s in ov["steps"]],
                "care_path": _STATE["care"]["paths"]["FI"], "clock_note_en": CLOCK_NOTE,
                "measured_gaps": [], "headline_measured": ov["headline_measured"], "measured": ov["measured"],
                "consistency_check": _STATE["consistency"], "total_method_en": ov["total_method_en"],
                "indicators": [r for per in m.inp.values.values() for a, r in per.items() if a == "FI" and _shown(r)],
                "data_gaps": [{"what_en": w, "why_it_matters_en": y, "who_could_publish_en": p} for w, y, p in GAPS],
                "sources": m.inp.sources, "meta": meta()}
    i = m.ix[area_id]
    B = _STATE["measured"]
    a = dict(m.areas[i])
    lam = m.N[i] / 52.0
    steps = m.area_steps(i)
    for st in steps:
        if st["id"] in priors.QUEUE_SHARE:
            wait = priors.QUEUE_SHARE[st["id"]] * st["days"]["median"]
            st["queue"] = {"kind": "estimated", "arrivals_per_week": round(float(lam), 2),
                           "service_rate_per_week": round(float(lam), 2), "wait_days": round(wait, 1),
                           "backlog_patients": round(float(lam * wait / 7), 1),
                           "method_en": ("Standing queue: service rate equals arrivals (backlog neither grows nor shrinks) and "
                                         "backlog / service rate reproduces the estimated wait. Only added capacity shortens it.")}
    a.update(patients_per_year=round(float(m.N[i]), 1), patients_basis=m.N_how, deaths_per_year=round(float(m.deaths[i]), 1),
             deaths_basis=m.deaths_how, deaths_kind="measured", deaths_source_url=getattr(m, "deaths_source_url", None),
             population=round(float(m.pop[i])), population_kind=m.pop_kind,
             curative_share=q3(m.cur[:, i], 3), curative_share_basis=m.cur_kind[i],
             total_days=q3(m.total[:, i]), worst_step=m.worst_step(i), data_coverage=round(float(m.coverage[i]), 2), kind="estimated",
             pre_diagnosis_days=q3(m.days[:, i, :4].sum(1)), curative_gap_patients_per_year=B["gap"][area_id]["value"],
             curative_gap_note_en=B["gap"][area_id]["note_en"])
    inds = sorted((r for per in m.inp.values.values() for aid, r in per.items() if aid == area_id and _shown(r)),
                  key=lambda r: r["indicator"])
    used = {d["indicator"] for st in steps for d in st["drivers"]}
    gaps = [{"what_en": w, "why_it_matters_en": y, "who_could_publish_en": p} for w, y, p in GAPS]
    for (ind, step, *_rest) in priors.ELASTICITIES:
        if ind not in used and m.inp.get(ind, area_id) is None:
            gaps.append({"what_en": f"{ind} for this county", "why_it_matters_en": f"Would narrow the estimate of the {step} step.",
                         "who_could_publish_en": "THL / Statistics Finland / the county"})
    sids = {r.get("source_id") for r in inds}
    return {"area": a, "care_path": _STATE["care"]["paths"].get(area_id), "clock_note_en": CLOCK_NOTE,
            "mortality_vs_incidence": B["mortality_vs_incidence"].get(area_id),
            "steps": steps, "indicators": inds, "data_gaps": gaps,
            "measured": B["per_area"][area_id], "measured_gaps": B["gaps"][area_id],
            "curative_gap": B["gap"][area_id], "consistency_check": _STATE["consistency"],
            "total_method_en": m.residual_how,
            "sources": {k: v for k, v in m.inp.sources.items() if k in sids}, "meta": meta()}


# ------------------------------------------------------------------ simulate
def _steps_block(med):
    return {"total_days": q3(med.sum(1)),
            "steps": [{"id": s, "label_en": STEP_LABEL[s], "days": q3(med[:, k])} for k, s in enumerate(STEPS)], "kind": "estimated"}


def _clock(m, idxs, ids):
    """Estimated clock before and after a set of measures: the county's step estimates (80% interval) times the share of
    each step that remains at the central effect sizes. Same remaining shares as Model.evaluate()."""
    w = m.N[idxs] / m.N[idxs].sum()
    base = scen = 0.0
    for k, i in enumerate(idxs):
        med = m.med_days[i][None, :]
        eff = {j: np.array([m.effect_at(j, 0.0)]) for j in ids}
        rem = m.remaining(ids, med, None, "all", eff=eff, floor=(m.nat_med * m.floor_ratio)[None, :])[0]
        base = base + w[k] * m.days[:, i, :]
        scen = scen + w[k] * m.days[:, i, :] * rem[None, :]
    return base, scen


def _ev(idxs, ids):
    """Model.evaluate for every scenario and area, through the optimiser's cache (same numbers as the plan)."""
    opt, st = _STATE["opt"], frozenset(ids)
    return [[opt.ev(i, st, t) for i in idxs] for t in GRID]


def _spans(m, idxs, ids):
    """Plan-level ranges over the scenario grid for a set of measures in the areas idxs."""
    ev = _ev(idxs, ids)
    n = float(m.N[idxs].sum())
    tot = lambda key, nd=2: span([sum(e[key] for e in row) for row in ev], nd)   # noqa: E731
    dth = tot("deaths")
    if dth["lo"] < 0:
        dth["note_en"] = HANNA_NOTE
    dd = tot("d_delay")
    if dd["lo"] < 0:
        dd["note_en"] = HANNA_NOTE
    return {"curative": tot("curative"), "deaths": dth, "d_delay": dd, "d_other": tot("d_other"), "d_curative": tot("d_curative"),
            "days": span([sum(e["days_saved"] * m.N[i] for e, i in zip(row, idxs)) / n for row in ev], 1)}


def simulate(area_id, interventions, seed=None):
    """What a set of measures adds in one county (or "FI"). Uses the same deterministic evaluator as the optimiser, so the
    same set gives the same numbers in both. `seed` is accepted for compatibility and not used."""
    m = get_model()
    opt = _STATE["opt"]
    unknown = [j for j in interventions if j not in m.iv]
    ids = [j for j in dict.fromkeys(interventions) if j in m.iv]
    fi = area_id == "FI"
    idxs = list(range(m.A)) if fi else [m.ix[area_id]]
    a = None if fi else idxs[0]
    tot = _spans(m, idxs, ids)
    base, scen = _clock(m, idxs, ids)
    setup = run = 0.0
    per, before = [], []
    for j in ids:
        iv = m.iv[j]
        cs = m.cost(j, a)
        setup, run = setup + cs[0], run + cs[1]
        one = _spans(m, idxs, [j])
        before.append(j)
        # what it adds to the measures listed before it (per scenario, then the range)
        ev0, ev1 = _ev(idxs, before[:-1]), _ev(idxs, before)
        add_cur = span([sum(y["curative"] - x["curative"] for x, y in zip(r0, r1)) for r0, r1 in zip(ev0, ev1)], 2)
        add_dth = span([sum(y["deaths"] - x["deaths"] for x, y in zip(r0, r1)) for r0, r1 in zip(ev0, ev1)], 2)
        note = opt.explain(j, a, one["curative"] if iv["metric"] == "curative_share_pp" else None,
                           one["deaths"] if iv["metric"] == "curative_share_pp" else None, where="On its own")
        if iv["mechanism"] == "demand" and one["days"]["median"] < 0.05:
            cap = sorted({c for s in priors.QUEUE_SHARE for c in m.capacity_ids[STEPS.index(s)]})
            note += f" Pair it with capacity ({', '.join(cap) or 'none available'})."
        per.append({"id": j, "name_en": iv.get("name_en", j), "name_fi": iv.get("name_fi"),
                    "days_saved": one["days"], "deaths_avoided_per_year": one["deaths"],
                    "extra_curative_patients_per_year": one["curative"],
                    "added_in_this_set": {"extra_curative_patients_per_year": add_cur, "deaths_avoided_per_year": add_dth,
                                          "note_en": "What it adds to the measures listed before it; these add up to the total."},
                    "cost": {"eur_setup": round(cs[0]), "eur_per_year": round(cs[1]), "eur_annualised": round(cs[2]),
                             "kind": iv["cost"].get("kind", "assumption")},
                    "owner_level": iv.get("owner_level"), "targets_stage": iv.get("targets_stage"),
                    "needs_national_decision": m.is_national(j),
                    "mechanism": iv["mechanism"], "confidence": opt.conf(j), "standalone": True, "note_en": note, "kind": "estimated"})
    return {
        "area_id": area_id, "interventions": ids, "unknown_interventions": unknown,
        "extra_curative_patients_per_year": tot["curative"], "deaths_avoided_per_year": tot["deaths"],
        "deaths_avoided_split": {"from_treatment_access": tot["d_curative"], "from_days_saved": tot["d_delay"],
                                 "from_screening": tot["d_other"],
                                 "note_en": "from_screening also holds the symptom campaign and stop-smoking support (everything that is "
                                            "neither treatment access nor days saved). The parts are ranges of their own and need not add "
                                            "up at the ends."},
        "baseline": _steps_block(base), "scenario": _steps_block(scen), "days_saved": tot["days"],
        "clock_note_en": CLOCK_NOTE,
        "cost": {"eur_setup": round(setup), "eur_per_year": round(run),
                 "eur_annualised": round(setup / priors.ANNUALISE_YEARS + run), "kind": "assumption"},
        "per_intervention": per, "n_runs": m.R, "kind": "estimated", "interval_en": RANGE_EN,
        "note_en": ("per_intervention shows each measure on its own, and under added_in_this_set what it adds to the measures listed "
                    "before it. Together they add less than the sum of the stand-alone numbers: access measures share the reachable part "
                    f"of the county's measured shortfall, measures on the same pathway step overlap (the k-th counts for {priors.DIMINISHING}^k) "
                    "and no step can go below the best Nordic benchmark. Deaths avoided = deaths within 5 years avoided per yearly "
                    "cohort; modelled, not observed. " + RANGE_EN),
    }


# ------------------------------------------------------------------ optimize
def optimize(scope, budget_eur, objective=None, exclude=None):
    """Plan for one county or "FI". objective: "curative" (county default), "gap" (national default) or "deaths".
    exclude: measure ids to leave out (for example one the county already runs)."""
    m = get_model()
    if scope != "FI" and scope not in m.ix:
        raise KeyError(f"unknown scope {scope}")
    if objective in ("", "default"):
        objective = None
    if objective is not None and objective not in OBJECTIVES:
        raise ValueError("objective must be one of " + ", ".join(OBJECTIVES))
    exclude = [j for j in (exclude or []) if j in m.iv]
    if not exclude:
        pre = _plans().get(scope, {}).get(objective or "default", {}).get(str(int(round(float(budget_eur)))))
        if pre:
            return pre
    return _STATE["opt"].optimize(scope, budget_eur, objective, exclude)


# ------------------------------------------------------------------ early warning
def early_warning(area_id=None):
    try:
        rows = json.loads((MODEL / "early_warning.json").read_text())
    except (OSError, ValueError):
        return []
    return [r for r in rows if area_id in (None, r["area_id"])]
