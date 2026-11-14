"""First-screen data: the Goal 3 scoreboard and the county funnel plot.

Both are measured values only. goal3() cuts data/processed/goal3.json (2 MB) down to what the UI draws;
funnel() works from the county counts Gemini read out of the registry's lung cancer report
(lung_patients_n and lung_curative_intent_n, 2019-2023, all sexes) and adds exact binomial limits.
"""
from __future__ import annotations

import math
from pathlib import Path

import measured as measured_mod
import providers

DATA = Path(__file__).resolve().parents[2] / "data"
CANCERS = ("lung", "pancreas", "liver", "all")
ASR = ("incidence_asr", "mortality_asr")


# ---- Goal 3 ---------------------------------------------------------------------

def goal3() -> dict:
    return providers.memo("goal3", _goal3)


def _goal3() -> dict:
    g = providers._read(DATA / "processed/goal3.json")
    if not isinstance(g, dict):
        raise FileNotFoundError("data/processed/goal3.json")
    reg = providers._read(DATA / "processed/sources.json") or {}

    def src(sid):
        r = reg.get(sid) or {}
        return {"source_id": sid, "title": r.get("title"), "publisher": r.get("publisher"), "url": r.get("url"), "retrieved_at": r.get("retrieved_at")}

    keep = ("cancer", "sex", "finland", "sweden", "norway", "benchmark", "gap_pp", "gap_lo", "gap_hi", "lag_years",
            "gap_change_pp_per_decade", "strategy_target_pp", "period", "source_id", "source_url", "kind", "derived", "verified")
    survival = [{k: r.get(k) for k in keep} for r in g.get("survival_targets") or []]
    method = next((r.get("method_en") for r in g.get("survival_targets") or [] if r.get("method_en")), None)

    mt = g.get("mortality_trend") or {}
    mort = {k: mt.get(k) for k in ("indicator", "unit", "baseline_year", "baseline_year_stated_in_strategy", "target_pct", "baseline_value",
                                   "baseline_deaths_n", "target_value", "target_deaths_n", "latest", "change_since_baseline_pct",
                                   "deaths_change_since_baseline_pct", "last_10_years", "source_id", "source_url", "kind", "strategy_quote_fi", "note_en")}
    mort["series"] = [{"year": p.get("year"), "value": p.get("value")} for p in mt.get("series") or []]
    try:
        # what is left of the target, in the same unit as the target (per cent of the baseline rate)
        mort["remaining_pct"] = round(mt["target_pct"] - mt["change_since_baseline_pct"], 1)
        mort["target_year"] = 2035
    except (KeyError, TypeError):
        pass

    rows, meta = [], {}
    for r in g.get("county") or []:
        if r.get("sex") != "all" or r.get("metric") not in ASR or r.get("cancer") not in CANCERS:
            continue
        row = {"area_id": r["area_id"], "cancer": r["cancer"], "metric": r["metric"], "value": r.get("value"), "national": r.get("national"), "n": r.get("n")}
        if r.get("small_n"):
            row["small_n"] = True
            row["note"] = r.get("note")
        rows.append(row)
        meta.setdefault(r["metric"], {"period": r.get("period"), "unit": r.get("unit"), "source_id": r.get("source_id"), "source_url": r.get("source_url"),
                                      "source_title": (reg.get(r.get("source_id")) or {}).get("title")})
    tw = g.get("treated_within_target") or {}
    notes = [n for n in g.get("notes_en") or [] if n.startswith(("Mortality is not", "Small numbers", "Site definitions", "Survival targets use"))]
    return {
        "generated_at": g.get("generated_at"),
        "survival_targets": survival, "survival_method_en": method,
        "survival_sex_note_en": "NORDCAN publishes survival for men and women separately, with no both-sexes figure, so both are shown.",
        "mortality_trend": mort,
        "county": {"metrics": meta, "rows": rows, "cancers": list(CANCERS)},
        "treated_within_target": {k: tw.get(k) for k in ("available", "indicator_en", "target_en", "data_gap_en", "who_could_publish_en", "kind")},
        "sources": {sid: src(sid) for sid in {r.get("source_id") for r in survival} | {mort.get("source_id")} | {m.get("source_id") for m in meta.values()} if sid},
        "notes_en": notes,
    }


# ---- funnel plot ------------------------------------------------------------------

