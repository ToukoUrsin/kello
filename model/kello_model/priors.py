"""Every assumption the model makes about SIZE of effect, in one readable place.

NONE of these are fitted. Finland publishes no county-level lung cancer step durations,
so there is no outcome to fit against. Each elasticity is a prior: "a county one standard
deviation worse on this indicator has a step that is about exp(mean) times longer",
drawn as Normal(mean, sd) in the Monte Carlo. sd is as large as the mean on purpose:
the prior allows no effect and even the opposite sign.

sign: +1 = a higher indicator value means a longer step; -1 = shorter.
"""

# (indicator, step, sign, mean, sd, rationale)
ELASTICITIES = [
    # --- patient: first symptom -> first primary care contact
    ("forgone_care_due_to_money_pct", "patient", +1, 0.05, 0.05, "People who skip care for cost reasons present later."),
    ("daily_smokers_pct", "patient", +1, 0.04, 0.04, "Smokers tend to normalise a cough and wait longer before seeking help."),
    ("low_income_rate_pct", "patient", +1, 0.03, 0.04, "Lower income is associated with later presentation."),
    ("education_level_index", "patient", -1, 0.04, 0.04, "Lower education carries higher odds of stage IV at diagnosis (Finnish registry study)."),
    ("crc_screening_participation_pct", "patient", -1, 0.04, 0.04, "Proxy for how readily residents take up health services."),
    ("sparse_rural_pop_pct", "patient", +1, 0.03, 0.04, "Long distances to the health centre raise the threshold to seek care."),
    # --- primary: first contact -> referral
    ("primary_care_wait_over_7d_pct", "primary", +1, 0.10, 0.08, "Each GP visit in the work-up waits in the same queue."),
    ("primary_care_wait_over_3m_pct", "primary", +1, 0.05, 0.05, "Very long GP waits mark the worst-served areas."),
    ("nurse_wait_over_7d_pct", "primary", +1, 0.03, 0.04, "Nurse triage is often the first contact."),
    ("continuity_of_care_coci", "primary", -1, 0.05, 0.05, "Seeing the same doctor makes a persisting symptom easier to recognise."),
    ("gp_vacancy_pct", "primary", +1, 0.05, 0.05, "Unfilled GP posts mean less continuity and slower work-up."),
    # --- referral: referral -> first specialist visit
    ("pulmonology_assessment_over_90d_pct", "referral", +1, 0.12, 0.08, "Direct measure of the pulmonology first-visit queue (all diagnoses)."),
    ("pulmonology_referrals_handled_over_21d_pct", "referral", +1, 0.10, 0.08, "Slow referral processing delays every booking."),
    ("specialist_wait_over_6m_per_10k", "referral", +1, 0.04, 0.04, "General congestion of specialist care in the area."),
    ("specialist_wait_median_days", "referral", +1, 0.05, 0.05, "General speed of specialist access in the area."),
    # --- diagnosis: first specialist visit -> diagnosis
    ("pulmonology_queue_over_90d_pct", "diagnosis", +1, 0.08, 0.07, "Pulmonology procedure queue (bronchoscopy etc., all diagnoses)."),
    ("km_to_university_hospital", "diagnosis", +1, 0.06, 0.05, "PET-CT, EBUS and MDT are centralised; distance adds scheduling time."),
    ("lung_mdt_recorded_pct", "diagnosis", -1, 0.04, 0.04, "A recorded MDT decision is a marker of an organised diagnostic process."),
    ("lung_stage_known_pct", "diagnosis", -1, 0.05, 0.05, "Complete staging is a marker of a working diagnostic process."),
    # --- treatment: diagnosis -> treatment start. NOT USED while the Cancer Registry's measured medians are available
    # (step 5 is measured per collaborative area); kept as the fallback if those rows are missing.
    ("oncology_queue_over_90d_pct", "treatment", +1, 0.08, 0.07, "Oncology treatment queue (all cancers)."),
    ("oncology_assessment_over_90d_pct", "treatment", +1, 0.06, 0.06, "Oncology first-visit queue (all cancers)."),
    ("oncology_referrals_handled_over_21d_pct", "treatment", +1, 0.05, 0.05, "Slow handling of referrals to oncology."),
    ("km_to_university_hospital", "treatment", +1, 0.03, 0.04, "Thoracic surgery is done in university hospitals."),
    ("km_to_radiotherapy", "treatment", +1, 0.06, 0.05, "Radiotherapy needs daily travel; distance delays start."),
]

# Indicator key aliases: if the data agent names a key differently, map it here.
ALIASES = {
    "km_to_university_hospital": ["km_to_univ_hospital", "distance_to_university_hospital_km"],
    "km_to_radiotherapy": ["km_to_radiotherapy_unit", "distance_to_radiotherapy_km"],
    "lung_stage_known_pct": ["lung_stage_recorded_pct"],
    "lung_histology_defined_pct": ["lung_histology_known_pct", "lung_morphology_verified_pct"],
}

# County multiplier on a step is kept inside this band (shrinkage: no county is declared
# more than 80% slower or 40% faster than the country on indicators alone).
MULT_LO, MULT_HI = 0.6, 1.8
Z_CLIP = 2.5

# Patient-to-patient spread of each step (sigma of the lognormal), assumption.
SIGMA_PATIENT = {"patient": 0.9, "primary": 0.8, "referral": 0.6, "diagnosis": 0.6, "treatment": 0.5}

# Capacity-limited steps: share of the step that is waiting for a slot (the rest is handling
# time: reading, deciding, booking). Assumption.
QUEUE_SHARE = {"referral": 0.7, "diagnosis": 0.6}

