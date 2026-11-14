"""Sotkanet (THL) indicators per wellbeing services county, latest 5 years with data."""
from __future__ import annotations

import json

from common import Out, fetch, FetchError

BASE = "https://sotkanet.fi/rest/1.1"
YEARS = list(range(2015, 2027))
KEEP_YEARS = 5

# sotkanet id -> (key, unit, direction, pathway step, short English label)
IND = {
    6411: ("primary_care_wait_over_7d_pct", "%", "higher_is_worse", "primary",
           "Non-urgent GP visits with a wait over 7 days from assessment of need"),
    2676: ("primary_care_wait_over_7d_pct_march", "%", "higher_is_worse", "primary",
           "Non-urgent GP visits with a wait over 7 days (March snapshot, older series)"),
    6410: ("primary_care_wait_over_3m_pct", "%", "higher_is_worse", "primary",
           "Non-urgent GP visits with a wait over 3 months"),
    3176: ("primary_care_wait_over_3m_pct_oct", "%", "higher_is_worse", "primary",
           "Non-urgent GP visits with a wait over 3 months (October snapshot, older series)"),
    6412: ("nurse_wait_over_7d_pct", "%", "higher_is_worse", "primary",
           "Non-urgent nurse visits with a wait over 7 days"),
    5499: ("nurse_wait_over_7d_pct_oct", "%", "higher_is_worse", "primary",
           "Non-urgent nurse visits with a wait over 7 days (October snapshot, older series)"),
    3892: ("gp_vacancy_pct", "%", "higher_is_worse", "primary",
           "Unfilled health-centre physician posts, share of all posts"),
    4123: ("primary_care_doctor_visits_per_1000", "per 1,000", "context", "primary",
           "Primary care outpatient physician visits per 1,000 inhabitants"),
    5502: ("continuity_of_care_coci", "index", "higher_is_better", "primary",
           "Continuity of care (COCI) in primary care physician visits"),
    4263: ("forgone_care_due_to_money_pct", "%", "higher_is_worse", "patient",
           "Had to cut back on food, medicines or doctor visits for lack of money"),
    3055: ("specialist_arrivals_without_referral_pct", "%", "context", "referral",
           "Arrived at specialist care without a referral"),
    5033: ("referrals_handled_over_21d_pct", "%", "higher_is_worse", "referral",
           "Referrals to specialist care processed in more than 21 days (all specialties)"),
    13: ("referrals_handled_within_3d_pct", "%", "higher_is_better", "referral",
         "Referrals to specialist care processed within 3 days (all specialties)"),
    5073: ("referrals_per_1000", "per 1,000", "context", "referral",
           "Referrals received by specialist care per 1,000 inhabitants"),
    5083: ("specialist_wait_median_days", "days", "higher_is_worse", "referral",
           "Median waiting time of those waiting for specialist care on 31 Dec (all specialties)"),
    3336: ("specialist_wait_over_6m_per_10k", "per 10,000", "higher_is_worse", "referral",
           "Waited over 6 months for specialist care, per 10,000 inhabitants"),
    2478: ("pulmonology_outpatient_visits", "visits", "context", "diagnosis",
           "Specialist outpatient visits, pulmonary diseases"),
    2475: ("oncology_outpatient_visits", "visits", "context", "treatment",
           "Specialist outpatient visits, oncology and radiotherapy"),
    5093: ("cancer_drug_reimbursement_index", "index", "context", "treatment",
           "Entitled to special reimbursement for cancer medicines (age-standardised)"),
    3621: ("breast_screening_participation_pct", "%", "higher_is_better", "patient",
           "Breast cancer screening participation"),
    3620: ("cervical_screening_participation_pct", "%", "higher_is_better", "patient",
           "Cervical cancer screening participation"),
    6103: ("crc_screening_participation_pct", "%", "higher_is_better", "patient",
           "Colorectal cancer screening participation"),
    3625: ("breast_5y_survival_pct", "%", "higher_is_better", "outcome", "Breast cancer 5-year relative survival"),
    3626: ("cervix_5y_survival_pct", "%", "higher_is_better", "outcome", "Cervical cancer 5-year relative survival"),
    3627: ("colon_5y_survival_pct", "%", "higher_is_better", "outcome", "Colon cancer 5-year relative survival"),
    4404: ("daily_smokers_pct", "%", "higher_is_worse", "patient", "Daily smokers, adults"),
    4406: ("daily_smokers_65plus_pct", "%", "higher_is_worse", "patient", "Daily smokers, aged 65+"),
    4408: ("daily_smokers_low_education_pct", "%", "higher_is_worse", "patient",
           "Daily smokers, low education"),
    180: ("education_level_index", "index", "context", "patient", "Measure of educational level"),
    3099: ("low_income_rate_pct", "%", "context", "patient", "At-risk-of-poverty rate"),
    749: ("pop_65plus_pct_2030_proj", "%", "context", None, "Population aged 65+, % of population, projection 2030"),
    760: ("pop_65plus_pct_2040_proj", "%", "context", None, "Population aged 65+, % of population, projection 2040"),
    5643: ("cancer_index_age_std", "index (FI=100)", "context", "outcome", "THL cancer morbidity index, age-standardised"),
    5657: ("lung_disease_index_age_std", "index (FI=100)", "context", "patient",
           "THL chronic lung disease morbidity index, age-standardised"),
    4193: ("lung_disease_pyll_per_100k", "per 100,000", "higher_is_worse", "outcome",
           "Potential years of life lost (ages 25-80) due to lung diseases per 100,000"),
    3138: ("pyll_per_100k", "per 100,000", "higher_is_worse", "outcome",
           "Potential years of life lost (ages 0-80) per 100,000"),
    5047: ("copd_hospitalisations_per_100k", "per 100,000", "higher_is_worse", "patient",
           "Hospital inpatient periods for COPD, age 15+, per 100,000, standardised"),
    5018: ("copd_share_of_gp_visit_reasons_pct", "%", "context", "primary",
           "COPD as reason for primary care physician visit, % of recorded reasons"),
    5085: ("asthma_copd_reimbursement_pct", "%", "context", "patient",
           "Entitled to special reimbursement for asthma/COPD medicines"),
}