def _logpmf(k: int, n: int, p: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def _cdf_table(n: int, p: float) -> list[float]:
    acc, out = 0.0, []
    for k in range(n + 1):
        acc += math.exp(_logpmf(k, n, p))
        out.append(min(acc, 1.0))
    return out


def _limits(n: int, p: float, alpha: float) -> tuple[int, int, float]:
    """Smallest k with P(X<=k) >= alpha/2 and with P(X<=k) >= 1-alpha/2 (binomial quantiles), and the chance of landing outside them."""
    cdf = _cdf_table(n, p)
    lo = next(k for k, c in enumerate(cdf) if c >= alpha / 2)
    hi = next(k for k, c in enumerate(cdf) if c >= 1 - alpha / 2)
    outside = (cdf[lo - 1] if lo > 0 else 0.0) + (1.0 - cdf[hi])
    return lo, hi, outside


def _cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    return min(1.0, sum(math.exp(_logpmf(i, n, p)) for i in range(k + 1)))


def _exact_interval(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Clopper-Pearson interval for a share, by bisection on the binomial tail."""
    def solve(f, lo, hi):
        for _ in range(48):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda q: 1 - _cdf(k - 1, n, q) < alpha / 2, 0.0, k / n)
    upper = 1.0 if k == n else solve(lambda q: _cdf(k, n, q) > alpha / 2, k / n, 1.0)
    return lower, upper


def funnel() -> dict:
    return providers.memo("funnel", _funnel)


def _funnel() -> dict:
    d = measured_mod.data()
    period = "2019-2023"

    def table(ind):
        return {r["area_id"]: r for r in d["rows"] if r.get("indicator") == ind and r.get("period") == period and (r.get("sex") or "all") == "all"
                and isinstance(r.get("value"), (int, float))}
    N, K = table("lung_patients_n"), table("lung_curative_intent_n")
    if "FI" not in N or "FI" not in K:
        raise FileNotFoundError("national lung_patients_n / lung_curative_intent_n rows")
    n_fi, k_fi = int(N["FI"]["value"]), int(K["FI"]["value"])
    p = k_fi / n_fi
    names = {a["id"]: a for a in d["areas"]}
    areas = []
    exp95 = exp998 = 0.0
    for aid in sorted(N):
        if aid == "FI" or aid.startswith("yta:") or aid not in K:
            continue
        n, k = int(N[aid]["value"]), int(K[aid]["value"])
        lo95, hi95, out95 = _limits(n, p, 0.05)
        lo998, hi998, out998 = _limits(n, p, 0.002)
        exp95 += out95
        exp998 += out998
        outside = "99.8" if (k < lo998 or k > hi998) else "95" if (k < lo95 or k > hi95) else "none"
        ci = _exact_interval(k, n)
        a = names.get(aid, {})
        areas.append({"id": aid, "short_en": a.get("short_en") or aid, "short_fi": a.get("short_fi"), "n": n, "k": k, "pct": round(100 * k / n, 1),
                      "lo": round(100 * ci[0], 1), "hi": round(100 * ci[1], 1), "outside": outside,
                      "side": "none" if outside == "none" else ("below" if k / n < p else "above"),
                      "patients_per_year": round(n / 5, 1), "page": K[aid].get("page"), "quote": K[aid].get("quote")})
        # The model's recording flags on this county's care path: where they touch treatment records, the share may be understated.
        try:
            flags = [f for f in ((providers.area(aid).get("care_path") or {}).get("artefact_flags") or [])
                     if f.get("stage_id") in ("no_record", "drug_therapy") and f.get("text_en")]
        except Exception:  # noqa: BLE001
            flags = []
        if flags:
            areas[-1]["recording_flag"] = {"stages": [f["stage_id"] for f in flags], "strength": "strong" if any(f.get("strength") == "strong" for f in flags) else "possible",
                                           "text_en": " ".join(f["text_en"] for f in flags)}
    ns =[a["n"] for a in areas]
    lo_n, hi_n = max(20, int(min(ns) * 0.75)), int(max(ns) * 1.06)
    grid = sorted({int(round(lo_n * (hi_n / lo_n) ** (i / 59))) for i in range(60)})
    limits = []
    for n in grid:
        l95, h95, _ = _limits(n, p, 0.05)
        l998, h998, _ = _limits(n, p, 0.002)
        limits.append({"n": n, "lo95": round(100 * l95 / n, 2), "hi95": round(100 * h95 / n, 2), "lo998": round(100 * l998 / n, 2), "hi998": round(100 * h998 / n, 2)})
    out95 = [a for a in areas if a["outside"] != "none"]
    out998 = [a for a in areas if a["outside"] == "99.8"]
    low = min(areas, key=lambda a: a["k"] / a["n"])
    high = max(areas, key=lambda a: a["k"] / a["n"])
    rec = K["FI"]
    return {
        "indicator": "lung_curative_intent_pct", "label_en": "Share of lung cancer patients given treatment that aims to cure",
        # wording follows data/processed/indicators_catalog.json (lung_curative_intent_pct), not memory
        "definition_en": ("Curative-intent treatment: the Finnish Cancer Registry's treatment category 'Parantava', the first-line treatment within 12 months "
                          f"of diagnosis, from the hospital care register (Hilmo), by county of residence. Patients diagnosed {period}. "
                          "Crude share, not adjusted for age or stage."),
        "period": period, "kind": "measured", "sex": "all",
        "national": {"n": n_fi, "k": k_fi, "pct": round(100 * p, 2)},
        "areas": areas, "limits": limits,
        "n_areas": len(areas),
        "expected_outside_95": round(exp95, 2), "observed_outside_95": len(out95),
        "expected_outside_998": round(exp998, 3), "observed_outside_998": len(out998),
        "below_95": [a["id"] for a in out95 if a["side"] == "below"], "above_95": [a["id"] for a in out95 if a["side"] == "above"],
        "lowest": {"id": low["id"], "short_en": low["short_en"], "n": low["n"], "k": low["k"], "per_100": round(100 * low["k"] / low["n"])},
        "highest": {"id": high["id"], "short_en": high["short_en"], "n": high["n"], "k": high["k"], "per_100": round(100 * high["k"] / high["n"])},
        "method_en": ("Limits are exact binomial quantiles around the national share for each number of patients (95% and 99.8%). "
                      "Each county's own interval is the exact (Clopper-Pearson) 95% interval of its share. "
                      "Expected number outside by chance = sum over counties of the probability of falling outside its limits at the national share."),
        "not_adjusted_en": "Not adjusted for stage, age or other illness: the registry does not publish those by county. The plot shows where to look, not why.",
        "missing": [a["short_en"] for a in d["areas"] if a["id"] not in {x["id"] for x in areas}],
        "source_url": rec.get("source_url"), "source_id": "fcr_lung_quality_report", "page": rec.get("page"), "read_by": rec.get("read_by"),
        "quote": rec.get("quote"),
    }
