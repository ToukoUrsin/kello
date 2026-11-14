"""Build SAMPLE fixture data for the Kello app shell.

Everything written here is placeholder data so the UI and API can be exercised
before the data, evidence and model agents deliver. Every API response built
from it carries "fixture": true. Numbers are plausible, not sourced.

Run:  .venv/bin/python app/server/fixtures/build_fixtures.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AREAS = json.loads((ROOT / "data/processed/areas.json").read_text())

NOTE = "SAMPLE FIXTURE - placeholder value, not retrieved from the source"
TODAY = "2026-11-13"


def h(*parts: str) -> float:
    """Deterministic pseudo-random number in [0, 1)."""
    d = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(d[:6], "big") / 2**48


# Approximate population (thousands), from memory: fixture only.
POP_K = {"01": 99, "02": 203, "03": 480, "04": 280, "05": 490, "06": 212, "07": 170, "08": 540,
         "09": 205, "10": 160, "11": 125, "12": 130, "13": 248, "14": 163, "15": 273, "16": 191,
         "17": 177, "18": 68, "19": 416, "20": 70, "21": 176, "90": 665, "91": 30}
# Rough remoteness 0..1 used to shape the sample pattern (fixture only).
REMOTE = {"90": 0.0, "04": 0.05, "03": 0.1, "02": 0.1, "01": 0.2, "08": 0.15, "05": 0.15, "19": 0.35,
          "13": 0.3, "15": 0.4, "09": 0.35, "07": 0.35, "06": 0.45, "10": 0.5, "11": 0.5, "12": 0.7,
          "14": 0.6, "16": 0.55, "17": 0.45, "18": 0.6, "20": 0.9, "21": 0.85, "91": 0.5}

STEPS = [
    ("patient", "First symptom to first primary care contact", "Ensioireesta ensimmäiseen yhteydenottoon", 28, "assumption",
     "No Finnish source records symptom onset. Taken from Nordic patient-interval studies and scaled by distance and age structure."),
    ("primary", "Primary care contact to referral", "Perusterveydenhuollosta lähetteeseen", 19, "estimated",
     "Estimated from primary care waiting-time shares and chest X-ray access; no timestamp links contact to referral."),
    ("referral", "Referral to first specialist visit", "Lähetteestä erikoissairaanhoidon ensikäyntiin", 15, "measured",
     "Median wait from referral to first pulmonology visit as published by the hospital district."),
    ("diagnosis", "First specialist visit to treatment decision", "Ensikäynnistä hoitopäätökseen", 33, "estimated",
     "Estimated from imaging and pathology turnaround indicators and the share of cases with complete staging."),
    ("treatment", "Treatment decision to treatment start", "Hoitopäätöksestä hoidon alkuun", 21, "estimated",
     "Estimated from surgical and radiotherapy queue indicators and distance to the university hospital."),
]

SOURCES = {
    "fx_thl_sotkanet": {"title": "Sotkanet indicator bank", "publisher": "THL", "url": "https://sotkanet.fi/", "api_call": None,
                        "retrieved_at": None, "licence": "CC BY 4.0", "notes": NOTE, "verified": False},
    "fx_thl_access": {"title": "Access to care statistics (hoitoonpääsy)", "publisher": "THL", "url": "https://thl.fi/", "api_call": None,
                      "retrieved_at": None, "licence": "CC BY 4.0", "notes": NOTE, "verified": False},
    "fx_fcr": {"title": "Finnish Cancer Registry statistics", "publisher": "Finnish Cancer Registry", "url": "https://cancerregistry.fi/",
               "api_call": None, "retrieved_at": None, "licence": "CC BY 4.0", "notes": NOTE, "verified": False},
    "fx_nordcan": {"title": "NORDCAN: cancer statistics for the Nordic countries", "publisher": "IARC / ANCR", "url": "https://nordcan.iarc.fr/",
                   "api_call": None, "retrieved_at": None, "licence": "see site", "notes": NOTE, "verified": False},
    "fx_statfi": {"title": "Population structure by wellbeing services county", "publisher": "Statistics Finland", "url": "https://stat.fi/",
                  "api_call": None, "retrieved_at": None, "licence": "CC BY 4.0", "notes": NOTE, "verified": False},
    "fx_literature": {"title": "Published pathway-interval studies (placeholder for the evidence table)", "publisher": "various",
                      "url": "https://pubmed.ncbi.nlm.nih.gov/", "api_call": None, "retrieved_at": None, "licence": "n/a", "notes": NOTE, "verified": False},
    "fx_model": {"title": "Kello pathway simulation (sample engine)", "publisher": "Kello", "url": None, "api_call": None,
                 "retrieved_at": TODAY, "licence": "n/a", "notes": "Sample engine in app/server/fixture_model.py; replaced by kello_model.", "verified": False},
}


def driver(aid, key, label, nat, spread, unit, period, src, kind="measured", digits=1):
    val = nat * (1 + spread * (2 * h(aid, key) - 1) + 0.25 * spread * (REMOTE.get(aid, 0.4) - 0.4) * 2)
    return {"indicator": key, "label_en": label, "value": round(val, digits), "national": nat, "unit": unit,
            "period": period, "source_id": src, "kind": kind}


def step_drivers(aid: str):
    return {
        "patient": [
            driver(aid, "km_to_university_hospital", "Median distance to university hospital", 92, 0.9, "km", "2025", "fx_statfi", digits=0),
            driver(aid, "pop_65plus_pct", "Population aged 65 and over", 23.6, 0.25, "%", "2025", "fx_statfi"),
        ],
        "primary": [
            driver(aid, "primary_care_wait_over_7d_pct", "Non-urgent primary care visits waited over 7 days", 41.0, 0.45, "%", "2026 Q2", "fx_thl_access"),
            driver(aid, "gp_per_10k", "Primary care physicians per 10,000 residents", 6.4, 0.3, "per 10,000", "2025", "fx_thl_sotkanet"),
        ],
        "referral": [
            driver(aid, "pulmonology_queue_over_90d_pct", "Pulmonology referrals waiting over 90 days", 7.8, 0.8, "%", "2026 Q2", "fx_thl_access"),
            driver(aid, "pulmonology_wait_median_days", "Median wait to first pulmonology visit", 15, 0.4, "days", "2026 Q2", "fx_thl_access", digits=0),
        ],
        "diagnosis": [
            driver(aid, "lung_stage_known_pct", "Lung cancers with stage recorded", 78.0, 0.15, "%", "2019-2023", "fx_fcr"),
            driver(aid, "ct_wait_median_days", "Median wait for non-urgent CT", 16, 0.5, "days", "2025", "fx_thl_access", kind="estimated", digits=0),
        ],
        "treatment": [
            driver(aid, "lung_curative_intent_pct", "Lung cancers treated with curative intent", 24.0, 0.3, "%", "2019-2023", "fx_fcr"),
            driver(aid, "surgery_queue_over_180d_pct", "Surgical queue waiting over 180 days", 9.5, 0.6, "%", "2026 Q2", "fx_thl_access"),
        ],
    }


DATA_GAPS = [
    {"what_en": "Date of first symptom", "why_it_matters_en": "The patient interval is the least understood part of the pathway; it is an assumption here.",
     "who_could_publish_en": "Wellbeing services counties, by recording symptom onset at the first contact"},
    {"what_en": "Date of the referral that led to the diagnosis, linked to the cancer registry", "why_it_matters_en": "Without it nobody can say how long a lung cancer patient waited in primary care.",
     "who_could_publish_en": "THL (Avohilmo and Hilmo) linked with the Finnish Cancer Registry"},
    {"what_en": "Date of the treatment decision (MDT meeting)", "why_it_matters_en": "Separates diagnostic delay from treatment capacity delay; today the two are estimated together.",
     "who_could_publish_en": "University hospitals, through the national cancer quality register"},
    {"what_en": "Date of first treatment, by modality, per county of residence", "why_it_matters_en": "Denmark and Sweden publish this monthly; Finland has no comparable public series.",
     "who_could_publish_en": "National Cancer Center Finland (FICAN) and THL"},
    {"what_en": "Turnaround time of molecular pathology", "why_it_matters_en": "Targeted treatment cannot start before the result arrives.",
     "who_could_publish_en": "Hospital laboratories (HUSLAB, Fimlab, Nordlab, Islab, Tyks)"},
]

INTERVENTIONS = [
    dict(id="fast_track_pathway", name_en="Standardised lung cancer fast-track pathway", name_fi="Keuhkosyövän nopeutettu hoitopolku",
         step="diagnosis", what_en="Booked slots for CT, bronchoscopy and MDT within fixed day limits, with one coordinator who owns the clock.",
         what_fi="Varatut ajat TT-kuvaukseen, bronkoskopiaan ja moniammatilliseen kokoukseen kiinteissä aikarajoissa; yksi koordinaattori vastaa aikataulusta.",
         effect=dict(metric="relative_days", value=0.30, lo=0.15, hi=0.42), cost=dict(eur_setup=90000, eur_per_year=160000, scales_with="county"),
         roadmap_measure="3.1", owner_en="Chief physician, pulmonology", owner_fi="Keuhkosairauksien ylilääkäri", prerequisite_en=None, confidence="medium"),
    dict(id="ct_capacity", name_en="Direct-access CT slots for primary care", name_fi="Suora pääsy TT-kuvaukseen perusterveydenhuollosta",
         step="primary", what_en="Reserved low-dose CT slots that a GP can book the same week for a patient with red-flag symptoms.",
         what_fi="Varatut matala-annos-TT-ajat, jotka yleislääkäri voi varata samalle viikolle hälytysoireiselle potilaalle.",
         effect=dict(metric="days", value=7, lo=3, hi=11), cost=dict(eur_setup=40000, eur_per_year=95000, scales_with="per_100k_pop"),
         roadmap_measure="2.5", owner_en="Head of imaging services", owner_fi="Kuvantamisen palvelujohtaja", prerequisite_en=None, confidence="medium"),
    dict(id="ai_cxr_triage", name_en="AI triage of chest X-rays", name_fi="Keuhkokuvien tekoälyseulonta",
         step="primary", what_en="Software flags suspicious chest X-rays for same-day reporting and CT.",
         what_fi="Ohjelmisto nostaa epäilyttävät keuhkokuvat saman päivän lausuntoon ja TT-kuvaukseen.",
         effect=dict(metric="days", value=4, lo=0, hi=8), cost=dict(eur_setup=60000, eur_per_year=70000, scales_with="county"),
         roadmap_measure="4.1", owner_en="Head of imaging services", owner_fi="Kuvantamisen palvelujohtaja",
         prerequisite_en="Free CT capacity (ct_capacity); without it flagged patients wait in the same queue.", confidence="low",
         null_results=[dict(claim="AI X-ray triage alone: no reduction in time to diagnosis without CT capacity (LungIMPACT 2026)", url=None, year=2026)]),
    dict(id="nurse_navigator", name_en="Cancer nurse navigator", name_fi="Syöpähoitaja-koordinaattori",
         step="referral", what_en="A named nurse books every step, chases results and is the patient's single phone number.",
         what_fi="Nimetty hoitaja varaa jokaisen vaiheen, seuraa tuloksia ja on potilaan ainoa yhteysnumero.",
         effect=dict(metric="days", value=5, lo=2, hi=9), cost=dict(eur_setup=10000, eur_per_year=68000, scales_with="per_100k_pop"),
         roadmap_measure="1.2", owner_en="Director of nursing, cancer services", owner_fi="Syöpäpalvelujen hoitotyön johtaja", prerequisite_en=None, confidence="medium"),
    dict(id="reflex_molecular", name_en="Reflex molecular testing at biopsy", name_fi="Refleksinomainen molekyylitestaus biopsiasta",
         step="diagnosis", what_en="The pathologist orders the gene panel when non-small-cell cancer is seen, without waiting for the oncologist.",
         what_fi="Patologi tilaa geenipaneelin heti ei-pienisoluisen syövän löydyttyä odottamatta onkologin pyyntöä.",
         effect=dict(metric="days", value=8, lo=4, hi=13), cost=dict(eur_setup=20000, eur_per_year=900, scales_with="per_patient"),
         roadmap_measure="4.3", owner_en="Chief of pathology", owner_fi="Patologian ylilääkäri", prerequisite_en=None, confidence="high"),
    dict(id="virtual_mdt", name_en="Twice-weekly virtual MDT with the university hospital", name_fi="Etä-MDT yliopistosairaalan kanssa kahdesti viikossa",
         step="treatment", what_en="Cases are decided by video within days instead of waiting for the next in-person meeting.",
         what_fi="Tapaukset ratkaistaan videoyhteydellä päivissä seuraavan lähikokouksen odottamisen sijaan.",
         effect=dict(metric="days", value=4, lo=1, hi=7), cost=dict(eur_setup=15000, eur_per_year=45000, scales_with="county"),
         roadmap_measure="3.1", owner_en="University hospital cancer centre", owner_fi="Yliopistosairaalan syöpäkeskus", prerequisite_en=None, confidence="medium"),
    dict(id="symptom_campaign", name_en="Symptom awareness campaign (cough over 3 weeks)", name_fi="Oirekampanja (yli 3 viikon yskä)",
         step="patient", what_en="Local campaign and pharmacy prompts telling people with a persistent cough to book a visit.",
         what_fi="Paikallinen kampanja ja apteekkien muistutukset: pitkittynyt yskä kannattaa tutkia.",
         effect=dict(metric="days", value=3, lo=0, hi=7), cost=dict(eur_setup=30000, eur_per_year=38000, scales_with="per_100k_pop"),
         roadmap_measure="1.3", owner_en="Health promotion lead", owner_fi="Hyvinvoinnin ja terveyden edistämisen päällikkö", prerequisite_en=None, confidence="low"),
    dict(id="gp_decision_support", name_en="GP risk tool and e-consultation with pulmonology", name_fi="Yleislääkärin riskityökalu ja e-konsultaatio keuhkolääkärille",
         step="primary", what_en="Risk score in the patient record plus an e-consult answered within two working days.",
         what_fi="Riskipisteytys potilastietojärjestelmässä ja e-konsultaatio, johon vastataan kahdessa arkipäivässä.",
         effect=dict(metric="days", value=4, lo=1, hi=8), cost=dict(eur_setup=25000, eur_per_year=40000, scales_with="county"),
         roadmap_measure="2.5", owner_en="Medical director, primary care", owner_fi="Perusterveydenhuollon johtava lääkäri", prerequisite_en=None, confidence="medium"),
    dict(id="pathway_timestamps", name_en="Record and publish the five pathway timestamps", name_fi="Kirjataan ja julkaistaan hoitopolun viisi aikaleimaa",
         step="referral", what_en="Symptom onset, first contact, referral, treatment decision and treatment start recorded as structured fields and published monthly.",
         what_fi="Oireen alku, ensikontakti, lähete, hoitopäätös ja hoidon alku kirjataan rakenteisesti ja julkaistaan kuukausittain.",
         effect=dict(metric="days", value=1, lo=0, hi=3), cost=dict(eur_setup=45000, eur_per_year=20000, scales_with="county"),
         roadmap_measure="3.2", owner_en="Chief information officer", owner_fi="Tietojohtaja", prerequisite_en=None, confidence="medium"),
]

ROADMAP = [
    dict(id="1.2", title_fi="Arvostava, inhimillinen ja yksilöllinen kohtaaminen tukee potilasta", title_en="Respectful, humane and individual encounters support the patient"),
    dict(id="1.3", title_fi="Selkeä ja saavutettava terveysviestintä sekä terveyslukutaidon vahvistaminen", title_en="Clear and accessible health communication and stronger health literacy"),
    dict(id="2.5", title_fi="Syövät havaitaan aiempaa varhaisemmassa vaiheessa kaikkialla Suomessa", title_en="Cancers are detected at an earlier stage everywhere in Finland"),
    dict(id="3.1", title_fi="Kansalliset hoitosuositukset ja hoitoketjut ohjaavat yhdenvertaista hoitoa", title_en="National treatment guidelines and care pathways steer equal care"),
    dict(id="3.2", title_fi="Kansallisen syövänhoidon laaturekisteri ja systemaattinen tulosten seuranta", title_en="National cancer care quality register and systematic follow-up of results"),
    dict(id="3.5", title_fi="Riittävä ja osaava henkilöstö varmistaa vaikuttavan hoidon", title_en="Sufficient and skilled staff ensure effective care"),
    dict(id="4.1", title_fi="Kansallinen terveyden tietovaranto ja kehittynyt analytiikka tukevat päätöksentekoa", title_en="A national health data repository and advanced analytics support decisions"),
    dict(id="4.3", title_fi="Suomi on yksilöllisen lääketieteen edelläkävijä", title_en="Finland is a forerunner in personalised medicine"),
]


def build():
    areas_out, overview_areas = {}, []
    for a in AREAS:
        aid = a["id"]
        pop = POP_K[aid] * 1000
        rem = REMOTE.get(aid, 0.4)
        drivers = step_drivers(aid)
        steps, total = [], 0
        for sid, label_en, label_fi, nat, kind, method in STEPS:
            mult = 0.82 + 0.42 * h(aid, sid) + (0.22 * rem if sid in ("patient", "treatment", "diagnosis") else 0.08 * rem)
            med = max(4, round(nat * mult))
            spread = {"measured": 0.08, "estimated": 0.24, "assumption": 0.4}[kind]
            steps.append({"id": sid, "label_en": label_en, "label_fi": label_fi,
                          "days": {"median": med, "lo": max(1, round(med * (1 - spread))), "hi": round(med * (1 + spread))},
                          "national_days": nat, "kind": kind, "method_en": method, "drivers": drivers[sid]})
            total += med
        lo = round(sum(s["days"]["lo"] for s in steps) * 1.06)
        hi = round(sum(s["days"]["hi"] for s in steps) * 0.95)
        rate = round(38 + 16 * h(aid, "mort") + 10 * rem, 1)
        deaths = round(rate * pop / 100000)
        cases = round(deaths * 1.18)
        coverage = round(0.42 + 0.4 * h(aid, "cov") - 0.12 * rem + (0.1 if aid != "91" else -0.2), 2)
        coverage = min(0.92, max(0.18, coverage))
        indicators = [d for s in steps for d in s["drivers"]] + [
            {"indicator": "lung_deaths_per_100k", "label_en": "Lung cancer deaths per 100,000 residents", "value": rate, "national": 44.0,
             "unit": "per 100,000", "period": "2019-2023", "source_id": "fx_fcr", "kind": "measured"},
            {"indicator": "pop_total", "label_en": "Population", "value": pop, "national": 5600000, "unit": "persons", "period": "2025",
             "source_id": "fx_statfi", "kind": "measured"},
        ]
        used = sorted({d["source_id"] for d in indicators} | {"fx_literature", "fx_model"})
        areas_out[aid] = {
            "area": {**a, "pop_total": pop, "lung_cases_per_year": cases, "deaths_per_year": deaths},
            "steps": steps, "indicators": indicators, "data_gaps": DATA_GAPS,
            "sources": {k: SOURCES[k] for k in used},
        }
        worst = max(steps, key=lambda s: s["days"]["median"] - s["national_days"])
        overview_areas.append({"id": aid, "short_en": a["short_en"], "short_fi": a["short_fi"],
                               "total_days": {"median": total, "lo": lo, "hi": hi}, "worst_step": worst["id"],
                               "deaths_per_year": deaths, "lung_deaths_per_100k": rate, "data_coverage": coverage,
                               "pop_total": pop})
    best = min(x["total_days"]["median"] for x in overview_areas)
    overview_areas.sort(key=lambda x: -x["total_days"]["median"])
    for i, x in enumerate(overview_areas, 1):
        x["rank"] = i
        x["excess_days_vs_best"] = x["total_days"]["median"] - best
    nat_total = sum(s[3] for s in STEPS)

    # National pseudo-area: population-weighted step days.
    tot_pop = sum(v["area"]["pop_total"] for v in areas_out.values())
    fi_steps = []
    for i, (sid, label_en, label_fi, nat, kind, method) in enumerate(STEPS):
        w = sum(v["steps"][i]["days"]["median"] * v["area"]["pop_total"] for v in areas_out.values()) / tot_pop
        spread = {"measured": 0.06, "estimated": 0.2, "assumption": 0.35}[kind]
        fi_steps.append({"id": sid, "label_en": label_en, "label_fi": label_fi,
                         "days": {"median": round(w), "lo": round(w * (1 - spread)), "hi": round(w * (1 + spread))},
                         "national_days": round(w), "kind": kind, "method_en": method,
                         "drivers": [{**d, "value": d["national"]} for d in step_drivers("FI")[sid]]})
    fi_total = sum(s["days"]["median"] for s in fi_steps)
    for v in areas_out.values():
        for s, f in zip(v["steps"], fi_steps):
            s["national_days"] = f["days"]["median"]
    areas_out["FI"] = {
        "area": {"id": "FI", "name_fi": "Suomi", "name_sv": "Finland", "name_en": "Finland", "short_fi": "Suomi", "short_en": "Finland",
                 "yta": None, "pop_total": tot_pop, "lung_cases_per_year": sum(v["area"]["lung_cases_per_year"] for v in areas_out.values()),
                 "deaths_per_year": sum(v["area"]["deaths_per_year"] for v in areas_out.values())},
        "steps": fi_steps,
        "indicators": [d for s in fi_steps for d in s["drivers"]], "data_gaps": DATA_GAPS, "sources": SOURCES,
    }
    overview = {
        "national": {
            "total_days": {"median": fi_total, "lo": round(fi_total * 0.86), "hi": round(fi_total * 1.2)},
            "benchmarks": [{"country": "Finland", "days": fi_total, "source_id": "fx_model", "kind": "estimated"},
                           {"country": "Denmark", "days": 78, "source_id": "fx_literature", "kind": "measured"},
                           {"country": "Sweden", "days": 97, "source_id": "fx_literature", "kind": "measured"}],
            "survival": [{"country": c, "sex": s, "value": v, "source_id": "fx_nordcan", "kind": "measured", "period": "2018-2022"}
                         for c, s, v in [("Finland", "men", 14.1), ("Finland", "women", 21.5), ("Denmark", "men", 20.3),
                                         ("Denmark", "women", 27.0), ("Sweden", "men", 20.6), ("Sweden", "women", 27.9)]],
            "steps": [{"id": s["id"], "label_en": s["label_en"], "days": s["days"]["median"]} for s in fi_steps],
        },
        "areas": overview_areas,
    }
    interventions = []
    for iv in INTERVENTIONS:
        iv = dict(iv)
        iv["cost"] = {**iv["cost"], "eur_setup": round(iv["cost"]["eur_setup"] * 2.6, -3), "eur_per_year": round(iv["cost"]["eur_per_year"] * 2.6, -2), "basis": "Sample cost set for the demo; editable", "source_url": None, "kind": "assumption"}
        iv["evidence"] = [{"claim": f"{iv['name_en']}: sample effect {iv['effect']['value']} ({iv['effect']['metric']})",
                           "quote": None, "url": "https://pubmed.ncbi.nlm.nih.gov/", "year": None, "design": None, "n": None,
                           "verified": False, "source_id": f"fx_ev_{iv['id']}"}]
        iv.setdefault("null_results", [])
        interventions.append(iv)

    out = {"overview.json": overview, "areas.json": areas_out, "interventions.json": interventions, "sources.json": SOURCES,
           "roadmap_measures.json": ROADMAP,
           "parameters.json": {"hazard_per_4_weeks": {"value": 1.04, "lo": 1.02, "hi": 1.07, "url": None, "quote": None, "verified": False, "note": NOTE},
                               "attributable_share": {"value": 0.6, "note": NOTE}}}
    for name, obj in out.items():
        (HERE / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    print("wrote", ", ".join(out), "| national total", fi_total, "| range",
          min(x["total_days"]["median"] for x in overview_areas), max(x["total_days"]["median"] for x in overview_areas))


if __name__ == "__main__":
    build()
