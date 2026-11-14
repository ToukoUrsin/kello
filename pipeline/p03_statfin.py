"""Statistics Finland PxWeb: cancer deaths by county, population structure, 65+ projection."""
from __future__ import annotations

import json

from common import Out, fetch, FetchError, jsonstat2_records, AREA_IDS

PX = "https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin"
LIC = "CC BY 4.0"
CAUSES = {  # code -> (key stem, English, Finnish)
    "04-21": ("cancer", "all cancers (C00-C97)", "syövät (C00-C97)"),
    "11": ("lung", "cancer of larynx, trachea and lung (C32-C34)", "kurkunpään, henkitorven ja keuhkon syöpä (C32-C34)"),
    "10": ("pancreas", "pancreatic cancer (C25)", "haimasyöpä (C25)"),
    "09": ("liver", "primary liver cancer (C22)", "primaarinen maksasyöpä (C22)"),
    "07": ("colon", "colon cancer (C18-C19)", "koolonin syöpä (C18, C19)"),
    "08": ("rectum", "cancer of rectum and anus (C20-C21)", "peräsuolen ja peräaukon syöpä (C20-C21)"),
    "13": ("breast", "breast cancer (C50)", "rintasyöpä (C50)"),
    "17": ("prostate", "prostate cancer (C61)", "eturauhasen syöpä (C61)"),
    "33": ("copd", "bronchitis and emphysema / COPD (J40-J44, J47)", "keuhkoputkentulehdus ja keuhkolaajentuma (J40-J44, J47)"),
}
YEARS = [str(y) for y in range(2016, 2026)]


def area_of(code: str) -> str | None:
    if code == "SSS":
        return "FI"
    if code.startswith("HVA") and code[3:] in AREA_IDS:
        return code[3:]
    return None


def px(table: str, query: dict, name: str):
    body = {"query": [{"code": k, "selection": {"filter": "item", "values": v}} for k, v in query.items()],
            "response": {"format": "json-stat2"}}
    url = f"{PX}/{table}"
    raw, ts = fetch(url, "statfin", name, post_json=body)
    return jsonstat2_records(json.loads(raw)), ts, f"POST {url} body={json.dumps(body, ensure_ascii=False)}"


def meta(table: str) -> dict:
    raw, _ = fetch(f"{PX}/{table}", "statfin", table.replace("/", "_") + ".meta.px.json")
    return {v["code"]: v for v in json.loads(raw)["variables"]}


