# Curative-intent treatment of lung cancer across Finland's wellbeing services counties, 2019–2023

**Question.** Are between-county differences in the share of lung cancer patients receiving
curative-intent treatment larger than chance alone would produce, and which counties are genuine outliers?

**Answer.** Yes, decisively. The 22 counties with reported counts scatter about the national share
far beyond binomial sampling error (Q = 187.7 on 21 df, *p* ≈ 10^-28;
dispersion factor φ = 8.5, winsorised φ = 6.6). Shares run from
18.5 % to 35.6 % — a 17.2
percentage-point spread, against a national 27.0 %. Against plain binomial limits
12 of 22 counties are outside the 95 % limits
(8 outside 99.8 %); after inflating the limits by the
observed overdispersion, 1 county (Helsinki) remains outside.

![Funnel plot]({{artifact:91f56a8b-8394-4d32-9078-13a98aee567d}})

## 1. Rows used

| | |
|---|---|
| Counties analysed | **22** — every row with both counts (`area_id` 01–21 and 90) |
| Excluded | **Åland** (`area_id` 91): patients, curative-intent count, share and case count are all empty; nothing can be derived, so it enters no plot, test or correlation |
| Finland row (`area_id` FI) | used **only** as the centre line: 4,009/14,873 = 26.95 % |
| Denominator | `lung_patients_2019_2023_n` (registry report) |
| Numerator | `curative_intent_n` (registry report) |

**No count was derived from share × case count.** The second source's `lung_cases_5y_n` is identical to
`lung_patients_2019_2023_n` for all 22 counties, and the recomputed share `curative_intent_n / patients`
reproduces the reported `lung_curative_intent_pct` to within 0.05 pp everywhere, so the counts were used as given.

**One discrepancy to note:** the 22 counties sum to 14,774 patients and 3,992 curative-intent
treatments, whereas the Finland row gives 14,873 and 4,009 — 99 patients and
17 treatments are in the national total but in no county row (Åland is the only county
without counts, and the registry total may also carry records of unknown area). Using the 22-county
sum as the centre line instead (27.02 %) leaves the set of counties outside the 95 % limits unchanged.

## 2. Is the variation larger than chance?

| Statistic | Value |
|---|---|
| Counties | 22 |
| Pearson Q = Σ z² (test of homogeneity) | **187.7** on 21 df, *p* ≈ 10^-28 |
| Dispersion factor φ = Q/K | **8.53** (1.0 = pure binomial) |
| Winsorised φ (Spiegelhalter, 10 % each tail) | **6.64** — used to inflate the limits |
| Between-county SD on the share scale (DerSimonian–Laird τ) | **4.9 pp** |

φ ≈ 9 means the observed between-county variance is about 9× what independent binomial
sampling at a common 27.0 % would give. The differences are real; the only question is what produces them.

## 3. Counties outside the limits

Shares are exact (Clopper–Pearson) CIs; *p* is a two-sided exact binomial test of the county count
against the national 26.95 %; *q* is the Benjamini–Hochberg value across all 22 counties.

### Above the limits — more curative-intent treatment than the national share

| County | Patients | Curative-intent | Share (95 % CI) | Exact binomial *p* | BH *q* | vs binomial limits | vs adjusted limits |
|---|---:|---:|---:|---:|---:|---|---|
| Vantaa and Kerava | 595 | 212 | 35.6 % (31.8–39.6) | 3.6e-06 | 2.6e-05 | outside 99.8% | within 95% |
| Central Uusimaa | 481 | 162 | 33.7 % (29.5–38.1) | 0.0012 | 0.0033 | outside 99.8% | within 95% |
| Helsinki | 1,486 | 491 | 33.0 % (30.7–35.5) | 2.2e-07 | 2.4e-06 | outside 99.8% | outside 95% |
| Pirkanmaa | 1,253 | 400 | 31.9 % (29.3–34.6) | 1.0e-04 | 4.4e-04 | outside 99.8% | within 95% |
| West Uusimaa | 1,058 | 337 | 31.9 % (29.1–34.8) | 4.1e-04 | 0.0015 | outside 99.8% | within 95% |

### Below the limits — less curative-intent treatment than the national share

| County | Patients | Curative-intent | Share (95 % CI) | Exact binomial *p* | BH *q* | vs binomial limits | vs adjusted limits | Shortfall vs national, patients/year |
|---|---:|---:|---:|---:|---:|---|---|---:|
| Lapland | 710 | 131 | 18.5 % (15.7–21.5) | 1.4e-07 | 2.4e-06 | outside 99.8% | within 95% | 12.1 |
| South Karelia | 355 | 67 | 18.9 % (14.9–23.3) | 5.0e-04 | 0.0016 | outside 99.8% | within 95% | 5.7 |
| Kymenlaakso | 591 | 114 | 19.3 % (16.2–22.7) | 1.6e-05 | 8.6e-05 | outside 99.8% | within 95% | 9.1 |
| Kainuu | 226 | 47 | 20.8 % (15.7–26.7) | 0.0359 | 0.0659 | outside 95% | within 95% | 2.8 |
| North Karelia | 510 | 109 | 21.4 % (17.9–25.2) | 0.0044 | 0.0107 | outside 95% | within 95% | 5.7 |
| North Ostrobothnia | 1,050 | 248 | 23.6 % (21.1–26.3) | 0.0149 | 0.0327 | outside 95% | within 95% | 7.0 |
| Southwest Finland | 1,437 | 349 | 24.3 % (22.1–26.6) | 0.0221 | 0.0442 | outside 95% | within 95% | 7.7 |