# Two interventions on the same step do not add up: the k-th largest counts for 0.7**k of itself.
DIMINISHING = 0.7

# How much a day saved in each step counts for mortality. Hanna et al. measured delay from
# diagnosis/decision to treatment, so only those days count in full. Earlier days count half
# (assumption; the evidence for pre-diagnosis delay is observational and confounded).
DELAY_WEIGHT = {"patient": 0.5, "primary": 0.5, "referral": 1.0, "diagnosis": 1.0, "treatment": 1.0}

# Screening-type effects
STAGE_SHIFT_DISCOUNT = 0.5   # lead-time and overdiagnosis: only half the naive survival gain is counted
MORTALITY_RR_REACH = 0.02    # default share of an area's lung cancer deaths arising among people a mortality_rr measure reaches
MAX_SHARE_OF_DEATHS = 0.5    # hard cap: no plan may claim more than half of an area's lung cancer deaths

ANNUALISE_YEARS = 5          # setup cost spread over five years
LOW_CONFIDENCE_WEIGHT = 0.5  # optimiser ranks low-confidence interventions at half their modelled value
# v3: the rule that kept 25% of a budget for pathway-shortening measures is removed. Every rule the optimiser
# applies is listed in words in its output (rules_en).

# ---- v3: who gets treated to cure
# A curative_share_pp measure adds effect/100 x patients per year, times an applicability factor:
#  - measures that bring the university hospital's team to the county (video MDT, surgeon second opinion) count only
#    where the county's own hospital is not a university hospital. Assumption from the collaborative-area structure:
#    Helsinki and the four Uusimaa counties are served by HUS; Southwest Finland, Pirkanmaa, North Savo and
#    North Ostrobothnia host Tyks, Tays, KYS and OYS.
#  - travel support is scaled by the county's distance to the university hospital (km_to_university_hospital):
#    0 at 50 km, full at 200 km.
UNIVERSITY_SERVED = {"90", "01", "02", "03", "04", "05", "08", "13", "19"}
NEEDS_REMOTE_UNIVERSITY_TEAM = {"video_mdt_stage1_3", "surgeon_second_opinion"}
DISTANCE_SCALED = {"travel_accommodation_support": (50.0, 200.0)}
# Deaths within five years avoided per extra patient treated with curative intent. Read from parameters.json
# (curative_access.deaths_avoided_per_extra_curative_patient); this is the fallback. An assumption, not a causal estimate.
DEATHS_PER_EXTRA_CURATIVE = (0.15, 0.05, 0.30)
# Ceiling on what the access measures can add in a county: this share of its measured shortfall to the best quarter of
# counties. The other half is left for what these measures do not touch (stage at diagnosis, other illness, patient
# choice). Assumption: no public table splits a county's shortfall by reason.
REACHABLE_SHARE_OF_SHORTFALL = 0.5
# Low-dose CT screening: people screened per 100,000 residents and their lung cancer deaths per 1,000 person-years
# without screening. Read from parameters.json (screening); these are the fallbacks.
SCREEN_PARTICIPANTS_PER_100K = (1000.0, 600.0, 1400.0)
SCREEN_BASELINE_DEATHS_PER_1000PY = (3.30, 2.5, 4.1)
SCREENING_BY_PARTICIPANTS = {"ldct_screening"}
# Measure bought first where the care path carries a recording flag (it adds no patients; see rules_en).
RECORDING_AUDIT_ID = "recording_audit"
RECORDING_FLAG_STAGES = ("no_record", "drug_therapy")

# Interventions that reach only some patients. `all` = share of all patients whose pathway shortens;
# `curative` = share of curative-intent patients it reaches (only these count for deaths avoided).
# The evidence file gives the group in words only, so the shares are our assumptions.
APPLIES = {
    "ebus_capacity": {"all": 0.45, "curative": 0.9, "why": "suspected stage I-IIIA only: nearly all curative candidates"},
    "reflex_molecular": {"all": 0.6, "curative": 0.3,
                         "why": "non-small cell lung cancer whose first treatment waits for the biomarker result: advanced disease, "
                                "and stage II-III patients whose perioperative or post-chemoradiotherapy drug depends on EGFR, ALK or PD-L1"},
    "liquid_biopsy_first": {"all": 0.3, "curative": 0.0, "why": "advanced non-squamous NSCLC only"},
}
# mortality_rr interventions: share of the area's lung cancer deaths arising among people the measure reaches.
# (value, why, lo, hi). Screening is NOT here: it is counted from the people screened (SCREENING_BY_PARTICIPANTS).
REACH = {
    "smoking_cessation_at_diagnosis": (0.013, "deaths among curative-intent patients (about 15% of deaths) x 35% still smoking "
                                              "x 25% who quit because of the programme", 0.006, 0.02),
}
# Demand-side measures (flag patients sooner). Alone they do nothing in the model: the flagged patient
# waits in the same queue, which is what LungIMPACT measured. The effect they have ONCE capacity is free
# has not been trialled; this is our assumption (share of the step removed: value, lo, hi).
DEMAND_NOMINAL = {
    "ai_cxr_triage_alone": (0.10, 0.0, 0.20),
    "ai_cxr_triage": (0.10, 0.0, 0.20),
}


# Value-for-money stop rule of the optimiser. An assumption: Finland has no official threshold. EUR 1,000,000 a year per death
# avoided a year is roughly EUR 100,000 per life-year if ten life-years are gained per death avoided. Without a stop rule the
# greedy plan spends leftover budget on anything with a gain above zero (for example EUR 110,000 for 0.01 deaths avoided).
MAX_EUR_PER_DEATH_AVOIDED = 1_000_000
