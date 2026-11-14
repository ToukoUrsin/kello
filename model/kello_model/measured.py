"""Measured county gaps (no model): registry and statistics values per area, national value, best and
worst county, rank, plus the measured diagnosis -> treatment step and a consistency check of the
estimated clock against measured outcomes. Arithmetic only; nothing here is a causal claim.
"""
from __future__ import annotations

import numpy as np

MIN_CONF = 0.7
DELAY_PERIOD = "1.1.2018-30.6.2022"
MODALITIES = [("surgery", "lung_days_diagnosis_to_surgery", "lung_surgery_pct", "Surgery"),
              ("radiotherapy", "lung_days_diagnosis_to_radiotherapy", "lung_radiotherapy_pct", "Radiotherapy"),
              ("drug_therapy", "lung_days_diagnosis_to_drug_therapy", "lung_drug_therapy_pct", "Drug therapy")]
YTA_EN = {"HUS": "Southern Finland (HUS)", "TYKS": "Western Finland (Tyks)", "TAYS": "Inner Finland (Tays)",
          "KYS": "Eastern Finland (KYS)", "OYS": "Northern Finland (OYS)"}
RANK_NOTE = "Rank 1 = the county furthest on the worse side."


def pick(inp, indicator, area, sex="all", period=None, label=None, strict=True):
    """One Gemini-read row. strict: only verified rows with confidence >= 0.7."""
    best = None
    for r in inp.gemini:
        if r["indicator"] != indicator or r["area_id"] != area or r["sex"] != sex:
            continue
        if period and r["period"] != period:
            continue
        if label and label.lower() not in str(r.get("label_en", "")).lower():
            continue
        if strict and not (r["verified"] and r["confidence"] >= MIN_CONF):
            continue
        if best is None or (r["verified"], r["confidence"]) > (best["verified"], best["confidence"]):
            best = r
    return best


def pair(inp, indicator, area, period, label=None, strict=True):
    """Unweighted mean of the men's and women's value (the reports give county values by sex only)."""
    m = pick(inp, indicator, area, "men", period, label, strict)
    w = pick(inp, indicator, area, "women", period, label, strict)
    if not m or not w:
        return None
    return {"value": round((m["value"] + w["value"]) / 2, 1), "men": m["value"], "women": w["value"], "row": m,
            "confidence": min(m["confidence"], w["confidence"])}


def _ref(r):
    return {"source_url": r.get("source_url"), "page": r.get("page"), "read_by": r.get("read_by"),
            "quote": r.get("quote"), "period": r.get("period")}


