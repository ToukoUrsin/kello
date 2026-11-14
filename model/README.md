# Kello model

One question: **where does a county lose lung cancer patients between diagnosis and curative treatment, and what
closes that gap?**

1. **Measured care path** (`api.care_path(area_id)`, `data/model/care_path.json`): Finnish Cancer Registry county
   counts for patients diagnosed 2019-2023. Nothing in it is modelled.
2. **What closes the gap** (`api.optimize(scope, budget_eur, objective, exclude)`): modelled. Every effect of a
   treatment-access measure is an assumption with a lower bound of zero, and says so.
3. **The clock** (symptom to treatment, `overview()` / `area()["steps"]` / `simulate()`): a secondary view. Only the
   last step is measured, per collaborative area. Days saved is never a headline number.

Nothing here is a causal claim. County figures describe areas, not why they differ.

## What is measured, estimated, assumed

| | What | Where it comes from |
|---|---|---|
| Measured | Care-path stages per county with counts n/N: stage recorded, MDT recorded, curative-intent treatment, surgery, drug therapy, life-prolonging, symptomatic only, no treatment on record, one-year survival; days from diagnosis to treatment per collaborative area | Registry quality report 2019-2023 and "Keuhkosyöpä Suomessa" (`data/evidence/registry_tables.json`, `gemini_extracted.jsonl`); each stage carries `source_url`, `page`, `quote`, `read_by` |
| Measured | Lung cancer deaths and cases a year, age-standardised incidence and mortality per county, 2020-2024 | Registry statistics via `data/processed/goal3.json` |
| Reported | National clock: 155 days in total, primary care 41, specialist care 58 | A four-city study reported by Yle; sample size not stated, so `kind: "reported"`, not measured |
| Arithmetic on measured values | Exact binomial 95% interval of each share; funnel limits (95%, 99.8%) around the national share; `missing_patients` = patients a year x (reference share - county share) | `carepath.py`; written out in `note_en` |
| Estimated | Observed vs expected curative share (below); clock steps 1-4 per county; everything a measure adds | this package |
| Assumption | Effect of every treatment-access measure; deaths avoided per extra patient treated to cure (0.15, range 0.05-0.30); the reachable half of a county's shortfall; which counties a remote university team serves; costs; the value limit of EUR 1,000,000 per death avoided | `data/evidence/*.json`, `priors.py`, one line of reasoning each |

### Care path

`stages[]` come in the contract order and only where the registry publishes them (Åland: none, 93 patients in
five years; never filled). `main_leak` is the stage where the county is furthest on the worse side of the national
share in units of chance variation, leaving out stages with a recording flag, with one plain sentence in English
and Finnish. `missing_patients` is against the national share (and `headroom` against the best quarter of
counties, 30.4%), split into surgery (measured operated share) and the rest (by subtraction: stereotactic
radiotherapy and chemoradiotherapy are not published per county). `artefact_flags` mark counties where "no
treatment on record" is far above and life-prolonging treatment far below the national share, or where almost no
drug therapy is recorded (Southwest Finland 0.9% against 25%): part of the gap may be recording, not care.

### Observed vs expected (`care_path.expected`)

The only adjustment public data supports is ecological: a quasi-binomial regression of county curative-intent
counts on the county's share of residents aged 65 or over, fitted without the county itself. Ratio = observed /
expected, with an interval that allows for counties varying 4.1 times more than chance. It uses the age of
residents, not of patients, because the registry publishes neither the national share by age nor each county's
patient ages. `not_adjusted_for` lists what is missing: stage (unknown for 48% of patients), performance status,
other illness, histology, smoking, patient choice. Distance to the university hospital is **reported, not adjusted
away** (rho -0.66 with the curative share; -0.30, p 0.18, after age): distance is a candidate reason for the gap,
not a nuisance. Result: Lapland (0.75, 0.58-0.97) and North Ostrobothnia (0.80) stay below expected; most other
low counties are inside what age structure and chance allow.

### Mortality

"Deaths per 100,000 aged 65+" is gone from every output. `measured.lung_mortality_asr` and `lung_incidence_asr`
are the registry's age-standardised rates. `mortality_vs_incidence` says in one sentence whether a county's
mortality difference is already there in its incidence (Lapland: mortality 1.31 times the national rate, incidence
1.24 times: it tracks incidence).

