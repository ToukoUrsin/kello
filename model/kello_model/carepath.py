"""Measured care path per county: who gets staged, discussed, treated to cure, operated, and who has no
treatment on record. Registry counts only; nothing here is modelled except the `expected` block, which
says so. Shares from counts carry exact binomial intervals (Clopper-Pearson) and funnel limits around the
national share; a county inside the limits differs from the country by no more than chance would give.

Arithmetic and description only: no causal claim is made from county aggregates.
"""
from __future__ import annotations

import json
import math

import numpy as np
from scipy import stats

from . import measured as measured_mod
from .inputs import EVID

REPORT = "keuhkosyoparaportti"          # quality report 2019-2023 (HTML), 12-month follow-up
PDF = "Keuhkosyopa_Suomessa"            # registry report 2018-mid 2022 (PDF), 6-month follow-up
PERIOD = "2019-2023"
PERIOD_PDF = measured_mod.DELAY_PERIOD
UNI_HOSTS = {"90", "05", "08", "13", "19"}   # counties that host a university hospital

LABELS = {
    "staged": ("Stage recorded in the registry", "Levinneisyys kirjattu rekisteriin"),
    "mdt": ("Multidisciplinary meeting (MDT) recorded", "Moniammatillinen kokous (MDT) kirjattu"),
    "curative": ("Treatment that aims to cure", "Parantava hoito"),
    "surgery": ("Operated", "Leikkaushoito"),
    "radiotherapy": ("Any radiotherapy", "Sädehoito"),
    "drug_therapy": ("Drug therapy", "Lääkehoito"),
    "life_prolonging": ("Life-prolonging treatment", "Jarruttava hoito"),
    "symptomatic_only": ("Symptom relief only", "Oireenmukainen hoito"),
    "no_record": ("No treatment on record", "Ei hoitotietoa"),
    "time_to_treatment": ("Days from diagnosis to first treatment", "Päivät diagnoosista hoidon alkuun"),
    "alive_1y": ("Alive 12 months after diagnosis", "Elossa 12 kuukautta diagnoosista"),
}
ORDER = list(LABELS)
COUNT_STAGES = {   # stage -> (Gemini indicator, direction, note)
    "mdt": ("lung_mdt_recorded_pct", "context",
            "A recording measure, not a measure of care: MDT meetings are picked from the hospital discharge register by two procedure "
            "codes (WZC15, WZC20), which most hospitals do not record. A low share says the meeting is not coded, not that it did not happen."),
    "curative": ("lung_curative_intent_pct", "higher_better",
                 "Patients with surgery, stereotactic radiotherapy or chemoradiotherapy within 12 months of diagnosis, of all patients "
                 "diagnosed 2019-2023. Not adjusted for age, stage or other illness."),
    "life_prolonging": ("lung_noncurative_treatment_pct", "context",
                        "Drug therapy or radiotherapy that slows the cancer. Treatment groups overlap: one patient can be in several."),
    "symptomatic_only": ("lung_palliative_treatment_pct", "context", "Palliative care recorded. Treatment groups overlap."),
    "no_record": ("lung_no_treatment_record_pct", "lower_better",
                  "No treatment of any kind found in the registers within 12 months. This mixes patients who were not treated with "
                  "patients whose treatment was not recorded; public data cannot tell them apart."),
}
PAIR_STAGES = {    # stage -> (indicator, direction, note)
    "surgery": ("lung_surgery_pct", "higher_better", ""),
    "radiotherapy": ("lung_radiotherapy_pct", "context",
                     "Any radiotherapy, curative or palliative. Curative (stereotactic) radiotherapy is published for the whole country "
                     "only (11.2% of patients 2019-2023), not by county."),
    "drug_therapy": ("lung_drug_therapy_pct", "context",
                     "Drug treatment is under-recorded in the national registers: only treatment given at a hospital contact is captured."),
}
PAIR_NOTE = ("Age-standardised share within 6 months of diagnosis, {period}; the registry publishes it for men and women separately and the "
             "value shown is the mean of the two (arithmetic on two measured values). A different period and follow-up than the 2019-2023 stages.")
NOT_ADJUSTED = ["stage at diagnosis (unknown for 48% of patients nationally, so it cannot be used)",
                "performance status and other illness", "histology", "how the cancer was found (symptoms, incidental, emergency)",
                "smoking", "treatment given outside the county's own records", "completeness of treatment recording"]


def _tables():
    try:
        return json.loads((EVID / "registry_tables.json").read_text())
    except (OSError, ValueError):
        return {}


def _row(inp, indicator, area, sex="all", period=PERIOD, src=REPORT):
    best = None
    for r in inp.gemini:
        if (r["indicator"] == indicator and r["area_id"] == area and r["sex"] == sex and r["period"] == period
                and src in str(r.get("source_url", ""))):
            if best is None or (r["verified"], r["confidence"]) > (best["verified"], best["confidence"]):
                best = r
    return best


def _counts(row):
    """'Lapin hyvinvointialue | 131 | 710 | 18.5' -> (131, 710). None when the quote does not hold the counts."""
    parts = [p.strip() for p in str(row.get("quote") or "").split("|")]
    try:
        k, n, pct = int(parts[-3]), int(parts[-2]), float(parts[-1].replace(",", "."))
    except (ValueError, IndexError):
        return None
    if n <= 0 or abs(100.0 * k / n - pct) > 0.06 or abs(pct - row["value"]) > 0.06:
        return None
    return k, n