# ------------------------------------------------------------------ step 5: diagnosis -> treatment start
def step5(inp, areas):
    """Measured median days from diagnosis to first treatment, by collaborative area and modality (Cancer Registry),
    combined with each county's treatment mix. Returns None when the registry rows are absent."""
    nat_rows = {k: pick(inp, ind, "FI", period=DELAY_PERIOD) for k, ind, _, _ in MODALITIES}
    if not all(nat_rows.values()):
        return None

    def mix(area):
        sh = {k: pair(inp, sind, area, DELAY_PERIOD, "age-standardised") for k, _, sind, _ in MODALITIES}
        return {k: v["value"] for k, v in sh.items()} if all(sh.values()) else None

    nat_mix = mix("FI")
    if nat_mix is None:
        nat_mix = {k: 1.0 for k, *_ in MODALITIES}

    def combine(rows, shares):
        tot = sum(shares.values())
        return sum(rows[k]["value"] * shares[k] for k in rows) / tot

    vals = [r["value"] for r in nat_rows.values()]
    nat_days = combine(nat_rows, nat_mix)
    out = {"national": {"value": round(nat_days, 1), "lo": min(vals), "hi": max(vals), "mix": nat_mix, "rows": nat_rows,
                        "source_url": nat_rows["surgery"].get("source_url"), "page": nat_rows["surgery"].get("page"),
                        "read_by": nat_rows["surgery"].get("read_by"), "period": DELAY_PERIOD},
           "areas": {}, "yta": {}}
    for a in areas:
        yta = a.get("yta")
        rows = {k: pick(inp, ind, f"yta:{yta}", period=DELAY_PERIOD) for k, ind, _, _ in MODALITIES}
        level = "collaborative_area"
        note = None
        if not all(rows.values()):
            rows, level = nat_rows, "national"
            note = ("No collaborative-area figure is published for this area (Åland is outside the five collaborative areas); "
                    "the national medians are used.")
        cm = mix(a["id"])
        mix_level = "county"
        if cm is None:
            cm, mix_level = nat_mix, "national"
        else:
            low = [k for k in cm if cm[k] < 0.4 * nat_mix[k]]
            if low:   # e.g. 0.9% drug therapy against 25% nationally: an incomplete record, not a real treatment mix
                note = ((note + " ") if note else "") + (
                    "The county's recorded share of " + " and ".join(k.replace("_", " ") for k in low) + f" ({', '.join(f'{cm[k]:g}%' for k in low)}) "
                    "is under 40% of the national share, which points to incomplete reporting to the registry rather than a real "
                    "difference in treatment, so the national treatment mix is used as the weights.")
                cm, mix_level = nat_mix, "national"
        days = combine(rows, cm)
        tot = sum(cm.values())
        drivers = []
        for k, ind, sind, lab in MODALITIES:
            r = rows[k]
            drivers.append({"indicator": ind, "label_en": f"{lab}: median days from diagnosis to treatment start",
                            "value": r["value"], "national": nat_rows[k]["value"], "unit": "days", "period": r["period"],
                            "source_url": r.get("source_url"), "page": r.get("page"), "read_by": r.get("read_by"),
                            "quote": r.get("quote"), "kind": "measured", "level": level,
                            "area_measured": r["area_id"], "area_measured_en": YTA_EN.get(yta, "Finland") if level != "national" else "Finland",
                            "weight": round(cm[k] / tot, 3), "weight_basis": f"{mix_level} treatment mix",
                            "treated_share_pct": cm[k]})
        out["areas"][a["id"]] = {"days": round(days, 1), "level": level, "yta": yta, "mix": cm, "mix_level": mix_level,
                                 "drivers": drivers, "note": note, "rows": rows}
        if level == "collaborative_area":
            out["yta"][yta] = rows
    return out


# ------------------------------------------------------------------ measured indicators per county
SPEC = [
    dict(key="curative_intent_pct", indicator="lung_curative_intent_pct", src="ind", unit="%", direction="higher_is_better",
         label_en="Lung cancer patients who got curative-intent treatment", gem=dict(sex="all", period="2019-2023")),
    dict(key="no_treatment_record_pct", indicator="lung_no_treatment_record_pct", src="ind", unit="%", direction="lower_is_better",
         label_en="Lung cancer patients with no treatment on record", gem=dict(sex="all", period="2019-2023")),
    dict(key="one_year_survival_pct", indicator="lung_survival_1y_pct", src="pair", period="2019-2023", unit="%",
         direction="higher_is_better", label_en="One-year survival after lung cancer diagnosis (age-standardised, mean of men and women)",
         strict=False),
    dict(key="surgery_pct", indicator="lung_surgery_pct", src="pair", period=DELAY_PERIOD, label="age-standardised", unit="%",
         direction="higher_is_better", label_en="Lung cancer patients operated within 6 months (age-standardised, mean of men and women)"),
    dict(key="lung_incidence_per_100k", indicator="lung_incidence_per_100k", src="ind", unit="per 100,000", direction="lower_is_better",
         label_en="New lung cancers per 100,000 residents a year (crude)", context=True),
    dict(key="lung_incidence_asr", indicator="incidence_asr", src="goal3", unit="per 100,000 person-years, age-standardised",
         direction="lower_is_better", label_en="New lung cancers per 100,000 person-years, age-standardised (Finnish Cancer Registry)",
         context=True),
    dict(key="lung_mortality_asr", indicator="mortality_asr", src="goal3", unit="per 100,000 person-years, age-standardised",
         direction="lower_is_better", label_en="Lung cancer deaths per 100,000 person-years, age-standardised (Finnish Cancer Registry)"),
    dict(key="gp_wait_over_7d_pct", indicator="primary_care_wait_over_7d_pct", src="ind", unit="%", direction="lower_is_better",
         label_en="Non-urgent GP visits that waited over 7 days"),
    dict(key="pulm_queue_over_90d_pct", indicator="pulmonology_queue_over_90d_pct", src="ind", unit="%", direction="lower_is_better",
         label_en="Pulmonology patients waiting over 90 days (all diagnoses)"),
    dict(key="dx_to_treatment_days", indicator="lung_days_diagnosis_to_treatment", src="step5", unit="days", direction="lower_is_better",
         label_en="Median days from diagnosis to treatment start (collaborative area, weighted by the county's treatment mix)"),
]
SEX_NOTE = ("County values are published by sex only; the value shown is the unweighted mean of the men's and women's figures "
            "(arithmetic on two measured values).")


