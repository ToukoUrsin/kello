Below is a table of public aggregate data on lung cancer in Finland's 23 wellbeing services counties (last row is the whole country). Sources: Finnish Cancer Registry lung cancer quality report 2019–2023 (patients, curative-intent treatment counts and shares, no-treatment-record share), Statistics Finland and THL Sotkanet (the context columns, latest year). `lung_patients_2019_2023_n` and `curative_intent_n` were read from the registry report; `lung_cases_5y_n` is the registry case count from a second source. Empty cells are missing — do not fill them.

```csv
area_id,county,collaborative_area,lung_patients_2019_2023_n,curative_intent_n,lung_curative_intent_pct,lung_no_treatment_record_pct,lung_cases_5y_n,lung_incidence_per_100k,pop_65plus_pct,daily_smokers_pct,education_level_index,low_income_rate_pct,km_to_university_hospital
01,East Uusimaa,HUS,272.0,77.0,28.3,31.6,272,55.2,24.2,10.7,388.6,9.8,63.7
02,Central Uusimaa,HUS,481.0,162.0,33.7,26.4,481,47.7,21.1,9.3,393.0,9.2,49.6
03,West Uusimaa,HUS,1058.0,337.0,31.9,28.5,1058,44.0,18.8,8.0,460.7,11.2,33.8
04,Vantaa and Kerava,HUS,595.0,212.0,35.6,28.9,595,42.9,16.7,12.5,368.8,13.8,20.6
05,Southwest Finland,TYKS,1437.0,349.0,24.3,43.1,1437,59.4,24.4,10.2,396.9,14.7,27.8
06,Satakunta,TYKS,682.0,167.0,24.5,29.8,682,63.7,29.2,12.5,351.8,14.6,115.4
07,Kanta-Häme,TAYS,546.0,128.0,23.4,32.1,546,64.2,28,10.2,367.8,13.2,84.3
08,Pirkanmaa,TAYS,1253.0,400.0,31.9,17.9,1253,47.4,22.6,7.4,421.9,14.6,33.3
09,Päijät-Häme,HUS,659.0,195.0,29.6,17.8,659,64.2,29,9.9,358.6,16.1,132.7
10,Kymenlaakso,HUS,591.0,114.0,19.3,16.4,591,73.3,31.1,12.0,351.3,15.5,166.1
11,South Karelia,HUS,355.0,67.0,18.9,42.8,355,56.2,29.9,10.1,366.0,17.6,256.8
12,South Savo,KYS,448.0,105.0,23.4,23.2,448,68.0,34.6,7.2,351.2,16.0,163.0
13,North Savo,KYS,641.0,157.0,24.5,19.3,641,51.6,27.8,9.0,383.5,15.4,46.8
14,North Karelia,KYS,510.0,109.0,21.4,22.2,510,62.5,29.8,10.0,371.0,19.0,165.8
15,Central Finland,KYS,637.0,173.0,27.2,24.5,637,46.7,25.4,7.6,398.5,17.3,145.9
16,South Ostrobothnia,TAYS,540.0,165.0,30.6,25.7,540,56.3,27.7,7.6,355.4,13.7,194.7
17,Ostrobothnia,TYKS,449.0,125.0,27.8,22.9,449,50.9,23.7,7.7,388.4,13.1,258.4
18,Central Ostrobothnia,OYS,148.0,33.0,22.3,25.0,148,43.6,25.3,8.7,362.3,12.2,212.1
19,North Ostrobothnia,OYS,1050.0,248.0,23.6,25.0,1050,50.6,21.9,9.5,407.6,14.8,73.0
20,Kainuu,OYS,226.0,47.0,20.8,28.3,226,63.5,31.8,8.9,353.7,15.4,182.9
21,Lapland,OYS,710.0,131.0,18.5,33.8,710,80.5,28.1,11.4,372.0,13.6,250.4
90,Helsinki,HUS,1486.0,491.0,33.0,29.1,1486,44.9,17.7,6.8,486.5,14.1,8.8
91,Åland,ALAND,,,,,,,24.8,6.8,365.1,9.2,170.9
FI,Finland,,14873.0,4009.0,27.0,27.5,14873,53.5,23.8,9.1,403.2,14.2,86.8
```

Save this table as `county_table_input.csv` first, and work only from it.

Question: are the differences between counties in the share of lung cancer patients who receive curative-intent treatment larger than chance alone would produce, and which counties are genuine outliers?

Do this:
1. Build a county table: patients (denominator), patients with curative-intent treatment, share. State exactly which rows you used; if counts are missing for a county, derive them from the share and the case count and say so.
2. Funnel plot: share against number of patients, with the national share as the centre line and 95% and 99.8% binomial control limits. Label counties outside the 95% limits. Test for overdispersion and, if present, also show overdispersion-adjusted limits.
3. Report which counties fall outside the limits (above and below), with their shares, counts and exact binomial p-values, and how many patients a year separate each low outlier from the national share.
4. Exploratory only: rank correlations of the county share with share of population aged 65+, daily smoking, education, distance to a university hospital and lung cancer incidence. Say clearly that with 22 or 23 counties these are ecological associations, not causes, and report confidence intervals.
5. State the limits: the registry itself says stage is recorded for about half of patients and recording practice differs by county, so part of the difference may be recording.

Outputs: the county table as CSV, the funnel plot as PNG (clear enough for a slide: readable labels, Finnish county names in English), a short results summary in Markdown, and the full analysis script. Use only numbers from the files; if something is missing, say so instead of substituting a value.
