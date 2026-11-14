"""Data for the map view: where people live, what a new treatment site would change, what each budget buys,
and the plan played forward year by year.

Everything here is arithmetic on numbers the rest of the app already shows (registry shares, the optimiser's
plan, municipality populations and distances). Each answer carries its `kind` and, where it rests on an
assumption, the sentence that says so.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np

import providers

ROOT = Path(__file__).resolve().parents[2]
PLACES = ROOT / "data" / "processed" / "places.json"

# Yearly cost of a new site. No Finnish public price list exists for these; both are our assumptions and the
# page lets the viewer change them.
SITE_COST = {
    "radiotherapy": (1_500_000, "Assumption: one linear accelerator with its bunker (about EUR 4.5M spread over 12 years), "
                                "yearly service, and a staff of about ten. No public Finnish price exists; change the figure to yours."),
    "full": (5_000_000, "Assumption: a radiotherapy unit plus a chest surgery service (two surgeons, theatre time, intensive care cover). "
                        "No public Finnish price exists; change the figure to yours."),
}
RAMP = (1 / 3, 2 / 3, 1.0)            # share of the plan's full effect reached in 2026, 2027, 2028 (assumption)
YEARS = (2026, 2027, 2028)
BASE_YEAR = 2023                      # the measured share is for 2019-2023; drawn at its last year


def _places() -> dict:
    return providers.memo("stage_places", lambda: json.loads(PLACES.read_text(encoding="utf-8")) if PLACES.exists() else {})


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def _county_rows() -> list[dict]:
    """One row per area with what the map needs; measured values only, straight from the care path."""
    def build():
        pl = _places()
        by_area: dict[str, list[dict]] = {}
        for p in pl.get("places") or []:
            by_area.setdefault(p["area_id"], []).append(p)
        rows = []
        for meta in providers.areas_list():
            aid = meta["id"]
            a = providers.area(aid)
            info, cp = a.get("area") or {}, a.get("care_path") or {}
            st = {s["id"]: s for s in cp.get("stages") or []}
            cur, mp, head, exp = st.get("curative") or {}, cp.get("missing_patients") or {}, cp.get("headroom") or {}, cp.get("expected") or {}
            ps = by_area.get(aid) or []
            w = sum(p["population"] for p in ps)
            seat = max(ps, key=lambda p: p["population"]) if ps else None
            n = info.get("patients_per_year")
            no_rec = (st.get("no_record") or {}).get("value")
            short = mp.get("per_year") or 0
            hidden = None
            if n and no_rec is not None and short > 0:
                _, plausible, extreme = providers.records_estimate(n, no_rec)
                hidden = {"per_year": min(plausible, short), "max_per_year": min(extreme, short)}
            rows.append({
                "area_id": aid, "name_en": info.get("short_en") or meta.get("short_en"), "yta": info.get("yta"),
                "lat": round(sum(p["lat"] * p["population"] for p in ps) / w, 4) if w else None,
                "lon": round(sum(p["lon"] * p["population"] for p in ps) / w, 4) if w else None,
                "population": info.get("population"), "patients_per_year": n,
                "curative_pct": cur.get("value"), "national_pct": cur.get("national"),
                "missing_per_year": short if cp.get("stages") else None, "missing_lo": mp.get("lo"), "missing_hi": mp.get("hi"),
                "best_quarter_pct": head.get("top_quartile_pct"), "missing_vs_best_quarter_per_year": head.get("total_per_year"),
                "surgery_pct": (st.get("surgery") or {}).get("value"), "surgery_national_pct": (st.get("surgery") or {}).get("national"),
                "km": exp.get("km_to_university_hospital"), "pop_65plus_pct": exp.get("pop_65plus_pct"),
                "seat": {k: seat[k] for k in ("id", "name", "lat", "lon")} if seat else None,
                "records": {"flagged": bool(cp.get("artefact_flags")), "hidden_per_year": hidden and hidden["per_year"],
                            "hidden_max_per_year": hidden and hidden["max_per_year"]},
                "too_few": not cp.get("stages"), "kind": "measured",
            })
        return rows
    return providers.memo("stage_counties", build)


def _slopes() -> dict:
    """How the curative share moves with distance across counties: a weighted straight-line fit, with and without
    the share of residents aged 65 or over. A pattern between 22 counties, not a causal estimate."""
    def build():
        rows = [r for r in _county_rows() if r["curative_pct"] is not None and r["km"] is not None and r["pop_65plus_pct"] is not None and r["patients_per_year"]]
        if len(rows) < 8:
            return {}
        y = np.array([r["curative_pct"] for r in rows], float)
        km = np.array([r["km"] for r in rows], float)
        old = np.array([r["pop_65plus_pct"] for r in rows], float)
        w = np.sqrt(np.array([r["patients_per_year"] for r in rows], float))[:, None]

        def fit(x):
            b, *_ = np.linalg.lstsq(x * w, y * w[:, 0], rcond=None)
            return b
        plain = fit(np.c_[np.ones(len(y)), km])
        held = fit(np.c_[np.ones(len(y)), km, old])
        a21 = providers.area(rows[0]["area_id"])
        d = (((a21.get("care_path") or {}).get("expected") or {}).get("distance")) or {}
        return {"n_counties": len(rows), "rho": d.get("rho_unadjusted"), "rho_after_65plus": d.get("rho_after_65plus"),
                "pp_per_100km": round(float(plain[1]) * 100, 1), "pp_per_100km_after_65plus": round(float(held[1]) * 100, 1),
                "note_en": (f"Across {len(rows)} counties the share treated to cure is {abs(plain[1] * 100):.1f} points lower for every 100 km further from "
                            f"a university hospital, and {abs(held[1] * 100):.1f} points once the share of residents aged 65 or over is held fixed "
                            "(straight-line fit weighted by patients). A pattern between counties, not proof that distance is the cause."),
                "kind": "estimated"}
    return providers.memo("stage_slopes", build)


def stage() -> dict:
    pl = _places()
    return {
        "hospitals": pl.get("hospitals") or [], "places": pl.get("places") or [], "counties": _county_rows(), "distance": _slopes(),
        "population_year": pl.get("population_year"),
        "notes": {
            "places_en": pl.get("method_en"),
            "patients_en": ("Lung cancer cases are published by county, not by municipality. Dots for patients are placed by where people live "
                            "inside the county; they are counts, not addresses."),
            "sites_en": ("The starting picture has the five university hospitals. Some central hospitals give radiotherapy too; we found no public "
                         "list with locations, so they are not drawn."),
        },
        "sources": pl.get("sources") or [],
    }


def scenario(sites: list[dict], cost_eur_per_year: float | None = None) -> dict:
    """What a new treatment site would change: distances from where people live, and what the between-county pattern
    then implies for the share treated to cure. Lower bound 0 (distance is not the cause), central value from the fit
    with age held fixed, upper bound from the plain fit."""
    pl, slopes = _places(), _slopes()
    places = pl.get("places") or []
    if not places or not slopes:
        raise KeyError("places")
    placed = []
    for s in sites[:6]:
        kind = s.get("kind") if s.get("kind") in SITE_COST else "radiotherapy"
        near = min(places, key=lambda p: _haversine(float(s["lat"]), float(s["lon"]), p["lat"], p["lon"]))
        cost, basis = SITE_COST[kind]
        placed.append({"lat": near["lat"], "lon": near["lon"], "kind": kind,
                       "place": {"id": near["id"], "name": near["name"], "area_id": near["area_id"]},
                       "cost_eur_per_year": float(cost_eur_per_year) if cost_eur_per_year is not None and len(sites) == 1 else cost,
                       "cost_kind": "assumption", "cost_basis_en": basis})
    road = float(pl.get("road_factor") or 1.3)
    changed, acc = [], {}
    closer = 0
    for p in places:
        after, full_after = p["km"], p["km"]
        for s in placed:
            d = round(_haversine(p["lat"], p["lon"], s["lat"], s["lon"]) * road, 1)
            after = min(after, d)
            if s["kind"] == "full":
                full_after = min(full_after, d)
        a = acc.setdefault(p["area_id"], {"w": 0, "before": 0.0, "after": 0.0, "full": 0.0})
        a["w"] += p["population"]
        a["before"] += p["km"] * p["population"]
        a["after"] += after * p["population"]
        a["full"] += full_after * p["population"]
        if after < p["km"] - 0.05:
            changed.append({"id": p["id"], "km_before": p["km"], "km_after": after})
            closer += p["population"]
    by_id = {r["area_id"]: r for r in _county_rows()}
    b_hi, b_mid = slopes["pp_per_100km"] / 100.0, slopes["pp_per_100km_after_65plus"] / 100.0   # points per km (negative)
    counties, tot = [], {"median": 0.0, "lo": 0.0, "hi": 0.0}
    for aid, a in acc.items():
        r = by_id.get(aid)
        if not r or not a["w"] or a["after"] >= a["before"] - 0.05 * a["w"]:
            continue
        before, after, full = a["before"] / a["w"], a["after"] / a["w"], a["full"] / a["w"]
        row = {"area_id": aid, "name_en": r["name_en"], "km_before": round(before, 1), "km_after": round(after, 1),
               "curative_pct_before": r["curative_pct"]}
        n, cur = r["patients_per_year"], r["curative_pct"]
        if cur is None or not n:
            row.update({"curative_pct_after": None, "extra_per_year": None, "why_en": "Too few patients to say."})
        else:
            # the part of curative treatment that is not surgery moves with any new site; the surgery part only with a full site
            rt_share = 1.0
            if r.get("national_pct") and r.get("surgery_national_pct") is not None:
                rt_share = max(0.0, min(1.0, (r["national_pct"] - r["surgery_national_pct"]) / r["national_pct"]))
            d_any, d_full = before - after, before - full
            eff_km = rt_share * d_any + (1 - rt_share) * d_full
            head = r.get("missing_vs_best_quarter_per_year") or 0.0
            gain = {"median": max(0.0, -b_mid) * eff_km, "lo": 0.0, "hi": max(0.0, -b_hi) * eff_km}       # points
            extra = {k: min(v / 100.0 * n, head) for k, v in gain.items()}
            row["extra_per_year"] = {k: round(v, 1) for k, v in extra.items()}
            row["curative_pct_after"] = {k: round(cur + (v / n * 100.0), 1) for k, v in extra.items()}
            if head <= 0:
                row["why_en"] = "At or above the best quarter of counties: no modelled gain."
            for k in tot:
                tot[k] += extra[k]
        counties.append(row)
    counties.sort(key=lambda c: -(c["km_before"] - c["km_after"]))
    compare = None
    if counties:                                 # the same county's plan, for scale
        try:
            pt = providers.optimize(counties[0]["area_id"], 1_000_000, None, []).get("totals") or {}
            ex = (pt.get("shown") or {}).get("extra")
            if ex:
                compare = {"area_id": counties[0]["area_id"], "name_en": counties[0]["name_en"], "plan_eur_per_year": pt.get("eur"),
                           "plan_extra_per_year": ex, "plan_eur_per_extra_patient": pt.get("eur_per_extra_curative_patient"), "kind": "estimated"}
        except Exception:
            compare = None
    cost = sum(s["cost_eur_per_year"] for s in placed)
    return {
        "sites": placed, "places": changed, "counties": counties,
        "totals": {"people_closer": closer, "extra_per_year": {k: round(v, 1) for k, v in tot.items()}, "cost_eur_per_year": cost,
                   "eur_per_extra_patient": round(cost / tot["median"], -3) if tot["median"] >= 0.05 else None,
                   "eur_per_extra_patient_best_case": round(cost / tot["hi"], -3) if tot["hi"] >= 0.05 else None},
        "compare": compare,
        "assumption_en": (f"Assumption: a county that gets closer to treatment moves along the pattern seen between counties today: "
                          f"{abs(slopes['pp_per_100km_after_65plus']):.1f} points more treated to cure per 100 km closer with age held fixed (central), "
                          f"{abs(slopes['pp_per_100km']):.1f} without (upper), and 0 if distance is not the cause (lower). A radiotherapy unit moves only "
                          "the part of curative treatment that is not surgery. The gain is capped at the county's shortfall to the best quarter of counties. "
                          "Some central hospitals already give radiotherapy and are not in the starting picture."),
        "kind": "assumption",
    }


def budget_curve(scope: str, objective: str | None = None, exclude: list[str] | None = None) -> dict:
    """What each amount of money buys: the optimiser run at many budgets. The curve goes flat where the plan has bought
    everything that adds a patient within the county's reachable shortfall."""
    ex = sorted(set(exclude or []))

    def build():
        top = providers.optimize(scope, 50_000_000, objective, ex)
        order = top.get("chosen") or []
        flat = float((top.get("totals") or {}).get("eur") or 0)
        cum, sums = 0.0, []
        for c in order:
            cum += float(c.get("eur") or 0)
            sums.append(cum)
        hi = max(flat * 1.4, 100_000.0)
        grid = {0.0, hi} | {round(hi * i / 12, -3) for i in range(1, 12)}
        county = len(sums) <= 12
        if county:                                # a county: also every point where one more action fits
            grid |= set(sums) | {max(0.0, s - 1) for s in sums}
        pts, seen_actions, steps = [], set(), []
        for b in sorted(grid):
            o = providers.optimize(scope, b, objective, ex)
            t = o.get("totals") or {}
            e = t.get("extra_curative_patients_per_year") or {}
            ids = [c["intervention_id"] for c in o.get("chosen") or []]
            pts.append({"budget_eur": b, "spent_eur": t.get("eur") or 0, "extra": round(e.get("median") or 0, 2), "lo": round(e.get("lo") or 0, 2),
                        "hi": round(e.get("hi") or 0, 2), "actions": ids if county else [], "n_actions": len(ids)})
            for c in o.get("chosen") or []:
                key = f"{c['intervention_id']}:{c.get('area_id')}"
                if key not in seen_actions:
                    seen_actions.add(key)
                    steps.append({"at_eur": b, "intervention_id": c["intervention_id"], "area_id": c.get("area_id"), "name_en": c.get("name_en"),
                                  "eur": c.get("eur"), "extra": (c.get("shown") or {}).get("extra")})
        tt = top.get("totals") or {}
        return {"scope": scope, "objective": top.get("objective"), "points": pts, "steps": steps if county else [],
                "flat_from_eur": flat, "max_extra": (tt.get("shown") or {}).get("extra"), "shortfall": tt.get("shortfall_vs_national_per_year"),
                "note_en": ("Each point is the optimiser's plan at that budget (modelled). Past the flat point more money buys nothing in the model: "
                            "the limit is the reachable part of the measured shortfall, not money."),
                "kind": "estimated"}
    return providers.memo(("budget_curve", scope, objective, tuple(ex)), build)