def run() -> Out:
    out = Out("p03_statfin")
    pop, pop65 = {}, {}  # (area, year) -> value

    # ---- population key figures (11ra)
    try:
        m = meta("vaerak/11ra.px")
        acode = next(c for c in m if c.startswith("alue"))
        hva = [v for v in m[acode]["values"] if area_of(v)]
        years = [y for y in m["timeperiod_y"]["values"] if y in YEARS]
        content = {"vaerak-vaesto": ("pop_total", "persons", "Population on 31 Dec", "Väestö 31.12.", "context"),
                   "vaesto_yli64_p": ("pop_65plus_pct", "%", "Share of population aged 65 or over", "65 vuotta täyttäneiden osuus, %", "context"),
                   "vaerak-vaesto_maa_pa": ("pop_density_per_km2", "per km2", "Population density", "Väestöntiheys", "context"),
                   "vaesto_ms_p": ("rural_pop_pct", "%", "Share living in rural areas (urban-rural classification)", "Maaseutualueella asuvien osuus, %", "context"),
                   "vaesto_m7_p": ("sparse_rural_pop_pct", "%", "Share living in sparsely populated rural areas", "Harvaan asutulla maaseudulla asuvien osuus, %", "context"),
                   "vaesto_keski_ika": ("mean_age_years", "years", "Mean age of population", "Keski-ikä, molemmat sukupuolet", "context")}
        recs, ts, call = px("vaerak/11ra.px", {acode: hva, "contentscode": list(content), "timeperiod_y": years}, "11ra_hva.json")
        out.source("statfin_11ra", title="11ra -- Key figures on population by region, 1990-2025", publisher="Statistics Finland",
                   url="https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/StatFin__vaerak/statfin_vaerak_pxt_11ra.px/",
                   api_call=call, retrieved_at=ts, licence=LIC, notes="Wellbeing services county rows (HVAxx) and whole country (SSS); 2026 regional division.")
        for c, (key, unit, en, fi, direction) in content.items():
            out.define(key, label_en=en, label_fi=fi, unit=unit, direction=direction, step=None,
                       definition_en=f"Statistics Finland table 11ra, content '{fi}', by wellbeing services county.")
        last5 = set(sorted(years)[-5:])
        for r in recs:
            a = area_of(r[acode])
            if a is None or r["value"] is None:
                continue
            y = r["timeperiod_y"]
            if r["contentscode"] == "vaerak-vaesto":
                pop[(a, y)] = r["value"]
            if r["contentscode"] == "vaesto_yli64_p":
                pop65[(a, y)] = r["value"]
            if y in last5:
                out.add(a, content[r["contentscode"]][0], r["value"], y, "statfin_11ra")
        out.extra["pop"] = {f"{a}|{y}": v for (a, y), v in pop.items()}
    except (FetchError, ValueError, KeyError, StopIteration) as e:
        out.problems.append(f"statfin 11ra population: {e!r}")

    # ---- deaths by cause (13u5)
    try:
        m = meta("ksyyt/13u5.px")
        acode = next(c for c in m if c.startswith("alue"))
        ccode = next(c for c in m if c.startswith("kuolinsyyt"))
        hva = [v for v in m[acode]["values"] if area_of(v)]
        years = [y for y in m["timeperiod_y"]["values"] if y in YEARS]
        recs, ts, call = px("ksyyt/13u5.px", {acode: hva, ccode: list(CAUSES), "timeperiod_y": years,
                                              "contentscode": ["ksyylkm", "ksyycdr"]}, "13u5_cancer.json")
        out.source("statfin_13u5", title="13u5 -- Deaths by underlying cause of death (time series classification) and wellbeing services county, 1969-2025",
                   publisher="Statistics Finland",
                   url="https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/StatFin__ksyyt/statfin_ksyyt_pxt_13u5.px/",
                   api_call=call, retrieved_at=ts, licence=LIC,
                   notes="Counts and crude death rate per 100,000 mean population. The 'lung' group is C32-C34 (larynx, trachea and lung). Crude rates are not age-standardised.")
        for code, (stem, en, fi) in CAUSES.items():
            step = "outcome"
            out.define(f"{stem}_deaths_n", label_en=f"Deaths, {en}", label_fi=f"Kuolleet, {fi}", unit="deaths", direction="context", step=step,
                       definition_en=f"Number of deaths per year, underlying cause {en}. Statistics Finland 13u5.")
            out.define(f"{stem}_deaths_per_100k", label_en=f"Crude death rate, {en}", label_fi=f"Yleinen kuolleisuusluku, {fi} (1/100 000)",
                       unit="per 100,000", direction="higher_is_worse", step=step,
                       definition_en=f"Crude deaths per 100,000 population, underlying cause {en}. Not age-standardised: older counties score higher for demographic reasons alone.")
            out.define(f"{stem}_deaths_per_100k_5y", label_en=f"Crude death rate 2021-2025 pooled, {en}",
                       label_fi=f"Kuolleisuus 2021-2025 yhteensä, {fi} (1/100 000)", unit="per 100,000", direction="higher_is_worse", step=step,
                       definition_en=(f"Sum of deaths 2021-2025 ({en}, table 13u5) divided by the sum of year-end populations 2021-2025 (table 11ra), x 100,000. "
                                      "Pooled to reduce small-number noise. Crude."))
            out.define(f"{stem}_deaths_per_100k_65plus_5y", label_en=f"Deaths per 100,000 residents aged 65+, 2021-2025 pooled, {en}",
                       label_fi=f"Kuolleet 100 000:ta 65 vuotta täyttänyttä kohti 2021-2025, {fi}", unit="per 100,000 aged 65+",
                       direction="higher_is_worse", step=step,
                       definition_en=(f"Sum of deaths at all ages 2021-2025 ({en}) divided by the sum of year-end population aged 65+ "
                                      "(population x share aged 65+, table 11ra), x 100,000. A rough age-structure adjustment, not a standardised rate."))
        d = {}
        for r in recs:
            a = area_of(r[acode])
            if a is None or r["value"] is None:
                continue
            stem = CAUSES[r[ccode]][0]
            key = f"{stem}_deaths_n" if r["contentscode"] == "ksyylkm" else f"{stem}_deaths_per_100k"
            out.add(a, key, r["value"], r["timeperiod_y"], "statfin_13u5")
            if r["contentscode"] == "ksyylkm":
                d[(a, stem, r["timeperiod_y"])] = r["value"]
        pooled_years = [y for y in sorted(years)[-5:]]
        for stem in [c[0] for c in CAUSES.values()]:
            for a in AREA_IDS + ["FI"]:
                if not all((a, stem, y) in d and (a, y) in pop and (a, y) in pop65 for y in pooled_years):
                    continue
                deaths = sum(d[(a, stem, y)] for y in pooled_years)
                p = sum(pop[(a, y)] for y in pooled_years)
                p65 = sum(pop[(a, y)] * pop65[(a, y)] / 100 for y in pooled_years)
                period = f"{pooled_years[0]}-{pooled_years[-1]}"
                note = "computed by pipeline from Statistics Finland counts (13u5) and population (11ra); source_id lists the numerator table"
                out.add(a, f"{stem}_deaths_per_100k_5y", round(deaths / p * 1e5, 1), period, "statfin_13u5", note=note)
                out.add(a, f"{stem}_deaths_per_100k_65plus_5y", round(deaths / p65 * 1e5, 1), period, "statfin_13u5", note=note)
    except (FetchError, ValueError, KeyError, StopIteration) as e:
        out.problems.append(f"statfin 13u5 deaths: {e!r}")

    # ---- population projection 2024 (14wx), municipality -> county
    try:
        curl = ("https://data.stat.fi/api/classifications/v2/correspondenceTables/"
                "kunta_1_20240101%23hyvinvointialue_1_20240101/maps?content=data&meta=max&lang=fi&format=json")
        raw, cts = fetch(curl, "statfin", "kunta2024_hva2024.json")
        k2h = {x["sourceLocalId"].split("/")[-1]: x["targetLocalId"].split("/")[-1] for x in json.loads(raw)}
        out.source("statfin_kunta_hva_2024", title="Correspondence table: municipalities 2024 - wellbeing services counties 2024",
                   publisher="Statistics Finland", url="https://stat.fi/en/luokitukset/corrmaps/kunta_1_20240101%23hyvinvointialue_1_20240101",
                   api_call=f"GET {curl}", retrieved_at=cts, licence=LIC, notes="Used to aggregate municipal projections to counties.")
        m = meta("vaenn/14wx.px")
        acode = next(c for c in m if c.startswith("alue"))
        agecode = next(c for c in m if c.startswith("ika"))
        sexcode = next(c for c in m if c.startswith("sukupuoli"))
        ages = m[agecode]["values"]
        age65 = [a for a in ages if a != "SSS" and int(a.rstrip("-")) >= 65]
        yrs = ["2025", "2030", "2035", "2040"]
        recs, ts, call = px("vaenn/14wx.px", {acode: m[acode]["values"], "timeperiod_y": yrs, sexcode: ["SSS"],
                                              agecode: ["SSS"] + age65}, "14wx_65plus.json")
        out.source("statfin_14wx", title="14wx -- Population projection 2024: population by age and sex by area, 2024-2045",
                   publisher="Statistics Finland",
                   url="https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/StatFin__vaenn/statfin_vaenn_pxt_14wx.px/",
                   api_call=call[:1500] + (" ...(truncated; full body in data/raw/statfin/14wx_65plus.json.meta.json)" if len(call) > 1500 else ""),
                   retrieved_at=ts, licence=LIC,
                   notes="Municipal projection (trend calculation by Statistics Finland, 2024 base) summed to counties with the 2024 municipality-county key. A projection published by the source, not an estimate by this project.")
        tot, t65 = {}, {}
        for r in recs:
            code = r[acode]
            a = "FI" if code == "SSS" else k2h.get(code[2:]) if code.startswith("KU") else None
            if a is None or r["value"] is None:
                continue
            k = (a, r["timeperiod_y"])
            if r[agecode] == "SSS":
                tot[k] = tot.get(k, 0) + r["value"]
            else:
                t65[k] = t65.get(k, 0) + r["value"]
        for y in ("2030", "2035", "2040"):
            out.define(f"pop_65plus_{y}_proj", label_en=f"Population aged 65+ in {y} (official projection)", label_fi=f"65 vuotta täyttäneet {y} (väestöennuste 2024)",
                       unit="persons", direction="context", step=None,
                       definition_en=f"Statistics Finland population projection 2024, persons aged 65+ on 31 Dec {y}, municipalities summed to county.")
        out.define("pop_65plus_pct_2035_proj", label_en="Share aged 65+ in 2035 (official projection)", label_fi="65 vuotta täyttäneiden osuus 2035 (väestöennuste 2024)",
                   unit="%", direction="context", step=None, definition_en="Projected 65+ population / projected total population, 2035.")
        out.define("pop_65plus_change_2025_2035_pct", label_en="Change in population aged 65+, 2025 to 2035 (official projection)",
                   label_fi="65 vuotta täyttäneiden määrän muutos 2025-2035 (väestöennuste 2024)", unit="%", direction="context", step=None,
                   definition_en="(65+ in 2035 / 65+ in 2025 - 1) x 100, both from the 2024 projection.")
        for a in AREA_IDS + ["FI"]:
            for y in ("2030", "2035", "2040"):
                if (a, y) in t65:
                    out.add(a, f"pop_65plus_{y}_proj", int(t65[(a, y)]), y, "statfin_14wx")
            if (a, "2035") in t65 and (a, "2025") in t65:
                out.add(a, "pop_65plus_pct_2035_proj", round(t65[(a, "2035")] / tot[(a, "2035")] * 100, 1), "2035", "statfin_14wx")
                out.add(a, "pop_65plus_change_2025_2035_pct", round((t65[(a, "2035")] / t65[(a, "2025")] - 1) * 100, 1), "2025-2035", "statfin_14wx")
    except (FetchError, ValueError, KeyError, StopIteration) as e:
        out.problems.append(f"statfin 14wx projection: {e!r}")
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(len(o.rows), "rows;", o.problems)