def _entry(m, sp, area):
    inp = m.inp
    if sp["src"] == "ind":
        r = inp.values.get(sp["indicator"], {}).get(area)
        if not r:
            return None
        e = {"value": round(r["value"], 1), "period": r.get("period"), "source_id": r.get("source_id"),
             "source_url": r.get("source_url") or (inp.sources.get(r.get("source_id")) or {}).get("url"),
             "page": r.get("page"), "read_by": r.get("read_by"), "quote": r.get("quote"), "level": "county"}
        if sp.get("gem"):
            g = pick(inp, sp["indicator"], area, **sp["gem"])
            if g and abs(g["value"] - r["value"]) <= 0.25:
                e.update(page=g.get("page"), read_by=g.get("read_by"), quote=g.get("quote"),
                         source_url=g.get("source_url") or e["source_url"],
                         cross_check_en="The pipeline's value and the value Gemini read from the registry report agree.")
            elif g:
                e["cross_check_en"] = f"Gemini read {g['value']:g} from the registry report (page {g.get('page')}); the pipeline value is shown."
        return e
    if sp["src"] == "pair":
        p = pair(inp, sp["indicator"], area, sp["period"], sp.get("label"), sp.get("strict", True))
        if not p:
            return None
        e = {"value": p["value"], "by_sex": {"men": p["men"], "women": p["women"]}, **_ref(p["row"]), "level": "county",
             "confidence": p["confidence"], "note_en": SEX_NOTE}
        if p["confidence"] < MIN_CONF:
            e["note_en"] += " Read from a chart, not a table (reader confidence %.1f): accurate to about one percentage point." % p["confidence"]
        return e
    if sp["src"] == "goal3":
        r = inp.g3(sp["indicator"], area)
        if not r:
            return None
        return {"value": round(float(r["value"]), 1), "period": r.get("period"), "source_id": r.get("source_id"),
                "source_url": r.get("source_url"), "level": "county" if area != "FI" else "national",
                "note_en": "Age-standardised to the Finnish 2014 population by the registry, so areas with older residents can be compared."}
    s5 = m.step5
    if not s5 or area not in s5["areas"] and area != "FI":
        return None
    if area == "FI":
        n = s5["national"]
        return {"value": n["value"], "period": n["period"], "source_url": n["source_url"], "page": n["page"], "read_by": n["read_by"],
                "level": "national"}
    a = s5["areas"][area]
    if a["level"] != "collaborative_area":
        return None      # no figure is published for this area (Åland): never show the national value as its own
    r = a["rows"]["surgery"]
    return {"value": a["days"], **_ref(r), "level": a["level"],
            "note_en": ("Measured per collaborative area and treatment type, not per county; counties in one collaborative area "
                        "differ only through their treatment mix." + (" " + a["note"] if a["note"] else ""))}


