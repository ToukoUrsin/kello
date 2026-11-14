# Kello — shared contract (all agents read this first)

**Product.** "Kello" (the clock): a map of Finland that shows, per wellbeing services county, where lung cancer patients lose time between first symptom and treatment start, and what a given budget should buy to fix it. Junction 2026, AstraZeneca challenge "Equal Care Across Finland". Judges are oncology / medical affairs / marketing people; a non-technical decision-maker must get the point in under 2 minutes. Judging: actionability 30, insight 25, data quality and transparency 20, execution 15, clarity 10.

**Hard rules**
- Public aggregate data only. No patient-level data.
- Every number shown carries `kind`: `measured` (straight from a public source), `estimated` (our model, with method and interval), or `assumption` (e.g. a cost we set; editable). Never present an estimate as a measurement.
- Every claim has a source URL that was actually opened. If you could not open or verify something, record `verified: false` — do not fill gaps from memory.
- No causal claims from county-level aggregates. No individual risk prediction.
- UI language: English, with the county plan available in Finnish and English.
- Do not run `git` (the lead commits). Do not touch other agents' directories. Do not print secret values; provide them through the environment.
- Python: `uv`, Python 3.12, one venv at `.venv` (create with `uv venv` if missing; `uv pip install` into it). Heavy jobs: prefix `nice -n 10`.
- Claude calls use `ANTHROPIC_API_KEY`; optionally set `ANTHROPIC_BASE_URL` for a gateway. Load the relevant provider documentation before writing Claude code.

**Layout** (repository root)
- `data/raw/<source>/` downloads (gitignored) · `data/processed/` clean data · `data/evidence/` literature · `data/model/` model outputs
- `pipeline/` data scripts (owner: data agent) · `model/kello_model/` simulation package (owner: model) · `app/server/` FastAPI · `app/web/` frontend · `science/` Claude Science work · `res/` the challenge PDFs as text (`res/strategy/s.txt`, `res/roadmap/r.txt`)

**Areas.** `data/processed/areas.json` and `areas.geojson` already exist: 23 areas, `id` = Statistics Finland code as string (`"01"`..`"21"`, `"90"` Helsinki, `"91"` Åland), `yta` = university hospital collaborative area (HUS/TYKS/TAYS/KYS/OYS/ALAND; from memory, data agent verifies). `"FI"` = whole country.

**Pathway steps (lung cancer), fixed ids**
1. `patient` — first symptom → first primary care contact
2. `primary` — first primary care contact → referral to specialist care
3. `referral` — referral → first specialist visit
4. `diagnosis` — first specialist visit → diagnosis and treatment decision (imaging, biopsy, molecular tests, MDT)
5. `treatment` — treatment decision → treatment start

**v2 changes (13 Nov, 22:40) — measured first**
- Step 4 `diagnosis` now means first specialist visit → diagnosis; step 5 `treatment` now means diagnosis → treatment start, because that is what the Cancer Registry measures (median days by collaborative area and modality, 2018–mid 2022; national 36–38 days). Step 5 is `kind:"measured"` with `measured_level:"collaborative_area"`; steps 1–4 stay `estimated`.
- The product leads with MEASURED county gaps and shows the modelled clock second. `data/processed/gemini_extracted.jsonl` (966 rows read by Gemini from registry reports; fields `area_id` (also `yta:HUS` etc. and `FI`), `indicator, value, unit, period, sex, source_url, page, quote, read_by, confidence, verified`) is a first-class input.
- `GET /api/overview`: `national.headline_measured:[{key,label_en,value_low,area_low,value_high,area_high,national,unit,period,source_url,page,read_by}]`; each area adds `measured:{curative_intent_pct, no_treatment_record_pct, one_year_survival_pct, surgery_pct, lung_incidence_per_100k, lung_deaths_per_100k_65plus, gp_wait_over_7d_pct, pulm_queue_over_90d_pct, dx_to_treatment_days}` (each `{value, national, rank, period, source_id|source_url, page?, read_by?, level?}` or null), `patients_per_year`, `curative_gap_patients_per_year` (arithmetic: patients × (national top-quartile share − county share), floor 0, with `note_en`).
- `GET /api/areas/{id}` adds `measured_gaps:[{indicator,label_en,value,national,best,best_area,worst,rank,unit,period,direction,source_url|source_id,page,quote,read_by,gap_patients_per_year?,note_en}]` ordered by how far the county is from the national value, and `consistency_check` (how the estimated clock correlates with measured outcomes across counties; stated as a check, not validation).
- `POST /api/optimize`: `not_chosen[].reason_en` must be the real reason (`"no effect without added CT capacity (LungIMPACT 2026)"`, `"weak evidence"`, `"prerequisite missing: …"`, `"budget"`), and `chosen` is ordered with `rank`; national scope returns non-zero `days_saved_weighted` when anything is bought.

