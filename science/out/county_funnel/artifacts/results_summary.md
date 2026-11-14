# Curative-intent treatment of lung cancer by wellbeing services county, Finland 2019–2023

**Data used.** I used `county_table_input.csv` only. There are 22 county rows (area_id 01–21 and 90, Helsinki). Patients (the denominator) and curative-intent counts are the registry counts as given. For every county, `lung_patients_2019_2023_n` equals `lung_cases_5y_n`, and count/patients reproduces the published share to within ±0.05 percentage points. **No counts were derived.**
- **Åland (91) is excluded.** All lung cancer fields are empty, and its count cannot be derived because both the share and the case count are missing.
- **Centre line.** The centre line is the national row: 4,009 / 14,873 = **26.95 %**.
- **National row versus county sum.** The 22 counties add up to 14,774 patients and 3,992 curative-intent treatments, which is 99 patients and 17 treatments fewer than the national row. The input does not say where the remainder belongs (possibly Åland or patients with unknown residence).

## Is the variation larger than chance?
Yes, by a wide margin.
- **Heterogeneity test.** Against the national share, χ² = 187.7 on 21 df, p ≈ 1e-28.
- **Overdispersion.** The Spiegelhalter multiplicative overdispersion factor (z-scores winsorised at 10 %) is φ = 6.64 (p ≈ 3e-20). The county-level variance is therefore about 6.6 times what binomial sampling predicts.
- **Random-effects view.** In an additive random-effects model, the between-county SD is τ = 4.9 percentage points and I² = 0.89.
- **Interpretation.** Most of the spread is systematic. It may reflect real practice differences, case mix or recording.

## Outliers (exact binomial limits around 26.95 %)
| County | Patients | Curative-intent | Share % | Exact binomial p | Binomial limits | Overdispersion-adjusted (φ) | Patients/yr below national share |
|---|---|---|---|---|---|---|---|
| Lapland | 710 | 131 | 18.5 | 1.4e-07 | below 99.8 % | **below 95 %** | 12.1 |
| South Karelia | 355 | 67 | 18.9 | 0.0005 | below 99.8 % | within | 5.7 |
| Kymenlaakso | 591 | 114 | 19.3 | 1.6e-05 | below 99.8 % | within | 9.1 |
| Kainuu | 226 | 47 | 20.8 | 0.036 | below 95 % | within | 2.8 |
| North Karelia | 510 | 109 | 21.4 | 0.0044 | below 95 % | within | 5.7 |
| North Ostrobothnia | 1050 | 248 | 23.6 | 0.015 | below 95 % | within | 7.0 |
| Southwest Finland | 1437 | 349 | 24.3 | 0.022 | below 95 % | within | 7.7 |
| West Uusimaa | 1058 | 337 | 31.9 | 0.00041 | above 99.8 % | within | (10.4 above) |
| Pirkanmaa | 1253 | 400 | 31.9 | 0.0001 | above 99.8 % | within | (12.5 above) |
| Central Uusimaa | 481 | 162 | 33.7 | 0.0012 | above 99.8 % | within | (6.5 above) |
| Helsinki | 1486 | 491 | 33.0 | 2.2e-07 | above 99.8 % | **above 95 %** | (18.1 above) |
| Vantaa and Kerava | 595 | 212 | 35.6 | 3.6e-06 | above 99.8 % | within | (10.3 above) |

The gap in patients per year is (26.95 % × patients − observed) / 5 years. For example, Lapland treated about 12 fewer patients a year with curative intent than the national share would imply.

**Reading.** Under pure binomial limits, 12 of 22 counties are outliers: 7 below and 5 above. Once the excess variation is allowed for, the picture is much simpler.
- **Multiplicative adjustment.** Only **Lapland (low)** and **Helsinki (high)** fall outside the 95 % overdispersion-adjusted limits, and both lie only just outside them (z = −1.98 and 2.05). No county falls outside 99.8 %.
- **Additive random-effects adjustment.** No county falls outside 95 %.
- **Overall pattern.** The counties form a gradient rather than a few isolated outliers. The Uusimaa/Helsinki area and Pirkanmaa are high, and the eastern and northern counties are low. With 22 tests at 95 %, about one false flag is expected by chance.

## Exploratory ecological rank correlations (n = 22 counties)
| County characteristic | Spearman ρ | 95 % CI (Fisher, Bonett–Wright SE) | 95 % CI (bootstrap, 5,000) |
|---|---|---|---|
| Population aged 65+ (%) | −0.77 | −0.91 to −0.47 | −0.91 to −0.50 |
| Distance to university hospital (km) | −0.67 | −0.86 to −0.30 | −0.91 to −0.27 |
| Lung cancer incidence /100k | −0.62 | −0.84 to −0.24 | −0.87 to −0.23 |
| Education level index | 0.49 | 0.06 to 0.77 | 0.10 to 0.75 |
| Daily smokers (%) | −0.30 | −0.65 to 0.15 | −0.72 to 0.18 |

These are **ecological associations between 22 areas, not causes.** The characteristics are strongly correlated with each other: older, less educated and more remote counties are largely the same counties. The correlations cannot be separated with 22 data points, and a county-level link need not hold for individual patients. An older population would plausibly mean more frail patients and more advanced disease, so the patient-level case mix (age, stage, performance status) would have to be adjusted before attributing any gap to the quality of care. No adjustment for multiple testing was made.

## Limits
- **Stage recording.** The registry itself says stage is recorded for only about half of patients, and recording practice differs by county. The share is therefore not adjusted for stage, the main determinant of curative eligibility, and part of the between-county difference may come from recording rather than treatment. The no-treatment-record share also varies widely (16 %–43 %): Southwest Finland and South Karelia are above 40 %. Missing treatment records would lower the measured curative share.
- **Treatment definition.** "Curative intent" is as defined in the registry report, and the input says nothing about how consistently it is coded.
- **Pooled period.** All five years (2019–2023) are pooled. The input gives no annual data, so trends and COVID-period effects cannot be examined.
- **Missing data.** Åland is missing, and the national row is not exactly the sum of the counties (see above).
- **Area type.** Helsinki is a city, not a county, but is treated as one area as in the source.