The last column is the arithmetic gap: (national share × county patients − observed treatments) ÷ 5 years.
Summed over the 7 low counties, **50 patients a year**
would have had a curative-intent treatment record had those counties treated at the national share.

**Overdispersion-adjusted reading.** With limits widened by √φ = 2.58, only **Helsinki**
(33.0 %,
n = 1,486) lies outside. This is not a retraction of the
finding — the adjusted limits *absorb* the between-county differences into the null, so they answer a
different question: "is this county unusual **given** that counties differ this much?" The 12
counties outside the binomial limits are the ones that differ from the national average; Helsinki is the
one that is extreme even on the scale of the counties' own spread. Note that Vantaa and Kerava has the
highest share (35.6 %) but falls inside the adjusted limits because its denominator is
smaller than Helsinki's.

## 4. Rank correlations with county context (exploratory)

| Context variable | Spearman ρ | 95 % CI | *p* |
|---|---:|---:|---:|
| Population aged 65+ (%) | -0.77 | -0.91 to -0.47 | 2.6e-05 |
| Distance to university hospital (km) | -0.66 | -0.86 to -0.30 | 7.4e-04 |
| Lung cancer incidence per 100 000 | -0.62 | -0.84 to -0.24 | 0.0019 |
| Daily smokers (%) | -0.30 | -0.65 to +0.15 | 0.1723 |
| Education level index | +0.49 | +0.06 to +0.77 | 0.0198 |

Spearman ρ with Bonett–Wright 95 % CIs, n = 22 counties (Åland has context data but no share, so it is
excluded here too). **These are ecological associations between county aggregates, not causes.** With
22 units the CIs are wide, the five variables are strongly intercorrelated with each other (older,
more peripheral counties are also the lower-education, higher-incidence ones), and nothing here identifies
an effect on an individual patient's chance of curative-intent treatment — the ecological fallacy applies
in full. No multiplicity adjustment is applied to these five tests; treat them as description, not inference.

The pattern that does emerge is a single gradient rather than five findings: counties with a younger
population, shorter distance to a university hospital and higher education index have higher
curative-intent shares, and counties with high lung cancer incidence have lower shares. The five
university-hospital host counties and their neighbours (Helsinki, Vantaa and Kerava, Central and West
Uusimaa, Pirkanmaa) are the high group; Lapland, Kymenlaakso, South Karelia, Kainuu and North Karelia
the low group. Daily smoking is the one variable whose CI comfortably spans zero.

## 5. Limits of what these numbers can show

1. **Recording, not only treatment.** The registry's own quality report states that stage is recorded
   for roughly half of lung cancer patients and that recording practice differs between counties. The
   curative-intent share is conditioned on what reaches the registry, so an unknown part of the spread
   is documentation rather than care delivered.
2. **The no-treatment-record column points the same way.** `lung_no_treatment_record_pct` ranges from
   16.4 % (Kymenlaakso) to 43.1 %
   (Southwest Finland) across counties — a 26.7
   pp spread in how often *any* treatment is recorded. A county can appear to have a low curative-intent
   share because treatment was given elsewhere or not captured. Southwest Finland and South Karelia, two
   low-share counties, have the two highest no-record shares (43.1 % and 42.8 %).
3. **No case-mix adjustment.** Stage, performance status, histology, age and comorbidity are the
   determinants of whether curative intent is even possible, and none is in this table. The funnel
   compares crude shares; a county with more advanced-stage or frailer patients should have a lower
   share for clinical reasons. Indirect standardisation was not possible with the data supplied.
4. **Referral across county borders.** Curative treatment is concentrated in university hospitals.
   Where a patient is treated and which county is credited need not coincide, which can move counts
   between neighbouring counties.
5. **Five pooled years.** 2019–2023 spans the COVID-19 period; the table gives no year breakdown, so
   no trend or disruption can be separated.
6. **Multiplicity.** With 22 simultaneous comparisons, BH-adjusted *q* values are reported alongside
   the raw exact *p* values; the 99.8 % limits serve the same purpose graphically.
7. **Åland** contributes nothing to this analysis — it has no reported counts, and that absence is
   reported rather than filled.

## Files

- [county_table_analysis.csv]({{artifact:d06b6d31-e9b6-471a-bb7b-c7e5f7ee1e84}}) — per-county counts, shares, exact CIs, z, exact and BH *p*, limit band, per-year gap, context columns
- [funnel_curative_intent.png]({{artifact:91f56a8b-8394-4d32-9078-13a98aee567d}}) — funnel plot
- [rank_correlations.csv]({{artifact:23082ee9-847d-4cf3-a63d-9df1aed9261a}}) — Spearman ρ, CIs, *p*
- [lung_curative_funnel.py]({{artifact:7b3ca43a-382c-4ee0-9fcc-e5edad410376}}) — full analysis script
- [county_table_input.csv]({{artifact:2034e53c-a3b0-4a7f-87ae-0c251a1eed16}}) — the input table as supplied