def build(m):
    """All measured blocks, computed once per model."""
    ids = m.ids
    name = {a["id"]: a.get("short_en") for a in m.areas}
    stats, per_area = {}, {a: {} for a in ids}
    for sp in SPEC:
        ent = {a: _entry(m, sp, a) for a in ids}
        have = [a for a in ids if ent[a]]
        nat = _entry(m, sp, "FI")
        if not have:
            for a in ids:
                per_area[a][sp["key"]] = None
            continue
        v = np.array([ent[a]["value"] for a in have], float)
        natv = nat["value"] if nat else round(float(np.average(v, weights=[m.N[m.ix[a]] for a in have])), 1)
        hib = sp["direction"] == "higher_is_better"
        bad = -v if hib else v                      # larger = worse
        order = np.argsort(-bad, kind="stable")
        rank = {have[int(i)]: r + 1 for r, i in enumerate(order)}
        sd = float(v.std()) or 1.0
        best_i, worst_i = int(np.argmin(bad)), int(np.argmax(bad))
        stats[sp["key"]] = {"spec": sp, "national": natv, "national_kind": "measured" if nat else "estimated (patient-weighted mean of counties)",
                            "best": float(v[best_i]), "best_area": have[best_i], "worst": float(v[worst_i]), "worst_area": have[worst_i],
                            "sd": sd, "n": len(have), "q75": float(np.percentile(v, 75)), "q25": float(np.percentile(v, 25)), "nat_entry": nat}
        for a in ids:
            e = ent[a]
            if e:
                e.update(national=natv, rank=rank[a], n_ranked=len(have), unit=sp["unit"], direction=sp["direction"], kind="measured")
            per_area[a][sp["key"]] = e
    # curative gap: arithmetic only
    gap = {}
    st = stats.get("curative_intent_pct")
    for a in ids:
        e = per_area[a].get("curative_intent_pct")
        n = float(m.N[m.ix[a]])
        if not st or not e:
            gap[a] = {"value": None, "note_en": "No county share of curative-intent treatment is published for this area."}
            continue
        g = max(0.0, n * (st["q75"] - e["value"]) / 100.0)
        gap[a] = {"value": round(g, 1), "top_quartile_share_pct": round(st["q75"], 1), "note_en": (
            f"{n:.0f} new patients a year x ({st['q75']:.1f}% - {e['value']:.1f}%) = {g:.1f} patients a year"
            + (" (floored at 0: the county is already at or above that share)" if g == 0 else "")
            + f". {st['q75']:.1f}% is the share reached by the best quarter of counties ({e['period']}); patients = new lung cancers "
            "2019-2023 / 5. Arithmetic on registry shares, not a causal estimate: counties differ in age, stage at diagnosis and other illness.")}
    # headline: the widest measured gaps
    head = []
    s5 = m.step5
    if s5 and s5["yta"]:
        for k, ind, _, lab in MODALITIES[:1] + MODALITIES[1:]:
            vals = {y: rows[k] for y, rows in s5["yta"].items()}
            lo, hi = min(vals, key=lambda y: vals[y]["value"]), max(vals, key=lambda y: vals[y]["value"])
            r = vals[lo]
            head.append({"key": f"dx_to_{k}_days", "label_en": f"Median days from diagnosis to {lab.lower()}",
                         "value_low": vals[lo]["value"], "area_low": f"yta:{lo}", "area_low_en": YTA_EN.get(lo, lo),
                         "value_high": vals[hi]["value"], "area_high": f"yta:{hi}", "area_high_en": YTA_EN.get(hi, hi),
                         "national": s5["national"]["rows"][k]["value"], "unit": "days", "period": r["period"],
                         "source_url": r.get("source_url"), "page": r.get("page"), "read_by": r.get("read_by"),
                         "level": "collaborative_area", "direction": "lower_is_better", "kind": "measured"})
    for key in ("curative_intent_pct", "surgery_pct", "no_treatment_record_pct", "lung_mortality_asr", "gp_wait_over_7d_pct"):
        st = stats.get(key)
        if not st:
            continue
        vals = {a: per_area[a][key] for a in ids if per_area[a][key]}
        if any(e.get("confidence", 1) < MIN_CONF for e in vals.values()):
            continue
        lo, hi = min(vals, key=lambda a: vals[a]["value"]), max(vals, key=lambda a: vals[a]["value"])
        e = vals[lo]
        head.append({"key": key, "label_en": st["spec"]["label_en"], "value_low": vals[lo]["value"], "area_low": lo, "area_low_en": name[lo],
                     "value_high": vals[hi]["value"], "area_high": hi, "area_high_en": name[hi], "national": st["national"],
                     "unit": st["spec"]["unit"], "period": e.get("period"), "source_url": e.get("source_url"), "source_id": e.get("source_id"),
                     "page": e.get("page"), "read_by": e.get("read_by"), "level": "county", "direction": st["spec"]["direction"],
                     "kind": "measured"})
    # per-area gap list, ordered by how far the county is from the national value on the worse side
    gaps = {}
    for a in ids:
        rows = []
        for sp in SPEC:
            e, st = per_area[a].get(sp["key"]), stats.get(sp["key"])
            if not e or not st:
                continue
            hib = sp["direction"] == "higher_is_better"
            diff = e["value"] - st["national"]
            worse = (-diff if hib else diff) / st["sd"]
            side = "same as" if abs(diff) < 0.05 else ("worse than" if worse > 0 else "better than")
            row = {"indicator": sp["key"], "source_indicator": sp["indicator"], "label_en": sp["label_en"], "value": e["value"],
                   "national": st["national"], "national_kind": st["national_kind"], "best": st["best"], "best_area": st["best_area"],
                   "best_area_en": name[st["best_area"]], "worst": st["worst"], "worst_area": st["worst_area"],
                   "worst_area_en": name[st["worst_area"]], "rank": e["rank"], "n_ranked": st["n"], "unit": sp["unit"],
                   "period": e.get("period"), "direction": sp["direction"], "source_url": e.get("source_url"),
                   "source_id": e.get("source_id"), "page": e.get("page"), "quote": e.get("quote"), "read_by": e.get("read_by"),
                   "level": e.get("level"), "kind": "measured", "sd_from_national": round(float(worse), 2),
                   "difference": round(diff, 1), "context_only": bool(sp.get("context")),
                   "note_en": (f"{e['value']:g} here, {st['national']:g} nationally: {side} the national value "
                               f"(rank {e['rank']} of {st['n']}; {RANK_NOTE.lower()} Best county: {name[st['best_area']]}, {st['best']:g}). "
                               + ("Context, not a measure of care: it follows age and smoking history. " if sp.get("context") else "")
                               + (e.get("note_en", "") + " " if e.get("note_en") else "")
                               + "A measured difference between areas, not an explanation of it.")}
            if e.get("confidence") is not None:
                row["confidence"] = e["confidence"]
            if sp["key"] == "curative_intent_pct":
                row["gap_patients_per_year"] = gap[a]["value"]
                row["note_en"] += " Gap in patients: " + gap[a]["note_en"]
            rows.append(row)
        gaps[a] = sorted(rows, key=lambda r: (r["context_only"], -r["sd_from_national"]))
    nat = {k: ({kk: vv for kk, vv in st["nat_entry"].items()} | {"unit": st["spec"]["unit"], "direction": st["spec"]["direction"]}
               if st["nat_entry"] else {"value": st["national"], "kind": st["national_kind"]}) for k, st in stats.items()}
    mvi = {a: mortality_vs_incidence(m, a, name[a]) for a in ids}
    for a in ids:
        e = per_area[a].get("lung_mortality_asr")
        if e and mvi[a]:
            e["note_en"] = mvi[a]["sentence_en"] + " " + e.get("note_en", "")
            for row in gaps[a]:
                if row["indicator"] == "lung_mortality_asr":
                    row["note_en"] = mvi[a]["sentence_en"] + " " + row["note_en"]
    return {"per_area": per_area, "gap": gap, "headline": head, "gaps": gaps, "stats": stats, "national": nat,
            "mortality_vs_incidence": mvi}


