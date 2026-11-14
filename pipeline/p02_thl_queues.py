"""THL waiting-time cubes: specialist care queues by specialty (pulmonology, oncology)
per provider, latest date + series since 2021; primary care access distribution (Avohilmo)."""
from __future__ import annotations

import json
from datetime import datetime

from common import Out, fetch, FetchError, thl_records, thl_dimensions, load_areas, HUS_AREAS, AREA_IDS, PROC

ESH = "https://sampo.thl.fi/pivot/prod/fi/eshjono/jonotilanne/fact_eshjono_jonotilanne"
PTH = "https://sampo.thl.fi/pivot/prod/fi/avohpaasy/pthjono02/fact_ahil_pthjono02"
ALL_PROVIDERS = 976329
ALL_DATES = 976319
SPECIALTIES = {"pulmonology": (862301, "80 Keuhkosairaudet", "pulmonary diseases", "keuhkosairaudet"),
               "oncology": (862186, "65 Syöpätaudit", "oncology", "syöpätaudit")}
# measure sid -> (suffix, unit, direction, en, fi)
MEASURES = {
    738214: ("queue_waiting_n", "patients", "context", "Patients waiting for treatment", "Hoitoa odottaneet"),
    738220: ("queue_over_90d_pct", "%", "higher_is_worse", "Waiting for treatment over 90 days", "Yli 90 vrk hoitoa odottaneet, %"),
    738217: ("queue_over_180d_pct", "%", "higher_is_worse", "Waiting for treatment over 180 days", "Yli 180 vrk hoitoa odottaneet, %"),
    738222: ("assessment_waiting_n", "patients", "context", "Patients waiting for assessment of need for care (first specialist visit)", "Hoidon tarpeen arviointia odottaneet"),
    738228: ("assessment_over_90d_pct", "%", "higher_is_worse", "Waiting for assessment of need for care over 90 days", "Yli 90 vrk hoidon tarpeen arviointia odottaneet, %"),
    738225: ("assessment_over_180d_pct", "%", "higher_is_worse", "Waiting for assessment of need for care over 180 days", "Yli 180 vrk hoidon tarpeen arviointia odottaneet, %"),
    980631: ("referrals_ytd_n", "referrals", "context", "Referrals received since start of year", "Lähetteet yhteensä (vuoden alusta)"),
    980629: ("referrals_handled_over_21d_pct", "%", "higher_is_worse", "Referrals processed in more than 21 days", "Lähete käsitelty yli 21 vrk:ssa, %"),
    1121175: ("referrals_per_1000", "per 1,000", "context", "Referrals since start of year per 1,000 inhabitants", "Lähetteet yhteensä / 1000 as"),
}
STEP = {"pulmonology": {"queue": "diagnosis", "assessment": "referral", "referrals": "referral"},
        "oncology": {"queue": "treatment", "assessment": "treatment", "referrals": "treatment"}}
SERIES_FROM = "2021-01-01"


def provider_map() -> dict[str, list[str]]:
    m = {a["name_fi"]: [a["id"]] for a in load_areas()}
    m["HUS"] = HUS_AREAS
    m["Kaikki hyvinvointialueet"] = ["FI"]
    return m


def iso(d: str) -> str:
    return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d")