def exact_ci(k, n, level=0.95):
    a = (1 - level) / 2
    lo = 0.0 if k == 0 else stats.beta.ppf(a, k, n - k + 1)
    hi = 1.0 if k == n else stats.beta.ppf(1 - a, k + 1, n - k)
    return 100 * float(lo), 100 * float(hi)


def funnel(p0, n):
    """Limits a county of n patients stays inside with 95% and 99.8% probability if its true share is the national one."""
    q = lambda a: 100 * float(stats.binom.ppf(a, n, p0)) / n
    return {"lo95": q(0.025), "hi95": q(0.975), "lo998": q(0.001), "hi998": q(0.999)}


def _outside(v, lim):
    if v < lim["lo998"] or v > lim["hi998"]:
        return "99.8"
    if v < lim["lo95"] or v > lim["hi95"]:
        return "95"
    return "none"


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


def _fi(x):
    return f"{x:g}".replace(".", ",")


def _i(x):
    return int(round(float(x)))


def _stage(sid, value, unit="%", **kw):
    en, fi = LABELS[sid]
    d = {"id": sid, "label_en": en, "label_fi": fi, "value": _r(value), "unit": unit, "n": None, "lo": None, "hi": None,
         "national": None, "best": None, "best_area": None, "worst": None, "worst_area": None, "rank": None, "of": None,
         "outside_limits": "none", "direction": "context", "level": "county", "kind": "measured", "source_url": None,
         "page": None, "quote": None, "read_by": None, "period": PERIOD, "note_en": ""}
    d.update(kw)
    return d


# ------------------------------------------------------------------ observed vs expected
def _irls(X, y, n, iters=50):
    beta = np.zeros(X.shape[1])
    beta[0] = math.log(y.sum() / (n.sum() - y.sum()))
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ beta)))
        w = n * p * (1 - p)
        z = X @ beta + (y - n * p) / w
        new = np.linalg.solve(X.T @ (w[:, None] * X), X.T @ (w * z))
        if np.abs(new - beta).max() < 1e-10:
            beta = new
            break
        beta = new
    p = 1 / (1 + np.exp(-(X @ beta)))
    cov = np.linalg.inv(X.T @ ((n * p * (1 - p))[:, None] * X))
    phi = float(((y - n * p) ** 2 / (n * p * (1 - p))).sum() / max(len(y) - X.shape[1], 1))
    return beta, cov, max(phi, 1.0), p


def expected_block(m, cur):
    """Quasi-binomial regression of county curative-intent counts on the county's share of residents aged 65+.
    Ecological (county-level) and leave-one-out: each county's expected share comes from a fit on the other counties."""
    ids = [a for a in m.ids if a in cur and m.inp.val("pop_65plus_pct", a) is not None]
    if len(ids) < 10:
        return {}, None
    x = np.array([m.inp.val("pop_65plus_pct", a) for a in ids], float)
    y = np.array([cur[a][0] for a in ids], float)
    n = np.array([cur[a][1] for a in ids], float)
    km = np.array([m.inp.val("km_to_university_hospital", a) or np.nan for a in ids], float)
    xc = x - x.mean()
    X = np.column_stack([np.ones(len(ids)), xc])
    beta, cov, phi, _ = _irls(X, y, n)
    se_b = math.sqrt(cov[1, 1] * phi)
    out, ratios = {}, []
    for i, a in enumerate(ids):
        keep = np.arange(len(ids)) != i
        b, c, ph, _ = _irls(X[keep], y[keep], n[keep])
        eta = float(X[i] @ b)
        pe = 1 / (1 + math.exp(-eta))
        var_exp = (pe * (1 - pe)) ** 2 * float(X[i] @ c @ X[i]) * ph
        obs = y[i] / n[i]
        se_log = math.sqrt(ph * (1 - pe) / (n[i] * pe) + var_exp / pe ** 2)
        ratio = obs / pe
        lo, hi = ratio * math.exp(-1.96 * se_log), ratio * math.exp(1.96 * se_log)
        ratios.append(ratio)
        verdict = "below_expected" if hi < 1 else ("above_expected" if lo > 1 else "as_expected")
        out[a] = {"observed_pct": _r(100 * obs), "expected_pct": _r(100 * pe), "ratio": _r(ratio, 2), "lo": _r(lo, 2), "hi": _r(hi, 2),
                  "verdict": verdict, "pop_65plus_pct": _r(x[i]), "km_to_university_hospital": _r(km[i]),
                  "extra_or_missing_patients_per_year": _r((obs - pe) * float(m.N[m.ix[a]]))}
    ratios = np.array(ratios)
    rho_age = measured_mod.spearman(x, y / n, 5000)
    ok = np.isfinite(km)
    rho_km = measured_mod.spearman(km[ok], (y / n)[ok], 5000)
    rho_km_adj = measured_mod.spearman(km[ok], ratios[ok], 5000)
    common = {
        "method_en": ("Expected share = what a county with this share of residents aged 65 or over would have if it followed the pattern of the "
                      "other 21 counties (quasi-binomial regression of curative-intent counts on the county's 65+ share, fitted without the "
                      "county itself). Ratio = observed / expected; the interval allows for counties varying "
                      f"{phi:.1f} times more than chance alone. This is an ecological adjustment: it uses the age of the county's residents, "
                      "not of its patients, because the registry publishes neither the national share by age nor the age of each county's "
                      "patients. It can remove an age-structure difference between counties; it cannot show why a county differs."),
        "adjusted_for": ["share of county residents aged 65 or over (Statistics Finland, county level)"],
        "not_adjusted_for": NOT_ADJUSTED,
        "kind": "estimated",
        "model": {"odds_ratio_per_pp_65plus": _r(math.exp(beta[1]), 3),
                  "odds_ratio_lo": _r(math.exp(beta[1] - 1.96 * se_b), 3), "odds_ratio_hi": _r(math.exp(beta[1] + 1.96 * se_b), 3),
                  "overdispersion": _r(phi, 1), "n_counties": len(ids),
                  "spearman_curative_vs_65plus": {"rho": _r(rho_age[0], 2), "p": _r(rho_age[1], 3)}},
        "distance_en": (f"Distance to the university hospital is reported, not adjusted away, because distance is part of access to "
                        f"treatment. Across counties the curative share falls with distance (Spearman rho {rho_km[0]:+.2f}, permutation p "
                        f"{rho_km[1]:.3f}); after the 65+ adjustment the link is rho {rho_km_adj[0]:+.2f} (p {rho_km_adj[1]:.2f}). Distance and "
                        "age structure go together in Finland, so 22 counties cannot separate them."),
        "distance": {"rho_unadjusted": _r(rho_km[0], 2), "p_unadjusted": _r(rho_km[1], 3),
                     "rho_after_65plus": _r(rho_km_adj[0], 2), "p_after_65plus": _r(rho_km_adj[1], 3)},
        "why_not_standardised_en": ("Indirect standardisation by age and stage was not possible: the registry's public report gives the "
                                    "curative share for all patients only, not by age group or stage, and stage is unknown for 48% of patients."),
    }
    return out, common