**Data files**
- `data/processed/sources.json`: `{source_id: {title, publisher, url, api_call, retrieved_at, licence, notes}}`
- `data/processed/indicators.jsonl`: one row per value: `{area_id, indicator, label_en, label_fi, value, unit, period, sex?, source_id, kind:"measured", note?}`. `indicator` is a stable snake_case key (e.g. `primary_care_wait_over_7d_pct`, `pulmonology_queue_over_90d_pct`, `lung_deaths_per_100k`, `lung_incidence_per_100k`, `lung_stage_known_pct`, `lung_curative_intent_pct`, `crc_screening_participation_pct`, `pop_total`, `pop_65plus_pct`, `km_to_university_hospital`). `data/processed/indicators_catalog.json` describes each key (definition, direction, which pathway step it informs).
- `data/evidence/interventions.json`: list of `{id, name_en, name_fi, step, what_en, what_fi, effect:{metric:"days"|"relative_days"|"stage_shift_pp"|"mortality_rr", value, lo, hi}, evidence:[{claim, quote, url, year, design, n, verified}], null_results:[{claim,url,year}], cost:{eur_setup, eur_per_year, scales_with:"county"|"per_100k_pop"|"per_patient", basis, source_url, kind}, roadmap_measure, owner_fi, owner_en, prerequisite_en, confidence:"high"|"medium"|"low"}`
- `data/evidence/parameters.json`: national baseline days per step with source, Nordic benchmarks, delay→mortality hazard per 4 weeks, stage-specific survival, target times (THL Ohjaus 21/2016), each with `{value, lo, hi, url, quote, verified}`.
- `data/model/pathways.json`, `data/model/plans.json`: precomputed model outputs in the API shapes below.

**API (FastAPI, port 8742, all JSON)**
- `GET /api/overview` → `{national:{total_days:{median,lo,hi}, benchmarks:[{country,days,source_id}], survival:[{country,sex,value,source_id}]}, areas:[{id, short_en, short_fi, total_days:{median,lo,hi}, excess_days_vs_best, worst_step, deaths_per_year, lung_deaths_per_100k, data_coverage, rank}]}`
- `GET /api/areas/{id}` → `{area, steps:[{id, label_en, days:{median,lo,hi}, national_days, kind, method_en, drivers:[{indicator,label_en,value,national,unit,period,source_id,kind}]}], indicators:[...], data_gaps:[{what_en, why_it_matters_en, who_could_publish_en}], sources:{...}}`
- `POST /api/simulate` `{area_id, interventions:[id], seed?}` → `{baseline:{total_days,steps}, scenario:{total_days,steps}, days_saved:{median,lo,hi}, deaths_avoided_per_year:{median,lo,hi}, cost:{eur_setup,eur_per_year}, per_intervention:[{id,days_saved,deaths_avoided_per_year,cost,note_en}], n_runs}`
- `POST /api/optimize` `{scope: area_id|"FI", budget_eur}` → `{chosen:[{intervention_id, area_id, eur, days_saved, deaths_avoided_per_year, eur_per_death_avoided, confidence}], totals:{eur, deaths_avoided_per_year:{median,lo,hi}, days_saved_weighted}, frontier:[{budget_eur, deaths_avoided_per_year}], not_chosen:[{intervention_id, reason_en}]}`
- `GET /api/plan/{area_id}?budget_eur=&lang=fi|en` → `{title, markdown, claims:[{text, source_ids}], review:{removed:[...], checked_by}}` (Claude writes, a reviewer pass strips unsourced sentences; cached on disk)
- `POST /api/verify` `{intervention_id, area_id?}` → `{question, verdict:"supported"|"mixed"|"contradicted"|"not_found", summary_en, sources:[{url,title,quote,fetched_at}], checked_at}` (live Oxylabs search + scrape at request time)
- `POST /api/read-report` `{url}` or file upload → `{document, extracted:[{indicator_guess, label, area, value, unit, period, page, quote}], model}` (Gemini reads a report or chart that has no API)
- `GET /api/sources` → sources.json plus evidence URLs

**v3 changes (14 Nov, 00:30) — "who gets treated to cure"**

Why: four simulated judges scored v2 64–71/100 and all said the same thing: the headline is the measured cure-share gap, the product is named after a clock, and the plan buys screening and a campaign. Three stories. v3 has one: *where a county loses patients between diagnosis and curative treatment, and what closes that gap*. The estimated symptom→treatment clock stays, as a secondary "Time" view marked estimated; "days saved" is never a headline.

Ports: the public demo stays on **8742** (lead restarts it). Test on your own port: model none, app agent **8743**, integrations agent **8744** (`PORT=8743 app/run.sh`). Never kill a server you did not start. `app/server/main.py` is shared by two agents: edit it with small targeted edits only, never rewrite the file.