def simulate_plan(scope: str, budget_eur: float, exclude: list[str] | None = None, runs: int = 300, seed: int = 1,
                  objective: str | None = None) -> dict:
    """The plan played forward: each simulated year draws how many of the year's patients are treated to cure.
    Shows two things at once: what the plan is modelled to add, and how much one county's yearly share moves by chance alone."""
    o = providers.optimize(scope, budget_eur, objective, sorted(set(exclude or [])))
    t = o.get("totals") or {}
    n = int(round(float(t.get("patients_per_year") or 0)))
    base = t.get("curative_share_now_pct")
    e = t.get("extra_curative_patients_per_year") or {}
    if not n or base is None:
        raise KeyError(scope)
    lo, mid, hi = float(e.get("lo") or 0), float(e.get("median") or 0), float(e.get("hi") or 0)
    runs = max(50, min(int(runs or 300), 1000))
    rng = random.Random(int(seed or 1))
    np_rng = np.random.default_rng(int(seed or 1))
    p0 = base / 100.0
    plan, none = [], []
    for _ in range(runs):
        extra = (rng.uniform(lo, mid) if rng.random() < 0.5 else rng.uniform(mid, hi)) if hi > lo else mid
        plan.append([float(np_rng.binomial(n, min(1.0, p0 + extra * r / n))) / n * 100 for r in RAMP])
        none.append([float(np_rng.binomial(n, p0)) / n * 100 for _ in RAMP])
    pa, na = np.array(plan), np.array(none)
    band = [{"year": BASE_YEAR, **{k: base for k in ("p10", "p50", "p90", "no_plan_p10", "no_plan_p50", "no_plan_p90", "expected")}}]
    for i, y in enumerate(YEARS):
        q, z = np.percentile(pa[:, i], [10, 50, 90]), np.percentile(na[:, i], [10, 50, 90])
        band.append({"year": y, "p10": round(float(q[0]), 1), "p50": round(float(q[1]), 1), "p90": round(float(q[2]), 1),
                     "no_plan_p10": round(float(z[0]), 1), "no_plan_p50": round(float(z[1]), 1), "no_plan_p90": round(float(z[2]), 1),
                     "expected": round(base + mid * RAMP[i] / n * 100, 1)})
    sd = math.sqrt(p0 * (1 - p0) / n) * 100
    above = int(round(float((pa[:, -1] > na[:, -1]).mean()) * 100))
    name = o.get("scope_en") or scope
    nat = (providers.optimize("FI", 0, None, []).get("totals") or {}).get("curative_share_now_pct")
    return {
        "scope": scope, "years": [BASE_YEAR, *YEARS], "baseline_pct": base, "baseline_period": "2019-2023",
        "national_pct": nat,
        "target_pct": t.get("curative_share_after_pct"), "patients_per_year": n, "ramp": [round(r, 2) for r in RAMP], "band": band,
        "runs": [[base, *[round(v, 1) for v in row]] for row in plan[:40]], "runs_total": runs,
        "reached": {"median": round(mid, 1), "lo": round(lo, 1), "hi": round(hi, 1)},
        "plan_above_no_plan_in_100": above,
        "chance_note_en": (f"With {n} patients a year, {name}'s share moves about {sd:.1f} points up or down from one year to the next by chance alone. "
                           f"In {above} of 100 simulated {YEARS[-1]}s the share with the plan is above the share without it. "
                           "That is why the pilot counts decisions reviewed, not the yearly share."),
        "assumptions_en": [
            "The plan reaches a third of its full effect in 2026, two thirds in 2027 and all of it in 2028 (assumption).",
            "Each run draws the plan's effect from its modelled range: half of the runs between the lowest value and the central one, "
            "half between the central one and the highest (our assumption; the range itself is not a probability interval).",
            "Each year's patients are then treated to cure or not at that share, one by one (binomial draw).",
            "The share without the plan stays at the measured 2019-2023 level, drawn on the chart at 2023.",
        ],
        "kind": "estimated",
    }
