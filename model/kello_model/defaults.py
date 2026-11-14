"""Built-in fallbacks, used ONLY when the evidence/data agents' files are absent.

Everything here is provisional. Each entry is tagged `kind: "assumption"` or carries the
provisional source it came from. When `data/evidence/parameters.json`,
`data/evidence/interventions.json` or `data/processed/indicators.jsonl` exist they
supersede these values (see inputs.py); `Inputs.provenance` records which were used.
"""

PROV = "provisional: earlier desk research, not re-verified by this package"
YLE = "Unpublished four-city study reported by Yle 2026 (" + PROV + ")"

# National median days per step. The 155-day total and the 50/41/58 split are reported;
# the split of the 58 specialist-care days into referral/diagnosis/treatment is OUR assumption.
PARAMETERS = {
    "steps": {
        "patient": {"value": 56, "lo": 45, "hi": 70, "kind": "measured", "source": YLE, "url": None, "verified": False},
        "primary": {"value": 41, "lo": 33, "hi": 50, "kind": "measured", "source": YLE, "url": None, "verified": False},
        "referral": {"value": 16, "lo": 10, "hi": 22, "kind": "assumption", "url": None, "verified": False,
                     "source": "58 specialist-care days (Yle 2026) split 16/22/20 by assumption"},
        "diagnosis": {"value": 22, "lo": 15, "hi": 30, "kind": "assumption", "url": None, "verified": False,
                      "source": "58 specialist-care days (Yle 2026) split 16/22/20 by assumption"},
        "treatment": {"value": 20, "lo": 14, "hi": 27, "kind": "assumption", "url": None, "verified": False,
                      "source": "58 specialist-care days (Yle 2026) split 16/22/20 by assumption"},
    },
    # symptom -> treatment, days
    "benchmarks": [
        {"country": "Finland", "days": 155, "source_id": "default_yle_2026", "kind": "measured", "verified": False},
        {"country": "Sweden", "days": 107, "source_id": "default_yle_2026", "kind": "measured", "verified": False},
        {"country": "Denmark", "days": 67, "source_id": "default_yle_2026", "kind": "measured", "verified": False},
    ],
    "step_floors": {},  # per-step best Nordic benchmark, if the evidence agent has one
    # Hanna et al. BMJ 2020: mortality hazard ratio per 4-week delay (surgery 1.06-1.08, radical RT 1.09)
    "hazard_per_4w": {"value": 1.07, "lo": 1.06, "hi": 1.09, "source": "Hanna et al., BMJ 2020 (" + PROV + ")",
                      "url": "https://www.bmj.com/content/371/bmj.m4087", "verified": False},
    # 5-year survival used for stage-shift and for the curative-intent group
    "survival_5y": {
        "early": {"value": 0.55, "lo": 0.45, "hi": 0.65, "kind": "assumption",
                  "source": "stage I-II lung cancer 5-year survival, round figure"},
        "late": {"value": 0.07, "lo": 0.04, "hi": 0.10, "kind": "assumption",
                 "source": "stage III-IV lung cancer 5-year survival, round figure"},
        # never in the evidence file (stage II-III survival was not found in an opened source):
        "curative": {"value": 0.45, "lo": 0.35, "hi": 0.55, "kind": "assumption",
                     "source": "5-year survival of patients treated with curative intent (stage I-IIIA mix); assumption"},
        "shift_from": {"value": 0.30, "lo": 0.15, "hi": 0.45, "kind": "assumption",
                       "source": "5-year survival patients would have had without the shift to stage I (mostly stage II-III, not IV); assumption"},
    },
    "curative_share": {"value": 0.27, "lo": 0.22, "hi": 0.32, "source": "about 27% receive curative-intent treatment (" + PROV + ")",
                       "verified": False},
    "national": {"incidence": {"value": 2900, "source": PROV}, "deaths": {"value": 2300, "source": PROV}},
    "survival": [],  # [{country, sex, value, source_id}] for the overview, only if the evidence file has it
    # Measured hospital times. `steps` = the pathway steps the measured interval spans.
    "measured_hospital_times": [
        {"area_id": "05", "hospital": "Tyks", "steps": ["referral", "diagnosis", "treatment"], "days": 35,
         "period": "2025-01..2025-06", "what_en": "referral to start of chemotherapy", "url": None,
         "source": "Tyks, Jan-Jun 2025 (" + PROV + ")", "verified": False},
    ],
}

# Approximate populations (thousands, 2023), used only if indicators.jsonl has no pop_total.
POP_THOUSANDS = {
    "01": 99, "02": 205, "03": 490, "04": 285, "05": 490, "06": 211, "07": 170, "08": 540, "09": 205,
    "10": 158, "11": 125, "12": 130, "13": 248, "14": 162, "15": 273, "16": 190, "17": 177, "18": 67,
    "19": 418, "20": 70, "21": 176, "90": 675, "91": 30,
}
POP_NOTE = {"kind": "assumption", "source": "approximate 2023 populations from memory; replaced by pop_total when present"}