*Measured care path (model: `kello_model.api.care_path(area_id)`, also inside `area()`; precomputed to `data/model/care_path.json`)*
```
{"area_id", "patients_per_year", "period",
 "stages":[{"id","label_en","label_fi","value","unit","n","lo","hi","national","best","best_area","worst","rank","of",
            "outside_limits": "none|95|99.8", "direction":"higher_better|lower_better|context",
            "level":"county|collaborative_area", "kind":"measured","source_url","page","quote","read_by","note_en"}],
 "main_leak": {"stage_id","label_en","sentence_en","sentence_fi","patients_per_year"},
 "missing_patients": {"vs":"national|top_quartile","per_year","lo","hi",
                      "by_modality":[{"id":"surgery|radiotherapy|other","per_year","note_en"}], "note_en"},
 "expected": {"method_en","adjusted_for":[...],"observed_pct","expected_pct","ratio","lo","hi","not_adjusted_for":[...]},
 "artefact_flags":[{"stage_id","text_en","text_fi"}]}
```
Stage ids, in order: `staged` (stage recorded), `mdt` (MDT recorded), `curative` (curative-intent treatment), `surgery`, `radiotherapy`, `drug_therapy`, `life_prolonging`, `symptomatic_only`, `no_record`, `time_to_treatment` (days, collaborative area), `alive_1y`. Use only stages the data has for that county; never fill. Intervals on shares are exact binomial from the county n; funnel limits around the national share.

*Interventions (`data/evidence/interventions.json`)* add fields: `owner_level:"county"|"collaborative_area"|"national"`, `first_step_en/fi` (what the owner does this week), `kpi:{indicator, label_en, baseline_from:"care_path.<stage>", target_rule_en}`, `targets_stage` (care-path stage id), effect metric may now be `curative_share_pp`. New treatment-access measures must each have evidence that was opened and quoted (same build check as before).

*Optimiser* `POST /api/optimize {scope, budget_eur, objective:"curative"|"deaths"|"gap", exclude?:[intervention_id]}` →
```
{"objective", "chosen":[{intervention_id, area_id, rank, eur, owner_level, targets_stage,
     extra_curative_patients_per_year:{median,lo,hi}, deaths_avoided_per_year:{median,lo,hi},
     eur_per_extra_curative_patient, eur_per_death_avoided, confidence, first_step_en, kpi:{label_en, baseline, target, by_year}}],
 "totals":{eur, extra_curative_patients_per_year:{median,lo,hi}, deaths_avoided_per_year:{median,lo,hi},
           curative_share_after_pct, gap_closed_pct},
 "needs_national_decision":[{...same shape, not counted in the county's budget...}],
 "not_chosen":[{intervention_id, reason_code, reason_en}],
 "rules_en":[...every rule the optimiser applies, in words...],
 "saturated": bool, "saturation_note_en",
 "goal3_link": {"lung_deaths_per_year","deaths_avoided_share_pct","survival_gap_pp","note_en"},
 "frontier":[{budget_eur, extra_curative_patients_per_year, deaths_avoided_per_year}]}
```
Every point estimate lies inside its own interval (same quantity, same conditioning). Card, plan and note use the same number. County default objective is `curative`; national default is `gap` (allocate where the measured shortfall is largest).

*Goal 3 scoreboard* `GET /api/goal3` → `data/processed/goal3.json` reduced for the UI: `survival_targets`, `mortality_trend`, `county` rows for `incidence_asr` and `mortality_asr` by cancer (lung, pancreas, liver, all; sex all), `treated_within_target`. The map can switch cancer for these two metrics. Age-standardised mortality from the registry replaces the old "deaths per 100,000 aged 65+" everywhere.

*Live web check* `POST /api/verify {intervention_id, area_id?}` adds: `in_use_here:"yes"|"planned"|"no_evidence"`, `in_use_quote`, `effect_check:"supports"|"weaker"|"contradicts"|"not_found"`, `trace:[{step, tool:"oxylabs /v1/search"|"oxylabs /v1/scrape"|"claude", input, result_en, ms}]`, `rounds`. The check is a loop: it searches again on the part of the question that is still unanswered (max 3 rounds, about 60 s). The app keeps the latest check per (intervention, area) in `app/server/cache/` and shows it on the action card and in the plan; `in_use_here:"yes"` offers "re-plan without it" (optimize with `exclude`).

*Report reader* results always return `notes_en` (what Gemini said about the document, shown in the UI), persist on disk by URL, and each extracted row can be "added to Kello" (`POST /api/read-report/keep {url, row_index}` appends to `data/processed/reader_added.jsonl` with `kind:"measured", verified:false, read_by`), after which it appears in Sources & method as user-added, unverified.