def run() -> Out:
    out = Out("p01_sotkanet")
    raw, ts = fetch(f"{BASE}/regions", "sotkanet", "regions.json")
    region_map = {}
    for r in json.loads(raw):
        if r["category"] == "HYVINVOINTIALUE":
            region_map[r["id"]] = r["code"]
        elif r["category"] == "MAA":
            region_map[r["id"]] = "FI"
    # university hospital collaborative areas (YTA) as published in the Sotkanet region tree
    yta_names = {r["id"]: r["title"]["fi"] for r in json.loads(raw) if r["category"] == "YTA"}
    out.extra["yta_by_area"] = {
        r["code"]: [yta_names[m] for m in r.get("memberOf", []) if m in yta_names]
        for r in json.loads(raw) if r["category"] == "HYVINVOINTIALUE"}
    out.source("sotkanet_regions", title="Sotkanet region classification", publisher="THL (Finnish Institute for Health and Welfare)",
               url=f"{BASE}/regions", api_call=f"GET {BASE}/regions", retrieved_at=ts, licence="CC BY 4.0",
               notes="Used to map Sotkanet region ids to wellbeing services county codes and to verify the collaborative area (YTA) of each county.")

    yq = "&".join(f"years={y}" for y in YEARS)
    for iid, (key, unit, direction, step, short) in IND.items():
        try:
            mraw, mts = fetch(f"{BASE}/indicators/{iid}", "sotkanet", f"indicator_{iid}.json")
            meta = json.loads(mraw)
            url = f"{BASE}/json?indicator={iid}&{yq}&genders=total&genders=female&genders=male"
            draw, dts = fetch(url, "sotkanet", f"data_{iid}.json")
            data = json.loads(draw)
        except (FetchError, ValueError) as e:
            out.problems.append(f"sotkanet {iid} {key}: {e}")
            continue
        title_fi = meta["title"]["fi"]
        title_en = meta["title"].get("en") or short
        sid = f"sotkanet_{iid}"
        out.source(sid, title=f"Sotkanet indicator {iid}: {title_en}",
                   publisher=f"THL Sotkanet; data owner: {meta.get('organization', {}).get('title', {}).get('en', 'THL')}",
                   url=f"https://sotkanet.fi/sotkanet/en/metadata/indicators/{iid}", api_call=f"GET {url}",
                   retrieved_at=dts, licence="CC BY 4.0",
                   notes=f"Finnish title: {title_fi}. Latest {KEEP_YEARS} years with county-level data kept.")
        out.define(key, label_en=short, label_fi=title_fi, unit=unit,
                   definition_en=f"Sotkanet indicator {iid}: {title_en}", direction=direction, step=step)
        recs = [d for d in data if d["region"] in region_map and d.get("value") is not None]
        county_years = sorted({d["year"] for d in recs if region_map[d["region"]] != "FI"})
        keep = set(county_years[-KEEP_YEARS:])
        best = {}
        pref = {"total": 0, "female": 1, "male": 2}
        for d in recs:
            if d["year"] not in keep:
                continue
            k = (region_map[d["region"]], d["year"])
            if k not in best or pref[d["gender"]] < pref[best[k]["gender"]]:
                best[k] = d
        if not best:
            out.problems.append(f"sotkanet {iid} {key}: no county-level values 2015-2026")
            del out.catalog[key]
            del out.sources[sid]
            continue
        for (area, year), d in sorted(best.items()):
            out.add(area, key, d["value"], year, sid,
                    sex=None if d["gender"] == "total" else d["gender"])
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(len(o.rows), "rows;", o.problems)
