Using the NORDCAN API (https://canapi.iarc.who.int/api/nordcan/v2/961/ — e.g. /survival/population/5/1/246_752_578_208/160/?&surv_period=5&age_surv=0&year_start=1973&year_end=2023; sex 1 male 2 female; countries 246 Finland, 752 Sweden, 578 Norway, 208 Denmark; cancers 160 lung, 130 pancreas, 110 liver), compute 5-year relative survival trends 1990–2024 for lung, pancreas and liver cancer by sex. Quantify Finland's gap to the mean of Sweden and Norway in the latest period, how the gap has changed per decade, and how many years Finland lags. Produce one clear figure per cancer and a results table, and state the limits of the data.

Context: Finland's National Cancer Strategy 2026–2035 sets the target of reaching the Sweden/Norway average for exactly these three cancers.

Requirements:
- Fetch the data live from the API in code; save the raw API responses as artifacts so the analysis can be re-run offline.
- Save the results table as CSV, one PNG figure per cancer, and the full analysis script.
- Report only numbers that come from the API responses. If an endpoint, period or parameter is unavailable, say so rather than substituting values.