def _iv(id, name_en, name_fi, step, what_en, metric, value, lo, hi, setup, per_year, scales, confidence,
        mechanism, prerequisite_en="", requires=(), null_results=(), basis="round-figure cost assumption"):
    return {
        "id": id, "name_en": name_en, "name_fi": name_fi, "step": step, "what_en": what_en, "what_fi": "",
        # sign convention of the evidence file: days / relative_days are days SAVED (positive = faster)
        "effect": ({"metric": metric, "value": abs(value), "lo": min(abs(lo), abs(hi)), "hi": max(abs(lo), abs(hi))}
                   if metric in ("days", "relative_days") else {"metric": metric, "value": value, "lo": lo, "hi": hi}),
        "evidence": [{"claim": PROV, "url": None, "verified": False}],
        "null_results": list(null_results),
        "cost": {"eur_setup": setup, "eur_per_year": per_year, "scales_with": scales, "basis": basis,
                 "source_url": None, "kind": "assumption"},
        "roadmap_measure": "", "owner_fi": "", "owner_en": "", "prerequisite_en": prerequisite_en,
        "requires": list(requires), "mechanism": mechanism, "confidence": confidence, "kind": "assumption",
    }


INTERVENTIONS = [
    _iv("ct_capacity", "Extra CT slots reserved for suspected lung cancer", "Lisää TT-aikoja keuhkosyöpäepäilyille",
        "diagnosis", "Adds scanner hours and radiologist time so a CT is done within days of the first visit.",
        "relative_days", -0.30, -0.15, -0.45, 300_000, 400_000, "county", "medium", "capacity"),
    _iv("ai_cxr_triage", "AI chest X-ray triage", "Tekoäly keuhkokuvien priorisointiin", "diagnosis",
        "Software flags suspicious chest X-rays so they are read and sent to CT first.",
        "relative_days", -0.15, -0.05, -0.25, 50_000, 80_000, "county", "low", "demand",
        prerequisite_en="Needs added CT capacity; alone it did not shorten time to diagnosis (LungIMPACT 2026).",
        requires=["ct_capacity"],
        null_results=[{"claim": "AI chest X-ray triage without added CT capacity: no change in time to diagnosis",
                       "url": None, "year": 2026}]),
    _iv("pulm_clinic_capacity", "Extra pulmonology first-visit slots", "Lisää keuhkopoliklinikan ensikäyntiaikoja",
        "referral", "Adds clinic sessions so a referred patient is seen sooner.",
        "relative_days", -0.30, -0.15, -0.45, 0, 250_000, "county", "medium", "capacity"),
    _iv("fast_track_pathway", "Booked fast-track lung cancer pathway", "Keuhkosyövän nopea hoitopolku", "referral+diagnosis",
        "Danish-style package: pre-booked visits and tests with time targets and a pathway coordinator.",
        "relative_days", -0.25, -0.10, -0.40, 100_000, 200_000, "county", "medium", "process"),
    _iv("gp_direct_ct", "GP direct access to CT", "Suora TT-lähete perusterveydenhuollosta", "primary",
        "Primary care doctors order a CT directly for red-flag symptoms instead of X-ray then referral.",
        "days", -14, -7, -21, 20_000, 100_000, "county", "medium", "process"),
    _iv("nurse_navigator", "Nurse navigator", "Syöpähoitaja-koordinaattori", "diagnosis+treatment",
        "A named nurse books tests, chases results and keeps the patient moving.",
        "days", -7, -3, -12, 0, 140_000, "county", "medium", "process"),
    _iv("reflex_molecular_testing", "Reflex molecular testing", "Refleksinä tehtävä molekyylitestaus", "diagnosis",
        "The pathology lab starts molecular tests on its own as soon as NSCLC is confirmed.",
        "days", -8, -4, -14, 30_000, 1_500, "per_patient", "high", "process"),
    _iv("symptom_campaign", "Symptom awareness campaign", "Oirekampanja", "patient",
        "Public campaign: a cough lasting over three weeks needs a chest X-ray.",
        "days", -5, 0, -10, 0, 40_000, "per_100k_pop", "low", "process"),
    _iv("treatment_slots", "Extra oncology and radiotherapy slots", "Lisää onkologian ja sädehoidon aikoja", "treatment",
        "Adds treatment-start capacity after the treatment decision.",
        "relative_days", -0.20, -0.10, -0.30, 250_000, 300_000, "county", "low", "process"),
    _iv("ldct_screening", "Low-dose CT screening for heavy smokers", "Pieniannoksinen TT-seulonta", "screening",
        "Invites high-risk smokers aged 50-74 to low-dose CT.",
        "mortality_rr", 0.84, 0.76, 0.92, 200_000, 600_000, "per_100k_pop", "high", "screening"),
]
