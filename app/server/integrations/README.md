# integrations

Two sponsor integrations of Kello. Everything in `examples/` is a real run from 13-14.11.2026.

| | What it does | Runs on |
|---|---|---|
| Live web check | For one measure in one county: is it already running there, and does evidence support the effect we assume? The answer changes the plan. | Oxylabs Web API + Claude (`claude-opus-5-5`); Gemini (`gemini-4-hydrogen`) when Claude is not reachable |
| County scout | "What is this county doing about lung cancer care right now?" Up to 6 dated findings with quotes. | same |
| Read a report | A PDF, web page, web app or chart image into cited numbers. | Gemini (`gemini-4-hydrogen`) |

## Oxylabs: endpoints used and why

- **`POST /v1/search`** (`{query, max_results, location}`): every search of a run, live, never cached.
  County sites, council decisions and hospital pages change weekly and are in Finnish; `location: "FI"`
  gives the results a person in Finland would get. 1-3 s per search.
- **`POST /v1/scrape`** (`{url, output:["html"], run_js?, location?}`): every page and PDF a run reads.
  We ask for raw HTML and pick the main content ourselves (`pagetext.py`), because the pages that
  matter are hospital sites with accordions, wide tables and cookie walls. Plain fetch first (2-6 s);
  a JavaScript render (11-18 s) only when the plain page comes back as navigation only; a Nordic exit
  as last try. PDFs come through the same endpoint and are parsed with PyMuPDF. A page is not cut at a
  fixed length: it is split into passages and the ones that share words with the question are kept
  ("7 of 31 passages kept" in the trace). The links of the page that match the question are handed to
  the model too, so it can go from a hub page ("Syöpätaudit") to the page it needs ("Keuhkosyöpäpotilaan
  hoitopolku"). Read pages are cached 24 h (`from_cache: true`).
- Not through Oxylabs: nothing, with one stated exception. Journal records (pubmed, PMC, europepmc.org,
  doi.org) are read from the Europe PMC REST API through `/v1/scrape`, because Oxylabs refuses
  pubmed/PMC URLs and publisher sites stall the scraper. If that scrape stalls for 9 s we ask Europe
  PMC directly; the trace then says "Europe PMC API, direct".

Every result lists the endpoints it used (`endpoints_used`: calls, failures, JavaScript renders, cache hits,
and why) and what it searched (`searched_en`), and every trace step names its endpoint and URL.

## The check: one specific question, an answer that changes the plan

The question has two halves (`verify.py`):

- **B. In use here.** "Is <measure> already running in <county>, or in the university hospital area that
  treats its patients?" -> `yes` | `partly` | `planned` | `no_evidence`.
- **A. Effect.** "Does recent evidence support the size of effect we assume?" -> `supports` | `weaker` |
  `contradicts` | `not_found`. For a measure with no direct effect (the records audit) it asks instead
  whether a source documents the problem it fixes.

The loop (`agent.py`), at most 3 search rounds and about 75 s (scout: 90 s):

1. Round 1 is written by code, not by the model: four Finnish searches at once. One for the university
   hospital's lung cancer pathway page ("OYS keuhkosyöpäpotilaan hoitopolku"), three with the words a
   local page uses for the measure ("potilashotelli", "täsmäsädehoito", "moniammatillinen kokous") and the
   county's or hospital's own name. This is what made treatment-access measures answerable.
2. The model (three tools: `search`, `read`, `finish`) reads three to five results in parallel, together
   with the evidence page we already hold for the effect.
3. It names what is still unanswered and searches again for exactly that. A draft answer with an open half
   is sent back for one more round while time remains.
4. `finish` gives the two answers, an advice for the plan line and quotes.

Rules applied in code, not left to the model:

- a quote that is not literally in the text of a page read in this run is dropped;
- an "in use" quote must come from a page that names the county or its university hospital area; a
  national page can support `partly` or `planned`, never `yes`;
- without such a quote the answer is "no public sign of it", never "not in use", and the result says
  what was searched and where;
- `partly` with the advice "keep the line as it is" is lowered to `no_evidence`: ordinary care is not a
  piece of the measure.

What the answer does to the plan (`plan_effect`, with `plan_effect_reason_en` in one sentence):

| in use here | plan_effect | What the page does |
|---|---|---|
| `yes` | `exclude` | the measure moves to "Already in place", its euros are freed and the plan is made again without it |
| `partly`, `planned` (or evidence contradicts the effect) | `flag` | the line stays, with what to ask whom or which piece to pay for ("Ask OYS first whether ...") |
| `no_evidence` | `keep` | the line stays; the result says what was searched |

`verdict_en` says the same in plain words (what is supported and what is not; never the bare word "mixed").

Which model answered is in `model`, `models` and on every model step of the trace. Order (`llm.py`): Claude
through the Anthropic API when reachable; otherwise Gemini with function calling, same prompts,
same tools, same quote check. If Claude fails in the middle of a run, the steps so far are handed to
Gemini and the trace step says so (`handover`). `KELLO_BRAIN=gemini` forces Gemini.

The button does not end in an error. The last good result per (measure, county) is kept in
`cache/verify/`. When Oxylabs or both models fail, or the run passes its hard limit (120 s), that result
is returned with `from_cache: true`, its own `checked_at` and `live_error`. `prerun.py` fills the store
ahead of time: every measure the optimiser funds at 1 M EUR in each of the 23 counties, and the scout for
each county, two runs at a time, skipping what is stored and younger than 24 h.

## HTTP endpoints (`api.py`, plus two handlers in `main.py`)

| Endpoint | Returns |
|---|---|
| `POST /api/verify {intervention_id, area_id?}` | the check result (blocks 25-75 s) |
| `GET /api/verify/stream?intervention_id=&area_id=` | SSE: `step` events, then `done` (the result) |
| `GET /api/verify/latest?area_id=` | `{area_id, checks:[result, ...]}`, the stored latest check per measure |
| `POST /api/scout {area_id}` | the scout result (blocks 50-90 s) |
| `GET /api/scout/stream?area_id=` | SSE, same events |
| `GET /api/scout/latest?area_id=` | stored result, or `{area_id, findings: null, checked_at: null}` |
| `GET /api/integrations/status` | `{search, claude, gemini, model, stored_checks, stored_scouts}` |
| `POST /api/read-report/start {url, hint?, refresh?}` | `{job_id, status, result?}`; poll `GET /api/read-report/job/{id}` |
| `POST /api/read-report {url}` | the read result (blocks) |
| `POST /api/read-report/keep {url, row_index}` | `{added, already, row, count}`; appends to `data/processed/reader_added.jsonl` |
| `GET /api/read-report/kept[?url=]` | `{count, rows}` |
| `GET /api/read-report/charts` | `{count, rows, accuracy}`: numbers read off a figure, with the error check |

Check result: `{schema, question, intervention_id, intervention_name_en, area_id, area_name_en,
in_use_here (yes|partly|planned|no_evidence), in_use_scope (county|collaborative_area|national|none), in_use_label_en,
in_use_quote, in_use_source:{url,title,published,fetched_at}|null, in_use_summary_en, missing_en,
effect_check (supports|weaker|contradicts|not_found), effect_label_en, effect_summary_en, supported_en, not_supported_en,
advice (take_out|narrow|check_first|keep), plan_effect (exclude|flag|keep), plan_effect_reason_en, verdict_en,
summary_en, unanswered_en, searched_en, queries, endpoints_used:[{endpoint,api,calls,failed,why_en,js_render?,from_cache?}],
sources:[{url,title,quote,about (in_use|effect|context),published,fetched_at,from_cache}], trace:[step], rounds, searches,
pages_read:[{url,title,chars,kind,from_cache,fetched_at,published,js_render}], quotes_dropped, stopped, model, models,
budget_s, seconds, zero_effect, from_cache, checked_at, live_error?, live_tried_at?, error?}`. `verdict`
(supported|mixed|contradicted|not_found) is kept for older callers. `error` appears only when the live run failed
and nothing is stored; the HTTP status is 200 and `verdict_en` says the measure is unchecked.

Trace step (also the SSE `step` payload, sent once with `status:"running"` and once with `"done"`):
`{step, round, tool ("claude"|"gemini"|"oxylabs /v1/search"|"oxylabs /v1/scrape"), endpoint ("POST /v1/search"|
"POST /v1/scrape"|"model"), input, url, why?, status, t_s, result_en, ms, model?, handover?, results?[{url,title}],
title?, chars?, published?, js_render?, from_cache?, kind?, error?, timeout?}`.

Scout result: `{area_id, area_name_en, area_name_fi, question, findings:[{date, what_en, what_fi, quote, url, title,
relates_to (a measure id, a care-path stage id, or null), scope, fetched_at, from_cache}],
findings_dropped:{quote_not_on_page, not_about_this_county}, summary_en, not_found_en, searched_en, queries,
endpoints_used, trace, rounds, searches, pages_read, stopped, model, models, seconds, from_cache, checked_at,
live_error?, error?}`. A date whose year is not printed on the page is set to null.

Read result: `{document:{title,publisher,url,pages,kind}, extracted:[{indicator_guess,label,label_en,area,area_id,
value,unit,period,page,quote,read_from (text|table|chart),confidence,verified,check,value_kind (measured|target)}],
model, notes_en, read_at, cached, seconds}`. `notes_en` is always there, also with 0 values. Every URL read is
stored in `app/server/cache/report_<key>.json`; a read with 0 values is served from there for one hour only.

Stores: `cache/verify/<measure>__<area>.json`, `cache/scout/<area>.json` (within 24 h a run with fewer findings
does not replace one with more), `cache/pages/` (24 h page cache, not shipped to the hosted copy).

## Measured (final code, 14.11.2026; `examples/verify_*.json`, `examples/scout_*.json`)

The funded measures of four counties at 1 M EUR a year, curative objective (Claude, `claude-opus-5-5`):

| Measure | County | In use here | Effect | Plan | Rounds | Seconds | Quote the answer rests on |
|---|---|---|---|---|---|---|---|
| sbrt_pathway | Lapland (21) | partly | weaker | flag | 1 | 20.4 | "Paikallisessa tai paikallisesti edenneessä taudissa, jos leikkaushoito ei ole mahdollista, voidaan antaa täsmäsädehoitoa tai yhtä aikaa ..." (oys.fi) |
| surgeon_second_opinion | Lapland (21) | partly | weaker | flag | 1 | 24.9 | "Vastaa keuhkosyövän moniammatillisista kokouksista" (oys.fi) |
| travel_accommodation_support | Lapland (21) | partly | weaker | flag | 1 | 21.8 | "Jos tulet pitkän matkan takaa eikä vointisi ole sellainen, että sinun tarvitsisi jäädä sairaalan vuodeosastolle, sinä ja läheisesi voitte ..." (oys.fi) |
| video_mdt_stage1_3 | Lapland (21) | partly | weaker | flag | 1 | 19.2 | "Vastaa keuhkosyövän moniammatillisista kokouksista" (oys.fi) |
| prehab_fitness_assessment | Lapland (21) | no_evidence | weaker | keep | 3 | 54.9 | none (7 searches, 5 pages read) |
| recording_audit | Lapland (21) | no_evidence | supports | keep | 3 | 39.6 | none (6 searches, 2 pages read) |
| surgeon_second_opinion | Satakunta (06) | partly | weaker | flag | 1 | 20.8 | "Tyksissä kokoontuu viikoittain moniammatillinen työryhmä, joka tarvittaessa käsittelee tutkimustulokset ja suunnittelee hoitolinjauksesi. ..." (tyks.fi) |
| video_mdt_stage1_3 | Satakunta (06) | partly | weaker | flag | 1 | 20.5 | "Satasairaalan lääkärit osallistuvat kokouksiin etäyhteydellä. Kaikkia syöpätapauksia ei ole tarpeellista käsitellä kokouksessa, vaan ..." (tyks.fi) |
| sbrt_pathway | Satakunta (06) | no_evidence | weaker | keep | 3 | 62.5 | none (6 searches, 4 pages read) |
| sbrt_pathway | Kymenlaakso (10) | partly | weaker | flag | 1 | 18.2 | "Jos leikkaus ole mahdollinen, hoitomuoto voi olla korkea-annoksinen niin sanottu täsmäsädehoito osassa tapauksia." (hus.fi) |
| travel_accommodation_support | Kymenlaakso (10) | partly | weaker | flag | 2 | 30.7 | "Hotellivarauksen on tehnyt sinua hoitava yksikkö." (assets.eu.ctfassets.net) |
| video_mdt_stage1_3 | Kymenlaakso (10) | partly | weaker | flag | 2 | 31.9 | "Hoitosuositukset tehdään Kymenlaakson hyvinvointialueen moniammatillisessa keuhkokokouksessa." (kymenhva.fi) |
| prehab_fitness_assessment | Kymenlaakso (10) | no_evidence | weaker | keep | 3 | 41.4 | none (6 searches, 3 pages read) |
| surgeon_second_opinion | Kymenlaakso (10) | no_evidence | weaker | keep | 3 | 48.8 | none (6 searches, 6 pages read) |
| sbrt_pathway | Southwest Finland (05) | partly | weaker | flag | 1 | 20.5 | "Keuhkosyövässä vartalon stereotaktista sädehoitoa voidaan käyttää ensilinjan hoitona leikkauksen asemasta, kertoo osastonylilääkäri Heidi ..." (varha.fi) |
| prehab_fitness_assessment | Southwest Finland (05) | no_evidence | weaker | keep | 3 | 49.8 | none (6 searches, 4 pages read) |
| recording_audit | Southwest Finland (05) | no_evidence | weaker | keep | 3 | 49.1 | none (6 searches, 5 pages read) |

All stored checks (103: every measure funded at 1 M EUR in the 23 counties, plus the other measures of the demo
counties): 2 `yes`, 38 `partly`, 3 `planned`, 60 `no_evidence`. Median 44 s, slowest 73 s;
31 answered in one round, 54 used all three. Quotes dropped by the verbatim check: 0.
Scout: 23 counties stored, 128 findings, median 49 s.

Two checks ended in `yes` (`plan_effect: "exclude"`):

- `gp_direct_ct` in Satakunta (06), 1 round, 21 s. Satakunnan Kansa, 11.11.2026: "Keskeinen uudistus on se, että
  keuhkosyöpää epäiltäessä potilas voidaan lähettää keuhkojen tietokonetomografiaan eli TT-kuvaukseen suoraan
  perusterveydenhuollosta." and "Vuonna 2022 pilottina alkanut toimintamalli vakiintui käyttöön vuonna 2024."
  (`examples/verify_gp_direct_ct_06_satakunta.json`). The optimiser does not fund this measure in Satakunta at
  any budget, so nothing moves in that plan; the same article makes `cpp_pathway` and `same_day_cxr_ct` there
  `partly` ("narrow this line to ..."), and those two are funded when the objective is deaths avoided.
- `surgeon_second_opinion` in Southwest Finland (05), 1 round, 25 s. Weaker: the quote is from Tyks's page on
  cancer team meetings in general (14 cancers, mostly weekly, with the surgeon), not from a lung cancer page.
  The optimiser does not fund this measure there either, for the same reason: the surgeons are in Turku.

No measure funded at 1 M EUR for the curative objective is a `yes` anywhere: no page read says that one of them
already runs in full, and the check is not allowed to guess.

With Gemini as the model (the hosted copy; `examples/verify_gemini_*.json`): the same loop takes 45-90 s, because each
Gemini turn is slower. `examples/verify_handover_*.json` is a run where Claude failed at the first turn and Gemini took
over ("Claude did not answer (HTTP 401); Gemini took over" on the trace step).

Known limits: two runs of the same question can pick different pages, so wording varies and a borderline answer can
move between `partly` and `no_evidence`; a site that does not answer in 20 s is skipped and named in the trace;
`no_evidence` means nothing public was found in about a minute, not that the county does nothing; hospital pages
rarely carry a date, so `published` is often empty and `fetched_at` is the date to cite.

## Gemini reader

Model: `gemini-4-hydrogen`, chosen from the models the key lists (`client.models.list()`): the Gemini 4 models
read the test chart equally well (mean error 0.06-0.09 points), hydrogen is the fastest of them (13 s against
22-25 s) and the only one with 65k output tokens, which a 60-page report needs. `gemini-3.8-flash` was 10 times
less exact on the chart (mean 1.0, worst 4.4 points). `GEMINI_READER_MODEL` overrides.

How a read works: PDFs go in as PDFs; web pages are rendered in Chrome (Playwright under Xvfb) into screenshots
plus page text, the text of embedded frames and the data behind Plotly charts. Pass 1 returns every value with
page and verbatim quote. Pass 2 shows Gemini only the cited page and asks for the number again: a different
number is dropped unless the page text prints ours (`check: "text_match"`).

Two failures fixed on 13.11.2026:

- `https://cancerregistry.fi/statistics/cancer-statistics/` returned 0 values. The numbers are in a cross-origin
  frame (the registry's R Shiny app) that starts loading about 10 s after the page is idle and opens on "all
  cancers"; a cookie wall covers it. The reader now dismisses the consent, waits for frames to settle, and for
  this app sets it to lung cancer for all areas itself. Result: 29 values, 28 confirmed, 129 s
  (`examples/read_report_cancerregistry_statistics_page.json`).
- A 46-page THL guideline (julkari.fi, "Hoitoonpääsyn seuranta syövän hoidossa") returned 0 values and the UI
  showed nothing. It reports no results, only definitions. `notes_en` now always says so, and when a PDF has no
  measured value the reader asks once for the targets it states: 24 targets, all confirmed, 108 s, for example
  "6 weeks from referral to first treatment" (`value_kind: "target"`;
  `examples/read_report_thl_waiting_time_guideline_46_pages.json`).

### A figure published only as an image (`build_chart_read.py`)

The registry gives the stage classification by county only as Kuva 13, a stacked bar chart without numbers.
`gemini_reader.read_chart(png, figure=, caption=)` reads it: 22 counties x 5 classes = 110 rows in
`data/processed/gemini_chart_read.jsonl` (`read_from: "chart"`, `verified: false`, confidence 0.6, `figure: "Kuva 13"`).
Checks (`examples/chart_read_accuracy.json`):

| Check | Values | Mean error | Worst |
|---|---|---|---|
| A. Blind read of Kuva 12 (same design, printed counts painted out) against count / total in Taulukko 10 | 17 | 0.07 points | 0.2 |
| B. Each county value against the colour widths measured in the image | 110 | 0.20 points | 0.67 |
| C. County values weighted by Taulukko 11 patient counts against the national shares in Taulukko 4 | 5 | 0.04 points | 0.1 |

Two reads of Kuva 13 differ by at most 0.2 points. Rows are written only when A and B stay within 2 points.
Only this chart design was tested; line charts with confidence bands (Kuva 15-23) were not.

## Run it

```bash
PORT=8744 app/run.sh                     # the API with keys from the environment (8742 is the public demo)
cd app/server                            # the CLIs need the same keys in the environment:
python -m integrations.verify sbrt_pathway 21 [--out f.json]       # one check, steps on stderr
python -m integrations.scout 21 [--out f.json]
python -m integrations.prerun [--areas 21,10] [--dry]              # fill the store: funded measures x counties, scouts
python -m integrations.gemini_reader <url-or-file> [--hint "..."] [--out f.json]
python -m integrations.build_chart_read  # Kuva 13 -> rows + accuracy file (about 1 minute)
python -m integrations.syoparekisteri_app [--view N] [--append]    # the registry statistics app, all areas
PYTHONPATH=. python integrations/build_extracted.py                # rebuild data/processed/gemini_extracted.jsonl
```

| Env var | Used by | Notes |
|---|---|---|
| `JUNCTION_OXYLABS_API_KEY` | `oxylabs.py` | Oxylabs Web API key (Bearer). Without it a check answers with the stored result (`from_cache: true`). |
| `ANTHROPIC_API_KEY` | `llm.py` | Claude key; set `ANTHROPIC_BASE_URL` too when using a gateway. |
| `GEMINI_API_KEY` | `gemini_reader.py`, `llm.py` | The reader, and the model of the check and the scout when Claude is not reachable. `app/run.sh` and `deploy/start.sh` fill it from `JUNCTION_GEMINI_API_KEY`. |
| `KELLO_BRAIN=gemini` | `llm.py` | Force Gemini for the check and the scout (to test the hosted path locally). |

Files: `agent.py` (the loop), `llm.py` (Claude or Gemini behind one conversation), `verify.py`, `scout.py`, `prerun.py`,
`api.py` (routes), `oxylabs.py` (search, scrape, page cache), `pagetext.py` (main content, passages, links, PDF text),
`counties.py` (county and hospital names), `gemini_reader.py`, `syoparekisteri_app.py`, `build_chart_read.py`,
`build_extracted.py`.