def mortality_vs_incidence(m, area, name):
    """Does the area's lung cancer mortality differ from the country by more than its incidence does? Registry
    age-standardised rates only; a description, not a cause."""
    inc, mor = m.inp.g3("incidence_asr", area), m.inp.g3("mortality_asr", area)
    if not inc or not mor or not inc.get("national") or not mor.get("national"):
        return None
    ri, rm = inc["value"] / inc["national"], mor["value"] / mor["national"]
    dn, cn = m.inp.g3("deaths_n", area), m.inp.g3("cases_n", area)
    small = bool(dn and dn["value"] < 150)
    if abs(rm - 1) < 0.05:
        verdict, tail = "same_as_national", "Mortality is close to the national rate."
    elif rm > 1 and ri >= rm - 0.1:
        verdict = "tracks_incidence"
        tail = ("Most of the mortality difference is already there in how many people get lung cancer; it does not by itself show "
                "worse results after diagnosis.")
    elif rm < 1 and ri <= rm + 0.1:
        verdict, tail = "tracks_incidence", "The lower mortality goes with fewer people getting lung cancer here."
    elif rm > ri:
        verdict, tail = "mortality_higher_than_incidence", "Mortality is further above the national rate than incidence is."
    else:
        verdict, tail = "mortality_lower_than_incidence", "Mortality is lower relative to the country than incidence is."
    s = (f"Age-standardised lung cancer mortality in {name} is {rm:.2f} times the national rate ({mor['value']:g} vs {mor['national']:g} per "
         f"100,000, {mor.get('period')}); incidence is {ri:.2f} times ({inc['value']:g} vs {inc['national']:g}). {tail}"
         + (f" Small numbers: {dn['value']:g} deaths in five years, so the rate is uncertain." if small else ""))
    return {"incidence_ratio": round(ri, 2), "mortality_ratio": round(rm, 2), "verdict": verdict, "sentence_en": s, "kind": "measured",
            "small_numbers": small, "deaths_5y": dn["value"] if dn else None, "cases_5y": cn["value"] if cn else None,
            "source_url": mor.get("source_url"), "period": mor.get("period")}