# ------------------------------------------------------------------ build
def build(m):
    inp, T = m.inp, _tables()
    ids = m.ids
    name = {a["id"]: a.get("short_en") or a["id"] for a in m.areas}
    name_fi = {a["id"]: a.get("name_fi") or a.get("short_en") or a["id"] for a in m.areas}

    def in_fi(a):   # "Lapin hyvinvointialueella" where the name allows it, otherwise "Helsinki:"
        n = name_fi[a]
        return n + "ella" if n.endswith("hyvinvointialue") else n + ":"
    yta = {a["id"]: a.get("yta") for a in m.areas}
    html = T.get("html_counts", {})
    t37 = T.get("table_3_7_surgery", {})
    t41 = T.get("table_4_1", {})
    stages = {a: {} for a in ids + ["FI"]}
    counts = {s: {} for s in COUNT_STAGES}

    # --- stages from counts (exact intervals, funnel limits)
    for sid, (ind, direction, note) in COUNT_STAGES.items():
        nat_row = _row(inp, ind, "FI")
        nat_c = _counts(nat_row) if nat_row else None
        if not nat_c:
            continue
        p0 = nat_c[0] / nat_c[1]
        for a in ids + ["FI"]:
            row = _row(inp, ind, a)
            c = _counts(row) if row else None
            if not c:
                continue
            k, n = c
            counts[sid][a] = c
            lo, hi = exact_ci(k, n)
            lim = funnel(p0, n)
            v = 100 * k / n
            h = html.get(sid, {}).get(a)
            agree = bool(h and h[0] == k and h[1] == n)
            st = _stage(sid, v, n=n, count=k, lo=_r(lo), hi=_r(hi), national=_r(100 * p0), direction=direction,
                        source_url=row.get("source_url"), page=row.get("page"), quote=row.get("quote"), read_by=row.get("read_by"),
                        verified=bool(row.get("verified")) or agree, note_en=note,
                        z=_r((v / 100 - p0) / math.sqrt(p0 * (1 - p0) / n), 2),
                        limits={k2: _r(v2) for k2, v2 in lim.items()})
            st["outside_limits"] = "none" if a == "FI" else _outside(v, lim)
            st["side"] = "inside" if st["outside_limits"] == "none" else ("below" if v < 100 * p0 else "above")
            if agree:
                st["cross_check_en"] = "Count and denominator were also parsed from the report's HTML table; the two readings agree."
            stages[a][sid] = st

    # --- stages published by sex (Table 3.7): mean of men and women
    def pair_se(a, sid, v):
        if sid == "surgery" and a in t37.get("men", {}) and a in t37.get("women", {}):
            sm = (t37["men"][a][3] - t37["men"][a][2]) / 3.92
            sw = (t37["women"][a][3] - t37["women"][a][2]) / 3.92
            return math.sqrt(sm ** 2 + sw ** 2) / 2, "from the registry's own 95% confidence intervals for men and women"
        n5 = (counts["curative"].get(a) or (0, 0))[1]
        if not n5:
            return None, None
        return math.sqrt(1.03 * v * (100 - v) / (0.9 * n5)), ("approximate: binomial with the county's 2019-2023 patient count scaled to "
                                                              "4.5 years, because the registry's interval for this row is not loaded")
    for sid, (ind, direction, note) in PAIR_STAGES.items():
        natp = measured_mod.pair(inp, ind, "FI", PERIOD_PDF, "age-standardised")
        for a in ids + ["FI"]:
            p = natp if a == "FI" else measured_mod.pair(inp, ind, a, PERIOD_PDF, "age-standardised")
            if not p:
                continue
            w = measured_mod.pick(inp, ind, a, "women", PERIOD_PDF, "age-standardised")
            row = p["row"]
            pair_note = PAIR_NOTE.format(period=PERIOD_PDF)
            if sid == "surgery":
                pair_note += " The report's age-adjusted comparison for women is not statistically significant; this mean is not a causal or patient-level result."
            st = _stage(sid, p["value"], national=natp["value"] if natp else None, direction=direction, period=PERIOD_PDF,
                        by_sex={"men": p["men"], "women": p["women"]}, source_url=row.get("source_url"),
                        page=f"{row.get('page')}-{w.get('page')}" if w and w.get("page") != row.get("page") else row.get("page"),
                        quote=f"{row.get('quote')} ; {w.get('quote')}" if w else row.get("quote"), read_by=row.get("read_by"),
                        verified=True, note_en=(note + " " if note else "") + pair_note)
            se, how = pair_se(a, sid, p["value"])
            if se and a != "FI" and natp:
                st.update(lo=_r(max(p["value"] - 1.96 * se, 0)), hi=_r(p["value"] + 1.96 * se), z=_r((p["value"] - natp["value"]) / se, 2),
                          limits={"lo95": _r(natp["value"] - 1.96 * se), "hi95": _r(natp["value"] + 1.96 * se),
                                  "lo998": _r(natp["value"] - 3.09 * se), "hi998": _r(natp["value"] + 3.09 * se)},
                          interval_basis_en=f"Interval and limits are {how} (normal approximation).")
                st["outside_limits"] = _outside(p["value"], {k: natp["value"] + f * se for k, f in
                                                             (("lo95", -1.96), ("hi95", 1.96), ("lo998", -3.09), ("hi998", 3.09))})
                st["side"] = "inside" if st["outside_limits"] == "none" else ("below" if p["value"] < natp["value"] else "above")
                if sid == "surgery" and a in t37.get("men", {}):
                    st["registry_ci"] = {s: {"operated_n": t37[s][a][0], "pct": t37[s][a][1], "lo": t37[s][a][2], "hi": t37[s][a][3],
                                             "national_pct": t37["national"][s][1]} for s in ("men", "women")}
                    st["registry_ci_read_by"] = T["_meta"]["table_3_7_surgery"]["read_by"]
            stages[a][sid] = st

    # --- staged (chart read for counties) and alive at 12 months (chart read, by sex)
    nat_unknown = _row(inp, "lung_stage_unknown_pct", "FI")
    for a in ids + ["FI"]:
        row = nat_unknown if a == "FI" else _row(inp, "lung_stage_unknown_pct", a)
        if row:
            chart = row["confidence"] < measured_mod.MIN_CONF
            stages[a]["staged"] = _stage(
                "staged", 100 - row["value"], national=_r(100 - nat_unknown["value"]) if nat_unknown else None,
                source_url=row.get("source_url"), page=row.get("page"), quote=row.get("quote"), read_by=row.get("read_by"),
                confidence=row["confidence"], verified=bool(row.get("verified")),
                note_en=("100 minus the share with no stage information. A recording measure: it says how complete the registry's stage "
                         "data is, not how well patients were staged."
                         + (" Read off a chart, not a table: accurate to about two percentage points, so no interval is given." if chart else "")))
        p = measured_mod.pair(inp, "lung_survival_1y_pct", a, PERIOD, None, strict=False)
        if p and REPORT in str(p["row"].get("source_url", "")):
            natp = measured_mod.pair(inp, "lung_survival_1y_pct", "FI", PERIOD, None, strict=False)
            row = p["row"]
            stages[a]["alive_1y"] = _stage(
                "alive_1y", p["value"], national=natp["value"] if natp else None, direction="higher_better",
                by_sex={"men": p["men"], "women": p["women"]}, source_url=row.get("source_url"), page=row.get("page"),
                quote=row.get("quote"), read_by=row.get("read_by"), confidence=p["confidence"], verified=True,
                note_en=("Age-standardised share alive 12 months after diagnosis; published by sex, the value is the mean of men and women. "
                         + ("Read off a chart, not a table: accurate to about one percentage point, so no interval or limits are given. "
                            if p["confidence"] < measured_mod.MIN_CONF else "")
                         + "Survival follows stage at diagnosis and age as well as treatment."))

    # --- days from diagnosis to first treatment: collaborative area only
    s5 = m.step5
    if s5:
        mix = s5["national"]["mix"]
        tot = sum(mix.values())
        area_val = {}
        for y, rows in s5["yta"].items():
            area_val[y] = sum(rows[k]["value"] * mix[k] for k in rows) / tot
        best_y, worst_y = min(area_val, key=area_val.get), max(area_val, key=area_val.get)
        order = sorted(area_val, key=lambda y: -area_val[y])
        for a in ids:
            y = yta.get(a)
            if y not in area_val:
                continue
            rows = s5["yta"][y]
            r = rows["surgery"]
            bym = {k: {"median_days": rows[k]["value"], "national_median_days": s5["national"]["rows"][k]["value"],
                       "lower_quartile": (t41.get(y, {}).get(k) or [None] * 3)[1], "upper_quartile": (t41.get(y, {}).get(k) or [None] * 3)[2],
                       "quote": rows[k].get("quote"), "page": rows[k].get("page")} for k in rows}
            stages[a]["time_to_treatment"] = _stage(
                "time_to_treatment", area_val[y], unit="days", national=s5["national"]["value"], direction="lower_better",
                level="collaborative_area", kind="estimated", collaborative_area=y, collaborative_area_en=measured_mod.YTA_EN.get(y, y),
                best=_r(area_val[best_y]), best_area=f"yta:{best_y}", worst=_r(area_val[worst_y]), worst_area=f"yta:{worst_y}",
                rank=order.index(y) + 1, of=len(order), by_modality=bym, period=PERIOD_PDF,
                source_url=r.get("source_url"), page=r.get("page"), read_by=r.get("read_by"),
                quote=" ; ".join(str(rows[k].get("quote")) for k in rows),
                note_en=(f"Estimated weighted mix for the {measured_mod.YTA_EN.get(y, y)} university hospital area, not a county value. The registry publishes median days by collaborative area and treatment type only; this is the "
                         f"{measured_mod.YTA_EN.get(y, y)} area's three medians (surgery {rows['surgery']['value']:g}, radiotherapy "
                         f"{rows['radiotherapy']['value']:g}, drug therapy {rows['drug_therapy']['value']:g}) weighted by the national treatment "
                         "mix, so every county in the area shows the same number. Only patients treated within 6 months are counted. "
                         "No interval is published; rank is among the five collaborative areas (1 = longest)."))
        nat = s5["national"]
        stages["FI"]["time_to_treatment"] = _stage(
            "time_to_treatment", nat["value"], unit="days", national=nat["value"], direction="lower_better", level="national",
            period=PERIOD_PDF, source_url=nat["source_url"], page=nat["page"], read_by=nat["read_by"],
            quote=" ; ".join(str(r.get("quote")) for r in nat["rows"].values()),
            note_en="The three national medians (surgery, radiotherapy, drug therapy) weighted by the national treatment mix.")

    # --- ranks, best and worst county per stage
    for sid in ORDER:
        if sid == "time_to_treatment":
            continue
        have = [a for a in ids if sid in stages[a]]
        if not have:
            continue
        direction = stages[have[0]][sid]["direction"]
        v = {a: stages[a][sid]["value"] for a in have}
        worse_first = sorted(have, key=lambda a: v[a] if direction != "lower_better" else -v[a])
        best_a, worst_a = worse_first[-1], worse_first[0]
        for r, a in enumerate(worse_first):
            stages[a][sid].update(rank=r + 1, of=len(have), best=v[best_a], best_area=best_a, best_area_en=name[best_a],
                                  worst=v[worst_a], worst_area=worst_a, worst_area_en=name[worst_a])
        if sid in stages["FI"]:
            stages["FI"][sid].update(best=v[best_a], best_area=best_a, best_area_en=name[best_a], worst=v[worst_a],
                                     worst_area=worst_a, worst_area_en=name[worst_a], of=len(have))

    # --- artefact flags
    flags = {a: [] for a in ids + ["FI"]}
    nat_drug = stages["FI"].get("drug_therapy", {}).get("value")
    for a in ids:
        S = stages[a]
        drug_low = bool(nat_drug and "drug_therapy" in S and S["drug_therapy"]["value"] < 0.2 * nat_drug)
        if drug_low:
            d = S["drug_therapy"]
            flags[a].append({"stage_id": "drug_therapy", "strength": "strong",
                             "text_en": (f"Recorded drug therapy is {d['value']:g}% of patients here against {nat_drug:g}% nationally. No county "
                                         "treats that few: the drug treatments are not reaching the national registers. Read this as a "
                                         "recording gap, not as care."),
                             "text_fi": (f"Lääkehoitoa on kirjattu {_fi(d['value'])} %:lle potilaista, koko maassa {_fi(nat_drug)} %:lle. Näin pieni osuus "
                                         "ei ole uskottava: lääkehoidot eivät päädy valtakunnallisiin rekistereihin. Kyse on kirjaamisesta, "
                                         "ei hoidosta.")})
        nr, lp = S.get("no_record"), S.get("life_prolonging")
        if nr and lp and nr["outside_limits"] == "99.8" and nr["side"] == "above" and lp["outside_limits"] == "99.8" and lp["side"] == "below":
            strong = drug_low or lp["value"] < 0.5 * lp["national"]
            flags[a].append({"stage_id": "no_record", "strength": "strong" if strong else "possible",
                             "text_en": (f"{nr['value']:g}% of patients have no treatment on record (Finland {nr['national']:g}%) while only "
                                         f"{lp['value']:g}% have life-prolonging treatment on record (Finland {lp['national']:g}%). "
                                         + ("That pattern points to treatment that was given but not recorded, not to patients left untreated. "
                                            if strong else
                                            "Part of this is likely treatment that was given but not recorded; public data cannot say how much. ")
                                         + "The curative share may be understated for the same reason. Audit the records before reading it as a gap in care."),
                             "text_fi": (f"{_fi(nr['value'])} %:lla potilaista ei ole hoitotietoa (koko maa {_fi(nr['national'])} %), ja jarruttavaa hoitoa on "
                                         f"kirjattu vain {_fi(lp['value'])} %:lle (koko maa {_fi(lp['national'])} %). "
                                         + ("Tämä viittaa siihen, että hoitoa on annettu mutta sitä ei ole kirjattu. " if strong else
                                            "Osa tästä on todennäköisesti kirjaamatta jäänyttä hoitoa; julkisesta aineistosta ei näe, kuinka suuri osa. ")
                                         + "Myös parantavan hoidon osuus voi samasta syystä näyttää liian pieneltä. Kirjaukset kannattaa tarkistaa ennen johtopäätöksiä.")})
        tt = S.get("time_to_treatment")
        if tt and tt["by_modality"]["surgery"].get("lower_quartile") == 0:
            sm = tt["by_modality"]["surgery"]
            flags[a].append({"stage_id": "time_to_treatment", "strength": "strong",
                             "text_en": (f"The median wait for surgery in the {tt['collaborative_area_en']} area is {sm['median_days']:g} days, but "
                                         "the lower quartile is 0: for at least a quarter of operated patients the cancer was diagnosed at the "
                                         "operation itself. The short median reflects how the diagnosis date is set, not fast care."),
                             "text_fi": (f"Leikkaukseen pääsyn mediaani yhteistyöalueella on {_fi(sm['median_days'])} päivää, mutta alakvartiili on 0: "
                                         "vähintään joka neljännellä leikatulla syöpä todettiin vasta leikkauksessa. Lyhyt mediaani kertoo "
                                         "diagnoosipäivän määrittelystä, ei nopeasta hoidosta.")})
        if "mdt" in S:
            flags[a].append({"stage_id": "mdt", "strength": "strong",
                             "text_en": ("The MDT share counts two procedure codes that most hospitals do not record (6% nationally). "
                                         "It measures coding, not whether cases are discussed."),
                             "text_fi": ("MDT-osuus perustuu kahteen toimenpidekoodiin, joita useimmat sairaalat eivät kirjaa (koko maassa 6 %). "
                                         "Luku kuvaa kirjaamista, ei sitä, käsitelläänkö potilaat kokouksessa.")})

    # --- reference shares
    cur_vals = np.array([stages[a]["curative"]["value"] for a in ids if "curative" in stages[a]], float)
    nat_cur = stages["FI"].get("curative", {}).get("value")
    q75 = float(np.percentile(cur_vals, 75)) if len(cur_vals) else None
    sur_vals = np.array([stages[a]["surgery"]["value"] for a in ids if "surgery" in stages[a]], float)
    nat_sur = stages["FI"].get("surgery", {}).get("value")
    q75_sur = float(np.percentile(sur_vals, 75)) if len(sur_vals) else None
    exp_by, exp_common = expected_block(m, counts["curative"])

    out = {}
    for a in ids:
        S = stages[a]
        n_yr = float(m.N[m.ix[a]])
        cp = {"area_id": a, "area_en": name[a], "area_fi": name_fi[a], "patients_per_year": _r(n_yr), "period": PERIOD,
              "stages": [S[s] for s in ORDER if s in S],
              "rank_note_en": "Rank 1 = the county furthest on the worse side (for context stages: the lowest value).",
              "limits_note_en": ("outside_limits compares the county with the national share: 'none' = inside the range chance alone gives a "
                                 "county of this size 95% of the time; '95' = outside it; '99.8' = outside the range chance gives 998 times "
                                 "in 1,000. Counties differ more than chance on most stages, so being outside the limits shows a real "
                                 "difference, not its cause."),
              "artefact_flags": flags[a]}
        flagged = {f["stage_id"] for f in flags[a]}
        if "curative" not in S:
            cp.update(main_leak=None, missing_patients=None, expected=None, headroom=None,
                      note_en=("The registry does not publish care-path shares for this area: its patients are in the national totals but, "
                               "with 93 patients in five years, not in the area tables."),
                      note_quote="Ahvenanmaan alueen potilaat ovat mukana kokonaisluvuissa, mutta niitä ei esitetä aluekohtaisissa tuloksissa "
                                 "pienten lukumäärien takia (yhteensä 93 tapausta).",
                      note_source_url="https://syoparekisteri.fi/assets/themes/ssy3/factsheets/keuhkosyoparaportti.html")
            out[a] = cp
            continue
        c = S["curative"]
        # main leak: the stage furthest on the worse side of the national value, relative to its limits
        cands = []
        for sid in ("curative", "surgery", "no_record"):
            st = S.get(sid)
            if not st or sid in flagged or st.get("z") is None:
                continue
            bad = -st["z"] if st["direction"] == "higher_better" else st["z"]
            cands.append((bad, sid))
        cands.sort(reverse=True)
        leak = None
        if cands and cands[0][0] > 1.96 and S[cands[0][1]]["outside_limits"] != "none":
            sid = cands[0][1]
            st = S[sid]
            pts = n_yr * abs(st["value"] - st["national"]) / 100
            verb_en = {"curative": "get treatment that aims to cure", "surgery": "are operated",
                       "no_record": "have no treatment on record a year after diagnosis"}[sid]
            verb_fi = {"curative": "saa parantavaan pyrkivää hoitoa", "surgery": "leikataan",
                       "no_record": "on vuoden kuluttua ilman hoitokirjausta"}[sid]
            leak = {"stage_id": sid, "label_en": st["label_en"], "label_fi": st["label_fi"],
                    "sentence_en": (f"Of 100 lung cancer patients in {name[a]}, {_i(st['value'])} {verb_en}. In Finland it is {_i(st['national'])}. "
                                    f"That is about {_i(pts)} patients a year."),
                    "sentence_fi": (f"{in_fi(a)} sadasta keuhkosyöpäpotilaasta {_i(st['value'])} {verb_fi}. Koko Suomessa luku on "
                                    f"{_i(st['national'])}. Ero on noin {_i(pts)} potilasta vuodessa."),
                    "patients_per_year": _r(pts), "value": st["value"], "national": st["national"], "z": st["z"],
                    "outside_limits": st["outside_limits"], "kind": "measured",
                    "basis_en": ("The stage where this county is furthest on the worse side of the national share, measured in units of chance "
                                 "variation for a county of its size. Stages with a recording flag are left out. A measured difference, not its cause.")}
        else:
            below = c["value"] < c["national"]
            leak = {"stage_id": None, "label_en": None, "label_fi": None,
                    "sentence_en": (f"Of 100 lung cancer patients in {name[a]}, {_i(c['value'])} get treatment that aims to cure. In Finland it is "
                                    f"{_i(c['national'])}. " + ("The difference is within what chance alone gives a county of this size."
                                                                 if below or c["outside_limits"] == "none" else
                                                                 "No stage of the care path is below the national level beyond chance.")),
                    "sentence_fi": (f"{in_fi(a)} sadasta keuhkosyöpäpotilaasta {_i(c['value'])} saa parantavaan pyrkivää hoitoa. Koko Suomessa luku on "
                                    f"{_i(c['national'])}. " + ("Ero mahtuu tämän kokoisen alueen satunnaisvaihteluun."
                                                                 if below or c["outside_limits"] == "none" else
                                                                 "Mikään hoitopolun vaihe ei jää koko maan tasosta satunnaisvaihtelua enempää.")),
                    "patients_per_year": 0.0, "kind": "measured"}
        cp["main_leak"] = leak

        # missing patients: arithmetic on the measured share
        def missing(ref, ref_name):
            per = max(0.0, n_yr * (ref - c["value"]) / 100)
            return {"vs": ref_name, "reference_pct": _r(ref), "per_year": _r(per),
                    "lo": _r(max(0.0, n_yr * (ref - c["hi"]) / 100)), "hi": _r(max(0.0, n_yr * (ref - c["lo"]) / 100))}
        mp = missing(nat_cur, "national")
        tq = missing(q75, "top_quartile")

        def split(total, ref_sur):
            s = S.get("surgery")
            if not s or total <= 0:
                return None
            sur = min(total, max(0.0, n_yr * (ref_sur - s["value"]) / 100))
            return sur, total - sur
        bym = []
        sp = split(mp["per_year"], nat_sur)
        if sp:
            bym = [{"id": "surgery", "per_year": _r(sp[0]),
                    "note_en": (f"{n_yr:.0f} patients a year x (national operated share {nat_sur:g}% - this county's {S['surgery']['value']:g}%), "
                                "capped at the total. Operated shares are the registry's age-standardised 6-month figures for 2018-mid 2022 "
                                "(mean of men and women), a different period than the total.")},
                   {"id": "radiotherapy", "per_year": _r(sp[1]),
                    "note_en": ("The rest: total minus the surgery part. Nationally the curative treatments other than surgery are stereotactic "
                                "radiotherapy (11.2% of patients) and chemoradiotherapy (0.9%) in 2019-2023; neither is published by county, so this part "
                                "is by subtraction, not measured. The total curative share is 2019-2023; the surgery comparison above is 2018-mid 2022.")}]
        mp.update(by_modality=bym, top_quartile=tq, kind="measured",
                  split_method_en=("Surgery part from the county's operated share against the national one; the remainder is assigned to curative "
                                   "radiotherapy by subtraction." if bym else
                                   "No split: the county is not below the reference, or its operated share is not published."),
                  note_en=(f"{n_yr:.0f} new patients a year x ({nat_cur:g}% nationally - {c['value']:g}% here) = {mp['per_year']:g} patients a year "
                           f"({mp['lo']:g}-{mp['hi']:g} from the exact 95% interval of the county's share"
                           + ("; floored at 0" if mp["per_year"] == 0 else "") + f"). Against the share reached by the best quarter of counties "
                           f"({q75:.1f}%) it is {tq['per_year']:g} a year. Arithmetic on registry shares, not a causal estimate: counties differ "
                           "in age, stage at diagnosis and other illness, and the registry cannot say which of these patients could have been "
                           "treated to cure." + (" This county carries a recording flag: part of the shortfall may be treatment that was "
                                                 "given but not recorded." if "no_record" in flagged or "drug_therapy" in flagged else "")))
        cp["missing_patients"] = mp
        sp_q = split(tq["per_year"], q75_sur) or (0.0, tq["per_year"])
        cp["headroom"] = {"vs": "top_quartile", "curative_share_pct": c["value"], "top_quartile_pct": _r(q75), "national_pct": nat_cur,
                          "total_per_year": tq["per_year"], "surgery_per_year": _r(sp_q[0]), "radiotherapy_per_year": _r(sp_q[1]),
                          "vs_national_per_year": mp["per_year"], "kind": "measured",
                          "note_en": "Patients a year between this county's curative share and the share of the best quarter of counties."}
        if a in exp_by:
            e = {**exp_common, **exp_by[a]}
            s = S.get("surgery", {}).get("registry_ci")
            if s:
                e["registry_age_standardised_surgery"] = {
                    **s, "note_en": ("The registry's own adjustment, for surgery only: operated share standardised to the age of all Finnish "
                                     "patients (four age groups), by sex, with its 95% confidence interval. Where the interval lies below the "
                                     "national share, age does not explain the county's lower operated share."),
                    "below_national": {k: s[k]["hi"] < s[k]["national_pct"] for k in s}}
            e["sentence_en"] = (f"Observed {e['observed_pct']:g}%, expected {e['expected_pct']:g}% for a county with {e['pop_65plus_pct']:g}% of "
                                f"residents aged 65+: ratio {e['ratio']:g} ({e['lo']:g}-{e['hi']:g}). "
                                + {"below_expected": "Below what the county's age structure predicts.",
                                   "above_expected": "Above what the county's age structure predicts.",
                                   "as_expected": "Within the range the county's age structure predicts."}[e["verdict"]])
            cp["expected"] = e
        else:
            cp["expected"] = None
        out[a] = cp

    # --- national view
    S = stages["FI"]
    rows = []
    for a in ids:
        if out[a].get("missing_patients"):
            c = stages[a]["curative"]
            rows.append({"area_id": a, "area_en": name[a], "curative_pct": c["value"], "lo": c["lo"], "hi": c["hi"], "n": c["n"],
                         "outside_limits": c["outside_limits"], "side": c["side"],
                         "missing_per_year": out[a]["missing_patients"]["per_year"],
                         "missing_vs_top_quartile_per_year": out[a]["missing_patients"]["top_quartile"]["per_year"],
                         "expected_ratio": (out[a]["expected"] or {}).get("ratio"), "expected_verdict": (out[a]["expected"] or {}).get("verdict"),
                         "recording_flag": any(f["stage_id"] in ("no_record", "drug_therapy") for f in flags[a])})
    rows.sort(key=lambda r: -r["missing_per_year"])
    tot_nat = sum(r["missing_per_year"] for r in rows)
    tot_q = sum(r["missing_vs_top_quartile_per_year"] for r in rows)
    below = [r for r in rows if r["side"] == "below"]
    tot_lim = sum(r["missing_per_year"] for r in below)
    fi = {"area_id": "FI", "area_en": "Finland", "area_fi": "Suomi", "patients_per_year": _r(float(m.N.sum())), "period": PERIOD,
          "stages": [S[s] for s in ORDER if s in S], "artefact_flags": [], "expected": exp_common, "by_county": rows}
    if rows and "curative" in S:
        lo_c, hi_c = min(rows, key=lambda r: r["curative_pct"]), max(rows, key=lambda r: r["curative_pct"])
        fi["main_leak"] = {
            "stage_id": "curative", "label_en": LABELS["curative"][0], "label_fi": LABELS["curative"][1],
            "sentence_en": (f"Of 100 lung cancer patients in Finland, {_i(nat_cur)} get treatment that aims to cure. By county it runs from "
                            f"{_i(lo_c['curative_pct'])} in {lo_c['area_en']} to {_i(hi_c['curative_pct'])} in {hi_c['area_en']}. Bringing every "
                            f"county below the national share up to it is about {_i(tot_nat)} patients a year; {_i(tot_lim)} of them are in the "
                            f"{len(below)} counties that are below it by more than chance."),
            "sentence_fi": (f"Suomessa sadasta keuhkosyöpäpotilaasta {_i(nat_cur)} saa parantavaan pyrkivää hoitoa. Alueittain luku vaihtelee "
                            f"{_i(lo_c['curative_pct'])}:stä {_i(hi_c['curative_pct'])}:een. Jos jokainen maan keskiarvon alle jäävä alue nousisi "
                            f"keskiarvoon, se tarkoittaisi noin {_i(tot_nat)} potilasta vuodessa. Heistä {_i(tot_lim)} on niillä {len(below)} alueella, "
                            "jotka jäävät keskiarvosta satunnaisvaihtelua enemmän."),
            "patients_per_year": _r(tot_nat), "kind": "measured"}
        fi["missing_patients"] = {"vs": "national", "per_year": _r(tot_nat), "lo": None, "hi": None, "by_modality": [],
                                  "top_quartile": {"vs": "top_quartile", "reference_pct": _r(q75), "per_year": _r(tot_q)},
                                  "counties_below_national": len([r for r in rows if r["missing_per_year"] > 0]),
                                  "counties_below_limits": len(below), "per_year_in_counties_below_limits": _r(tot_lim),
                                  "counties_below_limits_en": [r["area_en"] for r in below], "kind": "measured",
                                  "note_en": (f"Sum over counties of patients a year x (national share - county share), counties above the national "
                                              f"share counted as 0: {tot_nat:.0f} a year. Against the best quarter of counties ({q75:.1f}%): "
                                              f"{tot_q:.0f} a year. {len(below)} of {len(rows)} counties are below the national share beyond chance; "
                                              f"they account for {tot_lim:.0f} of the {tot_nat:.0f}. "
                                              "Arithmetic, not a causal estimate.")}
    else:
        fi["main_leak"], fi["missing_patients"] = None, None
    out["FI"] = fi
    return {"paths": out, "reference": {"national_curative_pct": nat_cur, "top_quartile_curative_pct": _r(q75),
                                        "national_surgery_pct": nat_sur, "top_quartile_surgery_pct": _r(q75_sur)},
            "counts": counts, "stages": stages}
