"""NORDCAN (IARC) API: Nordic benchmarks - 5-year survival, incidence and mortality rates."""
from __future__ import annotations

import json

from common import Out, fetch, FetchError, PROC, now_iso, num

API = "https://canapi.iarc.who.int/api/nordcan/v2/961"
COUNTRIES = {246: "FI", 752: "SE", 578: "NO", 208: "DK"}
CANCERS = {160: "lung", 130: "pancreas", 110: "liver", 520: "colorectal", 180: "breast"}
SEX = {1: "male", 2: "female"}
CSTR = "_".join(str(c) for c in COUNTRIES)


def run() -> Out:
    out = Out("p04_nordcan")
    bench = {"generated_at": now_iso(), "publisher": "NORDCAN, IARC / Association of the Nordic Cancer Registries",
             "countries": COUNTRIES, "cancers": {}, "survival_5y": [], "rates": [], "source_ids": []}
    try:
        raw, ts = fetch(f"{API}/meta/cancers/all/", "nordcan", "meta_cancers.json")
        labels = {c["cancer"]: {"label": c["label"], "icd": c.get("ICD")} for c in json.loads(raw)}
        bench["cancers"] = {name: {"nordcan_id": cid, **labels.get(cid, {})} for cid, name in CANCERS.items()}
    except (FetchError, ValueError) as e:
        out.problems.append(f"nordcan meta: {e}")

    surv_calls, rate_calls, last_ts = [], [], None
    for cid, cname in CANCERS.items():
        for sx, sname in SEX.items():
            if cid == 180 and sx == 1:
                continue
            url = (f"{API}/survival/population/5/{sx}/{CSTR}/{cid}/?&surv_period=5&age_surv=0&year_start=1973&year_end=2023")
            try:
                raw, last_ts = fetch(url, "nordcan", f"survival_{cid}_{sx}.json")
                surv_calls.append(url)
                for r in json.loads(raw)["dataset"]:
                    s = r.get("survival") or {}
                    if num(s.get("value")) is None or r["country"] not in COUNTRIES:
                        continue
                    bench["survival_5y"].append({"country": COUNTRIES[r["country"]], "sex": sname, "cancer": cname,
                                                 "period": r["period"], "year_mid": r["year"], "value": num(s["value"]),
                                                 "lo": num(s.get("lowCI")), "hi": num(s.get("upCI")), "source_id": "nordcan_survival"})
            except (FetchError, ValueError, KeyError) as e:
                out.problems.append(f"nordcan survival {cname} {sname}: {e}")
            for typ, tname in ((0, "incidence"), (1, "mortality")):
                url = f"{API}/data/population/{typ}/{sx}/{CSTR}/{cid}/?year_start=2000&year_end=2023"
                try:
                    raw, last_ts = fetch(url, "nordcan", f"{tname}_{cid}_{sx}.json")
                    rate_calls.append(url)
                    for r in json.loads(raw)["dataset"]:
                        if r["country"] not in COUNTRIES:
                            continue
                        bench["rates"].append({"country": COUNTRIES[r["country"]], "sex": sname, "cancer": cname, "type": tname,
                                               "year": r["year"], "n": r.get("total"),
                                               "crude_rate": None if r.get("crude_rate") is None else round(r["crude_rate"], 2),
                                               "asr_world": None if r.get("asr") is None else round(r["asr"], 2),
                                               "asr_nordic": None if r.get("asr_n") is None else round(r["asr_n"], 2),
                                               "asr_european": None if r.get("asr_e") is None else round(r["asr_e"], 2),
                                               "source_id": "nordcan_rates"})
                except (FetchError, ValueError, KeyError) as e:
                    out.problems.append(f"nordcan {tname} {cname} {sname}: {e}")

    if surv_calls:
        out.source("nordcan_survival", title="NORDCAN 5-year relative survival by country, sex and cancer, 5-year periods",
                   publisher="NORDCAN (IARC, Association of the Nordic Cancer Registries)", url="https://nordcan.iarc.fr/",
                   api_call="GET " + " ; ".join(surv_calls), retrieved_at=last_ts, licence="NORDCAN terms of use (free with citation)",
                   notes="Age-standardised 5-year relative survival (%), with 95% CI, as returned by the API field 'survival'.")
        bench["source_ids"].append("nordcan_survival")
    if rate_calls:
        out.source("nordcan_rates", title="NORDCAN incidence and mortality by country, sex, cancer and year",
                   publisher="NORDCAN (IARC, Association of the Nordic Cancer Registries)", url="https://nordcan.iarc.fr/",
                   api_call="GET " + " ; ".join(rate_calls), retrieved_at=last_ts, licence="NORDCAN terms of use (free with citation)",
                   notes=("API fields: total (cases/deaths), crude_rate, asr, asr_e, asr_n per 100,000. The pipeline reads asr as World standard, "
                          "asr_e as European and asr_n as Nordic (2000) standard from the field names; the API response does not spell this out (verified: field names only)."))
        bench["source_ids"].append("nordcan_rates")

    # FI national rows for indicators.jsonl (latest period / year), lung only
    defs = {"lung_5y_survival_pct": ("Lung cancer 5-year relative survival", "Keuhkosyövän 5 vuoden suhteellinen elossaololuku", "%", "higher_is_better",
                                     "NORDCAN age-standardised 5-year relative survival, lung (incl. trachea), latest 5-year period. National only."),
            "lung_incidence_asr_per_100k": ("Lung cancer incidence, age-standardised (Nordic)", "Keuhkosyövän ilmaantuvuus, ikävakioitu (Pohjoismaat)", "per 100,000", "higher_is_worse",
                                            "NORDCAN incidence rate, API field asr_n. National only; county-level incidence is published by the Finnish Cancer Registry."),
            "lung_mortality_asr_per_100k": ("Lung cancer mortality, age-standardised (Nordic)", "Keuhkosyöpäkuolleisuus, ikävakioitu (Pohjoismaat)", "per 100,000", "higher_is_worse",
                                            "NORDCAN mortality rate, API field asr_n. National only."),
            "lung_cases_n": ("New lung cancer cases per year", "Uudet keuhkosyöpätapaukset vuodessa", "cases", "context",
                             "NORDCAN incidence count (API field total), lung. National only.")}
    for k, (en, fi, unit, direction, d) in defs.items():
        out.define(k, label_en=en, label_fi=fi, unit=unit, direction=direction, step="outcome", definition_en=d)
    for sname in SEX.values():
        s = [r for r in bench["survival_5y"] if r["country"] == "FI" and r["cancer"] == "lung" and r["sex"] == sname]
        if s:
            r = max(s, key=lambda r: r["year_mid"])
            out.add("FI", "lung_5y_survival_pct", r["value"], r["period"], "nordcan_survival", sex=sname,
                    note=f"95% CI {r['lo']}-{r['hi']}")
        for tname, key in (("incidence", "lung_incidence_asr_per_100k"), ("mortality", "lung_mortality_asr_per_100k")):
            s = [r for r in bench["rates"] if r["country"] == "FI" and r["cancer"] == "lung" and r["sex"] == sname
                 and r["type"] == tname and r["asr_nordic"] is not None]
            if s:
                r = max(s, key=lambda r: r["year"])
                out.add("FI", key, r["asr_nordic"], r["year"], "nordcan_rates", sex=sname)
                if tname == "incidence" and r["n"] is not None:
                    out.add("FI", "lung_cases_n", int(r["n"]), r["year"], "nordcan_rates", sex=sname)
    (PROC / "nordic_benchmarks.json").write_text(json.dumps(bench, ensure_ascii=False, indent=1))
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(len(o.rows), "rows;", o.problems)