# ------------------------------------------------------------------ consistency check
def _rank(x):
    x = np.asarray(x, float)
    order = np.argsort(x, kind="stable")
    r = np.empty(len(x))
    r[order] = np.arange(1, len(x) + 1)
    for v in np.unique(x):                       # average ranks for ties
        k = x == v
        if k.sum() > 1:
            r[k] = r[k].mean()
    return r


def spearman(x, y, n_perm=20000, seed=1):
    rx, ry = _rank(x), _rank(y)
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(n_perm)])
    return rho, float((np.abs(perm) >= abs(rho) - 1e-12).mean())


CHECKS = [("curative_intent_pct", "share treated with curative intent", -1),
          ("one_year_survival_pct", "one-year survival", -1),
          ("lung_mortality_asr", "age-standardised lung cancer mortality", +1)]


def consistency(m, built):
    pre = np.median(m.days[:, :, :4].sum(2), axis=0)      # estimated days, first symptom -> diagnosis
    res = []
    for key, lab, expect in CHECKS:
        pairs = [(pre[m.ix[a]], built["per_area"][a][key]["value"]) for a in m.ids if built["per_area"][a].get(key)]
        if len(pairs) < 8:
            res.append({"indicator": key, "label_en": lab, "n": len(pairs), "rho": None, "sentence_en": "Too few counties with a value."})
            continue
        x, y = zip(*pairs)
        rho, p = spearman(x, y, 5000)
        want = "negative" if expect < 0 else "positive"
        if abs(rho) < 0.15:
            verdict, s = "none", f"No relationship: counties with a longer estimated wait do not differ in {lab} (rho {rho:+.2f}, n {len(pairs)})."
        elif rho * expect > 0:
            strength = "weakly" if abs(rho) < 0.3 else ("moderately" if abs(rho) < 0.5 else "clearly")
            verdict = "expected_sign"
            s = (f"Expected direction: counties with a longer estimated wait have {'lower' if expect < 0 else 'higher'} {lab}, {strength} "
                 f"(rho {rho:+.2f}, n {len(pairs)}, permutation p {p:.2f}{'; could be chance' if p > 0.05 else ''}).")
        else:
            verdict = "wrong_sign"
            s = (f"Wrong direction: we expected a {want} correlation, the data show rho {rho:+.2f} (n {len(pairs)}, permutation p {p:.2f}). "
                 "The estimated clock does not line up with this outcome.")
        res.append({"indicator": key, "label_en": lab, "n": len(pairs), "rho": round(rho, 2), "p_permutation": round(p, 3),
                    "expected_sign": want, "verdict": verdict, "sentence_en": s})
    ok = sum(r.get("verdict") == "expected_sign" and (r.get("p_permutation") or 1) <= 0.05 for r in res)
    return {"kind": "check", "what_en": ("Spearman rank correlation, across counties, between the estimated days from first symptom to "
                                         "diagnosis (steps 1-4) and three measured outcomes."),
            "results": res,
            "summary_en": (f"{ok} of {len(res)} outcomes correlate with the estimated clock in the expected direction beyond chance. "
                           "This is a check, not a validation: it is county-level, with about 22 points, and confounded by age, smoking "
                           "and stage at diagnosis. The priors were not tuned to improve it."),
            "caveat_en": "A check, not a validation; county-level, confounded by age, smoking and stage."}