## What a measure adds (one evaluator)

`Model.evaluate(area, measures, t)` is deterministic and is the only source of patients and deaths numbers. The
optimiser, `simulate()`, the cards and the notes all call it, so the same set of measures shows the same number
everywhere. Ranges come from five scenarios `t` in (-1, -0.5, 0, 0.5, 1) that move every effect size and conversion
assumption from its lower bound to its upper bound together; the point is the value at `t = 0` and the range is the
lowest and highest of the five, so **a point always lies inside its own range**. It is a range, not a probability
interval.

- **Treatment-access measures** (`metric: curative_share_pp`): effect in percentage points / 100 x the county's
  patients a year x applicability. Video MDT and the surgeon's second opinion count zero where the county's own
  hospital is a university hospital; travel support is scaled by road distance (0 at 50 km, full at 200 km).
  In one county the measures share a pool: half of the measured shortfall to the best quarter of counties
  (`priors.REACHABLE_SHARE_OF_SHORTFALL`), split into a surgery and a radiotherapy part. They combine as
  `pool x (1 - prod(1 - gain/pool))`, so adding a measure never lowers the total and the pool is never exceeded.
  A county at or above the best quarter gets zero.
- **Deaths avoided through access** = extra patients treated to cure x 0.15 (0.05-0.30) deaths within five years
  per patient: `kind: "assumption"`, conservative, context in `parameters.json -> curative_access`. Not a causal
  estimate.
- **Low-dose CT screening**: 1,000 (600-1,400) participants per 100,000 residents x 3.30 lung cancer deaths per
  1,000 of them a year without screening (NELSON control arm) x (1 - 0.84). The cost pays for the same
  participants: about EUR 600,000 per death avoided. `owner_level: "national"`; never in a county budget.
- **Symptom campaign**: 0.8 (0-1.6) points more stage I averaged over a year (3.1 points measured during a
  campaign, fading within months), confidence low, EUR 69,600 per 100,000 residents a year.
- **Days saved** count only for patients treated with curative intent: each 28 days sooner divides their hazard
  by 1.06 (Hanna, BMJ 2020; interval 0.93-1.19, so a lower bound can be below zero and is shown as it is).
- Overlap for pre-diagnosis and mortality measures: the k-th largest counts for 0.7^k. No plan may claim more
  than half of an area's lung deaths.

## Optimiser

`optimize(scope, budget_eur, objective=None, exclude=None)`. Objectives: `curative` (extra patients treated to
cure; county default), `gap` (the same, counted only in counties below the national share and only up to it;
national default), `deaths`. A county with no measured shortfall or no care path (Vantaa-Kerava, Åland) falls
back to `deaths` and says so in `objective_note_en`.

Greedy by objective per euro, re-evaluated after every pick; low-confidence measures rank at half value. Every
rule is listed in words in `rules_en`: the recording audit comes first where the care path carries a recording
flag; national measures are never bought from a county budget and are listed with their own numbers under
`needs_national_decision`; nothing is bought above EUR 1,000,000 per death avoided (an assumption; reason code
`poor_value`); **no budget share is reserved** for any kind of measure. Each chosen action carries what it adds to
the actions ranked before it (so actions add up to `totals`), `first_step_en/fi`, and a `kpi` with the county's
own measured baseline and a target with a year. `saturated` is true when no further measure adds anything at an
acceptable cost: county plans saturate near EUR 200,000 a year because the ceiling is the reachable shortfall, not
money. `goal3_link` sets the plan against the registry's lung deaths and the strategy's targets.

## The clock (secondary)

Five steps: patient, primary, referral, diagnosis, treatment. Step 5 is measured per collaborative area
(`level: "collaborative_area"`); Åland has no value and gets the national one marked `kind: "assumption"`, with
`measured.dx_to_treatment_days` null. Steps 1-4 per county = national figure x exp(sum of elasticity x standardised
indicator); the elasticities are priors, not fitted, and the 80% interval comes from 2,000 draws. Referral and
diagnosis are the residual of the reported 58 specialist days minus measured step 5. A measure that only flags
patients sooner (AI X-ray triage) saves nothing without added capacity, as in LungIMPACT 2026.

Consistency check, not a validation: across counties the estimated days before diagnosis correlate with the
curative share at rho -0.30 (p 0.17), with one-year survival at -0.04 and with age-standardised lung mortality at
+0.10. None is distinguishable from chance. The clock is not supported by outcomes; that is why it is secondary.

