"""Sample simulation engine used ONLY when kello_model is not importable.

Deterministic, simple arithmetic over the fixture JSON. Every result carries
"fixture": true. It exists so the UI can be exercised end to end.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
HAZARD_PER_4W = 0.04      # sample assumption
ATTRIBUTABLE = 0.6        # sample assumption
N_RUNS = 2000


@lru_cache(maxsize=None)
def load(name: str):
    return json.loads((FIX / name).read_text())


def interventions():
    return load("interventions.json")


def _iv(iid: str):
    for iv in interventions():
        if iv["id"] == iid:
            return iv
    raise KeyError(iid)


def _area(area_id: str):
    areas = load("areas.json")
    if area_id not in areas:
        raise KeyError(area_id)
    return areas[area_id]


def cost_for(iv: dict, area: dict) -> dict:
    c = iv["cost"]
    pop = area["area"]["pop_total"]
    cases = area["area"]["lung_cases_per_year"]
    k = {"county": 1.0, "per_100k_pop": max(1.0, pop / 100000), "per_patient": float(cases)}[c["scales_with"]]
    setup = c["eur_setup"] * (k if c["scales_with"] == "per_100k_pop" else 1.0)
    return {"eur_setup": round(setup), "eur_per_year": round(c["eur_per_year"] * k)}


def _deaths(days: float, area: dict) -> float:
    return area["area"]["deaths_per_year"] * HAZARD_PER_4W * (days / 28.0) * ATTRIBUTABLE


def simulate(area_id: str, ids: list[str], seed=None) -> dict:
    area = _area(area_id)
    base_steps = [{"id": s["id"], "days": s["days"]["median"], "kind": s["kind"]} for s in area["steps"]]
    cur = {s["id"]: float(s["days"]) for s in base_steps}
    per, tot_lo, tot_hi = [], 0.0, 0.0
    cost = {"eur_setup": 0, "eur_per_year": 0}
    chosen = [i for i in dict.fromkeys(ids)]
    for iid in chosen:
        iv = _iv(iid)
        e, note = iv["effect"], None
        if iid == "ai_cxr_triage" and "ct_capacity" not in chosen:
            saved = lo = hi = 0.0
            note = "No effect without CT capacity: flagged patients join the same queue."
        else:
            room = max(0.0, cur[iv["step"]] - 3.0)
            if e["metric"] == "relative_days":
                saved, lo, hi = (min(room, cur[iv["step"]] * e[k]) for k in ("value", "lo", "hi"))
            else:
                saved, lo, hi = (min(room, float(e[k])) for k in ("value", "lo", "hi"))
            if room < e.get("value", 0) and e["metric"] == "days":
                note = "Capped: this step is already near its floor."
        cur[iv["step"]] -= saved
        tot_lo += lo
        tot_hi += hi
        c = cost_for(iv, area)
        cost["eur_setup"] += c["eur_setup"]
        cost["eur_per_year"] += c["eur_per_year"]
        per.append({"id": iid, "days_saved": round(saved, 1), "deaths_avoided_per_year": round(_deaths(saved, area), 2),
                    "cost": c, "note_en": note})
    saved_total = sum(p["days_saved"] for p in per)
    scen_steps = [{"id": s["id"], "days": round(cur[s["id"]]), "kind": s["kind"]} for s in base_steps]
    base_total = sum(s["days"] for s in base_steps)
    return {
        "baseline": {"total_days": base_total, "steps": base_steps},
        "scenario": {"total_days": sum(s["days"] for s in scen_steps), "steps": scen_steps},
        "days_saved": {"median": round(saved_total), "lo": round(tot_lo * 0.9), "hi": round(max(saved_total, tot_hi * 0.95))},
        "deaths_avoided_per_year": {"median": round(_deaths(saved_total, area), 1), "lo": round(_deaths(tot_lo, area) * 0.6, 1),
                                    "hi": round(_deaths(max(saved_total, tot_hi), area) * 1.4, 1)},
        "cost": cost, "per_intervention": per, "n_runs": N_RUNS, "fixture": True,
    }


def _candidates(scope: str):
    areas = load("areas.json")
    ids = [k for k in areas if k != "FI"] if scope == "FI" else [scope]
    out = []
    for aid in ids:
        area = _area(aid)
        for iv in interventions():
            single = simulate(aid, [iv["id"]])["per_intervention"][0]
            eur = round(single["cost"]["eur_per_year"] + single["cost"]["eur_setup"] / 5)  # per year, set-up spread over 5 years
            out.append({"intervention_id": iv["id"], "area_id": aid, "eur": eur, "days_saved": single["days_saved"],
                        "deaths_avoided_per_year": single["deaths_avoided_per_year"], "confidence": iv["confidence"],
                        "pop": area["area"]["pop_total"]})
    return out


def _pick(cands: list[dict], budget: float):
    chosen, left = [], budget
    pool = sorted(cands, key=lambda c: -(c["deaths_avoided_per_year"] / max(c["eur"], 1)))
    for c in pool:
        if c["deaths_avoided_per_year"] <= 0 or c["eur"] > left:
            continue
        chosen.append(c)
        left -= c["eur"]
    return chosen


def optimize(scope: str, budget_eur: float) -> dict:
    if scope != "FI":
        _area(scope)
    cands = _candidates(scope)
    # ai_cxr_triage gains its effect only alongside ct_capacity in the same county
    chosen = _pick(cands, budget_eur)
    have_ct = {c["area_id"] for c in chosen if c["intervention_id"] == "ct_capacity"}
    spent = sum(c["eur"] for c in chosen)
    for c in cands:
        if c["intervention_id"] == "ai_cxr_triage" and c["area_id"] in have_ct and c["eur"] <= budget_eur - spent:
            area = _area(c["area_id"])
            both = simulate(c["area_id"], ["ct_capacity", "ai_cxr_triage"])["per_intervention"][1]
            if both["days_saved"] > 0 and scope != "FI":
                c = {**c, "days_saved": both["days_saved"], "deaths_avoided_per_year": round(_deaths(both["days_saved"], area), 2)}
                chosen.append(c)
                spent += c["eur"]
    out_chosen = [{"intervention_id": c["intervention_id"], "area_id": c["area_id"], "eur": c["eur"], "days_saved": c["days_saved"],
                   "deaths_avoided_per_year": c["deaths_avoided_per_year"],
                   "eur_per_death_avoided": round(c["eur"] / c["deaths_avoided_per_year"]) if c["deaths_avoided_per_year"] > 0 else None,
                   "confidence": c["confidence"]} for c in chosen]
    deaths = sum(c["deaths_avoided_per_year"] for c in chosen)
    tot_pop = sum({c["area_id"]: c["pop"] for c in cands}.values()) or 1
    by_area: dict[str, float] = {}
    for c in chosen:
        by_area[c["area_id"]] = by_area.get(c["area_id"], 0) + c["days_saved"]
    pops = {c["area_id"]: c["pop"] for c in cands}
    weighted = sum(by_area[a] * pops[a] for a in by_area) / tot_pop
    chosen_ids = {c["intervention_id"] for c in chosen}
    not_chosen = []
    for iv in interventions():
        if iv["id"] in chosen_ids:
            continue
        mine = [c for c in cands if c["intervention_id"] == iv["id"]]
        cheapest = min(c["eur"] for c in mine)
        if iv["id"] == "ai_cxr_triage":
            reason = "AI X-ray triage alone: no effect without CT capacity (LungIMPACT 2026). Fund direct-access CT first."
        elif cheapest > budget_eur:
            reason = f"Costs at least EUR {cheapest:,.0f} a year, more than the whole budget."
        elif cheapest > budget_eur - sum(c["eur"] for c in chosen):
            reason = "Fewer deaths avoided per euro than the chosen actions; the remaining budget does not cover it."
        else:
            reason = "No measurable effect on days in this county."
        not_chosen.append({"intervention_id": iv["id"], "reason_en": reason})
    grid = sorted({250_000, 500_000, 1_000_000, 2_000_000, 3_000_000, 5_000_000, 7_500_000, 10_000_000})
    frontier = [{"budget_eur": b, "deaths_avoided_per_year": round(sum(c["deaths_avoided_per_year"] for c in _pick(cands, b)), 1)} for b in grid]
    return {
        "chosen": out_chosen,
        "totals": {"eur": round(sum(c["eur"] for c in chosen)),
                   "deaths_avoided_per_year": {"median": round(deaths, 1), "lo": round(deaths * 0.45, 1), "hi": round(deaths * 1.6, 1)},
                   "days_saved_weighted": round(weighted, 1)},
        "frontier": frontier, "not_chosen": not_chosen, "fixture": True,
    }
