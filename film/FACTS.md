# Every number in the Kello film (v5), with its source

`scripts/make-data.py` reads these from the **live app** at render time (`$KELLO_BASE`, default http://127.0.0.1:8742)
into `src/data/film.json` and stops if a spoken number moved. The screen captures add `expect` checks: a shot fails if
the page no longer shows the text the voice-over relies on (`shots.json`). Checked 14 Nov 2026.

| Spoken / shown | Value | Source (live product) |
|---|---|---|
| "eighteen are treated to cure" · Lapland 18.5 | 131 of 710, 2019–2023 | `/api/areas/21` `care_path.stages[curative]`; Cancer Registry lung report p. 14, quote "Lapin hyvinvointialue \| 131 \| 710 \| 18.5", read by Gemini; county page dot chart |
| "In Vantaa and Kerava, thirty-six" · 35.6 · "36 of 100" tag | best county | same stage, `best` / `best_area_en`; first screen headline "In Vantaa and Kerava, 36." and dot chart "35.6 of 100, highest county" |
| Finland 27.0 | 4,009 of 14,873 | same stage, `national` |
| "thirty-one days from diagnosis to treatment, thirty-seven in Finland" · 31 / 37 | 31.2 vs 36.9 days, 2018–mid 2022 | `/api/areas/21` `stages[time_to_treatment]`, p. 28. **Oulu university hospital (OYS) collaborative area, not Lapland alone**; the registry's three medians (surgery 13.5, radiotherapy 31, drugs 42) weighted by the national treatment mix. The film says so on screen. |
| "Is the gap real? Not chance, not age, not just missing records" · "4 of 5 checks say the gap is real" | chance: less than once in 500; age: still lower after age adjustment; stage: cannot tell; records: about 8 of 12 remain; deaths: slightly more per case | `/api/areas/21` `gap_checks[]` (`short_answer_en`, `verdict`) and `gap_checks_overall_en`; county page strip "Is this gap real?" |
| "an eight-week records audit settles it" · 8 weeks, €8,000 | step zero of the plan | `gap_checks_overall_en` "(8 weeks, €8,000)"; `/api/optimize` `chosen[recording_audit].eur` = 8000 |
| "about twelve patients a year" · "12 patients a year short" | 12.1 a year (7.8–16.0) | `/api/areas/21` `care_path.missing_patients.per_year`; = 142 a year × (27.0% − 18.5%); `/api/optimize` `ui.strip.of` |
| "Now switch on Kello's plan" · 18.5 → 22.2, +3.7 of 100 | modelled | `POST /api/optimize {"scope":"21","budget_eur":1000000,"objective":"curative"}` `totals.curative_share_now_pct` / `after_pct`; dot chart "With the plan" |
| "Six actions" | 6 chosen | same call, `chosen` (records audit, SBRT pathway, travel support, prehab, surgeon second opinion, video MDT) |
| "two hundred and eleven thousand five hundred euros a year" · €211,500 | of a €1M ceiling | same call, `totals.eur`; strip "€211,500 of €1M a year" |
| "five of those twelve" · "closes 5 of them (43%)" | 5.2 of 12.1, 43% (range 0–7.7) | same call, `ui.strip` closes / of / pct, `totals.extra_curative_patients_per_year`; county page strip "Closes 5.2 of 12.1 missing patients a year (43%)"; plan title "5.2 more … for €211,500 a year" (`/api/plan/21`) |
| "thirty thousand four hundred euros a year" · SBRT | €30,400 | same call, `chosen[sbrt_pathway].eur`; card "Cost a year €30,400" |
| "First step: write the referral rule" · owner | text | `chosen[sbrt_pathway].first_step_en`, `owner_en` |
| Web check: "This morning's check and the live run agree: Oulu University Hospital already offers it. Ask them first." · BEFORE / AFTER tags | in use: partly; plan effect: flag, both runs | live run in the `card` capture (`/api/verify/stream`, Oxylabs search + page reads, Claude). The card shows the stored answer from the morning run before the click and, after it, `.vdiff`: "Stored answer, 14 Nov" vs "This run, 14 Nov … (same answer)". Quote from OYS "Keuhkosyöpäpotilaan hoitopolku". Speed-up shown on screen. |
| "Gemini read one thousand six hundred and twenty-eight values" · 1,607 re-confirmed, 21 flagged | 1,628 | `/api/reader` documents rows / verified; `data/processed/gemini_extracted.jsonl` line count; drawer "gemini-4-carbon read 1,628 values" |
| "a six-month pilot of two actions" · "from eighteen and a half to twenty and a half percent treated to cure, by 2028" · 18.5% → 20.5% | modelled; 2.84 (0–5.68) more patients a year | `/api/optimize` `pilot` (`actions` = surgeon_second_opinion + sbrt_pathway, `effect.curative_share_now_pct` / `after_pct`, `by_year`). **Not 22.2%**: 22.2% is the full six-action plan (dot chart "With the plan", +3.7 of 100). |
| "In six months: about 71 patients seen, 22 decisions not to operate reviewed" (shown) | 71.0 / 22 | `pilot.six_months.patients_seen.expected`, `no_surgery_decisions_reviewed.expected`; comparison area Vantaa and Kerava |

The captures show the app as it was when recorded (`src/data/captures/*.json` `captured_at`).