def run() -> Out:
    out = Out("p02_thl_queues")
    pmap = provider_map()
    series = []
    unmapped = set()
    for sp, (sp_sid, sp_label, sp_en, sp_fi) in SPECIALTIES.items():
        for m_sid, (suffix, unit, direction, en, fi) in MEASURES.items():
            key = f"{sp}_{suffix}"
            out.define(key, label_en=f"{en} ({sp_en})", label_fi=f"{fi} ({sp_fi})", unit=unit,
                       definition_en=(f"THL specialist care waiting-time cube, specialty {sp_label}, measure '{fi}'. "
                                      "Snapshot at the stated date, by service provider (hospital organisation)."),
                       direction=direction, step=STEP[sp][suffix.split("_")[0]])
            url = (f"{ESH}.json?row=tuottaja-{ALL_PROVIDERS}&column=ajankohta-{ALL_DATES}"
                   f"&filter=erikoisala-{sp_sid}&filter=measure-{m_sid}")
            sid = f"thl_eshjono_{sp}_{suffix}"
            try:
                raw, ts = fetch(url, "thl_eshjono", f"{sp}_{m_sid}.json")
                recs = thl_records(json.loads(raw))
            except (FetchError, ValueError, KeyError) as e:
                out.problems.append(f"thl eshjono {key}: {e}")
                continue
            out.source(sid, title=f"Specialist care waiting times: {sp_label} - {fi}", publisher="THL (Finnish Institute for Health and Welfare)",
                       url="https://sampo.thl.fi/pivot/prod/fi/eshjono/jonotilanne/fact_eshjono_jonotilanne",
                       api_call=f"GET {url}", retrieved_at=ts, licence="CC BY 4.0",
                       notes=("Values are by provider. HUS is one provider for East, Central and West Uusimaa, Vantaa-Kerava and Helsinki: "
                              "its value is written to each of those five areas with note 'HUS-wide value'. Åland is not in the cube. "
                              "The provider 'Helsingin sosiaali-, terveys- ja pelastustoimi' (city-run specialist care) is not mapped."))
            recs = [r for r in recs if r["value"] is not None and r["ajankohta_label"][:1].isdigit()]
            for r in recs:
                r["date"] = iso(r["ajankohta_label"])
            if not recs:
                out.problems.append(f"thl eshjono {key}: no values")
                continue
            latest = max(r["date"] for r in recs)
            cutoff = f"{int(latest[:4]) - 1}{latest[4:]}"
            last_by_provider = {}
            for r in recs:
                if r["date"] > cutoff:
                    last_by_provider[r["tuottaja_label"]] = max(last_by_provider.get(r["tuottaja_label"], ""), r["date"])
            for r in recs:
                areas = pmap.get(r["tuottaja_label"])
                if areas is None:
                    unmapped.add(r["tuottaja_label"])
                    continue
                note = "HUS-wide value" if r["tuottaja_label"] == "HUS" else None
                for a in areas:
                    if r["date"] >= SERIES_FROM:
                        row = {"area_id": a, "specialty": sp, "date": r["date"], "measure": suffix,
                               "value": r["value"], "source_id": sid}
                        if note:
                            row["note"] = note
                        series.append(row)
                    if r["date"] == last_by_provider.get(r["tuottaja_label"]):
                        out.add(a, key, r["value"], r["date"], sid, note=note)
    out.extra["thl_queue_series"] = series
    out.extra["unmapped_providers"] = sorted(unmapped)

    # --- Primary care: waiting time from earliest timestamp to realised visit, physicians, outpatient care
    try:
        draw, dts = fetch(PTH + ".dimensions.json", "thl_avohpaasy", "pthjono02.dimensions.json")
        dims = thl_dimensions(draw.decode("utf-8"))

        def sid_of(dim, pred):
            return next(n["sid"] for n in dims[dim] if pred(n))

        doc = sid_of("ammatti", lambda n: n["label"] == "Lääkärit")
        avo = sid_of("palvelumuoto", lambda n: n["label"] == "Avosairaanhoito")
        prov_root = sid_of("palveluntuottaja", lambda n: n["stage"] == "root")
        wait_root = sid_of("odotusaika", lambda n: n["stage"] == "root")
        m_n = sid_of("measure", lambda n: n["code"] == "kaynti_lkm")
        m_pct = sid_of("measure", lambda n: n["code"] == "kaynti_hpkaynnit")
        years = {n["label"]: n["sid"] for n in dims["aika"] if n["stage"] == "vuosi"}
        county_code = {n["label"]: n["code"] for n in dims["palveluntuottaja"] if n["stage"] == "maakunta"}
        prov_list = ".".join(str(n["sid"]) for n in dims["palveluntuottaja"]
                             if n["stage"] == "root" or (n["stage"] == "maakunta" and n["code"] in AREA_IDS)) + "."
        root_label = next(n["label"] for n in dims["palveluntuottaja"] if n["stage"] == "root")
        bands = {"0-7 vrk": ("gp_access_within_7d_pct", "higher_is_better", "within 7 days", "0-7 vrk"),
                 "8-14 vrk": ("gp_access_8_14d_pct", "context", "in 8-14 days", "8-14 vrk"),
                 "15-30 vrk": ("gp_access_15_30d_pct", "higher_is_worse", "in 15-30 days", "15-30 vrk"),
                 "31-90 vrk": ("gp_access_31_90d_pct", "higher_is_worse", "in 31-90 days", "31-90 vrk"),
                 "Yli 90 vrk": ("gp_access_over_90d_pct", "higher_is_worse", "after more than 90 days", "yli 90 vrk")}
        for b, (key, direction, en, fi) in bands.items():
            out.define(key, label_en=f"GP outpatient visits realised {en} of first contact", unit="%",
                       label_fi=f"Avosairaanhoidon lääkärikäynnit, odotusaika {fi} varhaisimmasta aikaleimasta, % hoitoonpääsykäynneistä",
                       definition_en=("THL Avohilmo cube 'Hoitoonpääsy perusterveydenhuollossa varhaisimmasta aikaleimasta toteutuneeseen käyntiin': "
                                      "share of access-to-care visits (physician, outpatient medical care) by waiting-time band, "
                                      "measured from the earliest recorded timestamp (contact / assessment of need) to the realised visit."),
                       direction=direction, step="primary")
        out.define("gp_access_visits_n", label_en="GP access-to-care visits with a recorded waiting time", unit="visits",
                   label_fi="Avosairaanhoidon lääkärin hoitoonpääsykäynnit, joille odotusaika kirjattu",
                   definition_en="Denominator of the gp_access_* shares (all realised visits with a waiting time, physicians, outpatient medical care).",
                   direction="context", step="primary")
        for ylabel in sorted(years)[-2:]:
            for meas, mname in ((m_pct, "pct"), (m_n, "n")):
                url = (f"{PTH}.json?row=palveluntuottaja-{prov_list}&column=odotusaika-{wait_root}"
                       f"&filter=ammatti-{doc}&filter=palvelumuoto-{avo}&filter=aika-{years[ylabel]}&filter=measure-{meas}")
                sid = f"thl_avohpaasy_gp_{ylabel}_{mname}"
                try:
                    raw, ts = fetch(url, "thl_avohpaasy", f"gp_{ylabel}_{mname}.json")
                    recs = thl_records(json.loads(raw))
                except (FetchError, ValueError, KeyError) as e:
                    out.problems.append(f"thl avohpaasy {ylabel} {mname}: {e}")
                    continue
                out.source(sid, title=f"Avohilmo: access to primary care from earliest timestamp to realised visit, physicians, outpatient care, {ylabel} ({mname})",
                           publisher="THL (Finnish Institute for Health and Welfare)",
                           url="https://sampo.thl.fi/pivot/prod/fi/avohpaasy/pthjono02/fact_ahil_pthjono02",
                           api_call=f"GET {url}", retrieved_at=ts, licence="CC BY 4.0",
                           notes="By wellbeing services county of the provider. 2026 is year-to-date. Åland is not in the cube.")
                for r in recs:
                    lab = r["palveluntuottaja_label"]
                    area = "FI" if lab == root_label else county_code.get(lab)
                    if area is None or r["value"] is None or (area != "FI" and area not in AREA_IDS):
                        continue
                    wl = r["odotusaika_label"].replace(" ", "").replace("-", "-")
                    period = ylabel if ylabel != max(years) else f"{ylabel} (year to date)"
                    if mname == "n":
                        if r["odotusaika_label"] == next(n["label"] for n in dims["odotusaika"] if n["stage"] == "root"):
                            out.add(area, "gp_access_visits_n", r["value"], period, sid)
                        continue
                    for b, (key, *_rest) in bands.items():
                        if wl == b.replace(" ", ""):
                            out.add(area, key, r["value"], period, sid)
    except (FetchError, ValueError, KeyError, StopIteration) as e:
        out.problems.append(f"thl avohpaasy primary care cube: {e!r}")

    (PROC / "thl_queue_series.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sorted(
            series, key=lambda r: (r["specialty"], r["measure"], r["area_id"], r["date"]))))
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(len(o.rows), "rows;", len(o.extra["thl_queue_series"]), "series rows;", o.extra["unmapped_providers"], o.problems)