Early warning (`early_warning.json`): level plus damped trend of "% waiting over 90 days". In backtest it is not
more accurate than "no change".

## Changed from v2

Removed or renamed:
- measure `remote_mdt_travel` -> `video_mdt_stage1_3`, `surgeon_second_opinion`, `travel_accommodation_support`
- `measured.lung_deaths_per_100k_65plus` -> `measured.lung_mortality_asr` (plus `lung_incidence_asr`)
- `overview().areas[].lung_deaths_per_100k` -> `lung_mortality_asr`, `lung_incidence_asr`
- `area().indicators` no longer lists `*_deaths_per_100k_65plus_5y`
- `chosen[].deaths_avoided_per_year` was a number, is now `{median, lo, hi}`; `chosen[].deaths_avoided` removed
- `totals.budget_rule_en`, `priors.PATHWAY_MIN_BUDGET_SHARE` (the 25% rule) removed
- objective `gap` now means the measured curative-share gap, not patient-days; default objective is no longer `deaths`
- `plans.json`: `plans[scope][objective][budget]` with objective in `default`, `curative`, `deaths`, `gap`; presets 0.1-10 M EUR
- `simulate()`: `seed` is ignored (deterministic); `deaths_avoided_split` gains `from_treatment_access`; ranges are
  scenario ranges, not 80% intervals; `single_interventions` in `pathways.json` likewise
- step `kind` can be `reported` or `assumption`; Åland's `measured.dx_to_treatment_days` is null
- `deaths_per_year` comes from registry statistics 2020-2024 (was StatFin C32-C34)
- LDCT reach of 25% of deaths (`priors.REACH`) replaced by the participants model
- `not_chosen[].reason_code` adds `excluded`, `national_decision`, `no_shortfall`, `not_applicable`, `cap`, `poor_value`

New: `care_path()`, `care_paths()`, `area().care_path`, `area().mortality_vs_incidence`, `overview().headline`,
`overview().areas[].care`, `optimize(..., exclude=)`, `needs_national_decision`, `rules_en`, `saturated`,
`saturation_note_en`, `goal3_link`, `objective_note_en`, per-action `first_step_en/fi`, `kpi`, `owner_level`,
`targets_stage`, `extra_curative_patients_per_year`.

## Limits

- **Access effects are assumptions.** No trial has measured what a video MDT or a second opinion adds to a
  county's curative share. The values come from observational studies (quoted in `interventions.json`), each with
  a lower bound of zero and the null results listed.
- **The reachable half** of the shortfall is an assumption: no public table splits a county's shortfall by reason.
- **Recording.** In flagged counties part of the measured gap may be unrecorded treatment. The plan buys the
  audit first but still counts the full measured shortfall.
- **Ecological adjustment.** One covariate, 22 counties. It can remove an age-structure difference; it cannot
  show why a county differs.
- **University-served list** is our reading of the collaborative-area structure, not a published list.
- **The 0.15 conversion** is an assumption anchored on observational survival differences, which overstate what
  the marginal patient gains; hence the low value and the wide range.
- **The clock** is estimated and not supported by outcomes (above).
- **Costs** are assumptions unless the measure says otherwise, and editable.

## Use

```
cd model
nice -n 10 ../.venv/bin/python -m kello_model.precompute   # writes data/model/*.json
../.venv/bin/python -m kello_model.report                  # sanity table
../.venv/bin/python -m pytest -q tests
```

```python
from kello_model import api
api.care_path("21")                       # measured
api.optimize("21", 1_000_000)             # county default: curative
api.optimize("FI", 5_000_000)             # national default: gap
api.optimize("21", 1_000_000, "deaths", exclude=["sbrt_pathway"])
api.simulate("21", ["surgeon_second_opinion", "sbrt_pathway"])
api.overview(); api.area("21"); api.early_warning("21")
```

Files: `carepath.py` (measured care path, expected share), `measured.py` (county gaps, mortality vs incidence,
consistency check), `priors.py` (all assumptions), `inputs.py` (reads the other agents' files), `engine.py`
(clock estimate and the evaluator), `optimize.py`, `api.py`, `early_warning.py`, `precompute.py`, `report.py`,
`defaults.py` (fallbacks when an input file is missing).
