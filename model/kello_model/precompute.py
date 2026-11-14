"""Regenerate everything in data/model/:  nice -n 10 python -m kello_model.precompute

care_path.json measured care path per county and for "FI" (contract shape), reference shares
pathways.json  overview + per-area output + every single measure's effect per area
plans.json     optimiser output for the preset budgets, per area and for "FI":
               plans[scope][objective][budget], objective in default / curative / deaths / gap
early_warning.json  queue forecasts (if the queue series exists)
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):   # one thread per worker process
    os.environ.setdefault(_v, "1")

import json  # noqa: E402
import multiprocessing as mp  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone

from . import api, early_warning
from .inputs import MODEL
from .optimize import BUDGET_BASIS, OBJECTIVES, Optimizer

PRESETS = [100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000]
OBJECTIVE_KEYS = ("default",) + OBJECTIVES     # "default" = curative for a county (deaths where it has no shortfall), gap for FI
IV_FIELDS = ("id", "name_en", "name_fi", "what_en", "what_fi", "step", "steps", "metric", "value", "lo", "hi", "mechanism", "requires",
             "confidence", "cost", "prerequisite_en", "owner_level", "owner_en", "owner_fi", "targets_stage", "modality",
             "first_step_en", "first_step_fi", "kpi")
_OPT: dict = {}


def _single(area_id):
    """Each measure alone in one area (same evaluator as simulate and the optimiser)."""
    m = api.get_model()
    out = {}
    a = None if area_id == "FI" else m.ix[area_id]
    for j in m.iv:
        p = api.simulate(area_id, [j])["per_intervention"][0]
        cs = m.cost(j, a)
        d, c = p["deaths_avoided_per_year"], p["extra_curative_patients_per_year"]
        out[j] = {"days_saved": p["days_saved"], "deaths_avoided_per_year": d, "extra_curative_patients_per_year": c,
                  "cost": {"eur_setup": round(cs[0]), "eur_per_year": round(cs[1]), "eur_annualised": round(cs[2])},
                  "eur_per_death_avoided": round(cs[2] / d["median"]) if d["median"] > 0.005 else None,
                  "eur_per_extra_curative_patient": round(cs[2] / c["median"]) if c["median"] > 0.05 else None,
                  "owner_level": m.iv[j].get("owner_level"), "needs_national_decision": m.is_national(j),
                  "mechanism": m.iv[j]["mechanism"], "confidence": p["confidence"], "kind": "estimated", "note_en": p["note_en"]}
    return area_id, api.area(area_id), out


def _plan(task):
    scope, key = task
    m = api.get_model()
    if "o" not in _OPT:
        _OPT["o"] = Optimizer(m)
    res = {}
    for b in PRESETS:
        res[str(b)] = _OPT["o"].optimize(scope, b, None if key == "default" else key)
    return scope, key, res


def main(procs=None):
    t0 = time.time()
    try:
        os.nice(10)
    except OSError:
        pass
    m = api.get_model()          # built in the parent; workers inherit it by fork
    scopes = m.ids + ["FI"]
    procs = procs or min(os.cpu_count() or 4, 32)
    tasks = [(s, k) for s in scopes for k in OBJECTIVE_KEYS]
    with mp.get_context("fork").Pool(procs) as pool:
        r_single = pool.map_async(_single, scopes, chunksize=1)
        r_plans = pool.map_async(_plan, tasks, chunksize=1)
        singles, plans_l = r_single.get(), r_plans.get()
    meta = {**api.meta(), "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "presets_eur": PRESETS, "objectives": list(OBJECTIVE_KEYS), "budget_basis_en": BUDGET_BASIS}
    MODEL.mkdir(parents=True, exist_ok=True)
    (MODEL / "care_path.json").write_text(json.dumps({"meta": meta, **api.care_paths()}, ensure_ascii=False))
    pathways = {"meta": meta, "overview": api.overview(),
                "areas": {a: ar for a, ar, _ in singles},
                "single_interventions": {a: s for a, _, s in singles},
                "interventions": [{k: iv.get(k) for k in IV_FIELDS} for iv in m.iv.values()]}
    (MODEL / "pathways.json").write_text(json.dumps(pathways, ensure_ascii=False))
    plans = {}
    for scope, key, res in plans_l:
        plans.setdefault(scope, {})[key] = res
    (MODEL / "plans.json").write_text(json.dumps({"meta": meta, "plans": plans}, ensure_ascii=False))
    ew = early_warning.build()
    dt = time.time() - t0
    print(f"precompute done in {dt:.1f}s with {procs} processes; {len(scopes)} scopes, {len(m.iv)} measures, "
          f"{len(OBJECTIVE_KEYS)} objectives x {len(PRESETS)} budgets; care paths: {len(api.care_paths()['paths'])}; early warning: "
          f"{'absent' if ew is None else str(len(ew)) + ' series'}")
    for k, v in m.inp.provenance.items():
        print(f"  input {k}: {v}")
    return dt


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
