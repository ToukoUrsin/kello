# Kello

In Lapland 18 of 100 lung cancer patients get treatment that aims to cure. In Vantaa and Kerava, 36.
Kello shows each Finnish wellbeing services county where it loses those patients, and gives it a costed plan to get them back.

Junction 2026, AstraZeneca challenge "Equal Care Across Finland". Live demo: https://kello-care.fly.dev · deck: `docs/deck/kello-deck.pdf`

## What is live and what is stored

Live: the web check (Oxylabs Web API searches and page reads, with the answer written by Claude or Gemini), the optimiser, and the scout. Stored: 966 registry values read by Gemini (946 re-confirmed, 20 unverified), county plan texts written once by Claude and served from `app/server/cache`, and page reads cached for speed.

## Run it

Create `.env` in the repository root with the keys below, then run:

```bash
app/run.sh --build
```

Set `JUNCTION_OXYLABS_API_KEY`, `GEMINI_API_KEY`, and `ANTHROPIC_API_KEY`; set `ANTHROPIC_BASE_URL` only when using a gateway.

## What it shows

- **The gap, measured.** Share of lung cancer patients who get treatment that aims to cure, 2019–2023: Lapland 18.5%,
  Finland 27.0%, Vantaa and Kerava 35.6%. 12 of 22 counties are further from the national rate than chance explains.
  Across Finland about 66 patients a year miss that treatment, 50 of them in seven counties.
- **Is it real?** Five checks per county: chance, age, stage at diagnosis, missing records, deaths and survival.
  For Lapland two say clearly yes, two mostly yes, and one cannot be answered from public data: stage is not published
  by county, and an 8-week chart audit settles it.
- **Where on the care path.** Four steps per county: found early enough, referred fast enough, treated fast enough,
  given treatment that aims to cure. Lapland falls behind at the last one only. Its patients do not wait longer (31 days
  from diagnosis to treatment in the Oulu university hospital area, 37 in Finland). About 12 a year are missing from
  curative treatment: 7 not operated, 5 not given curative radiotherapy.
- **Two more findings.** Across counties, the further people live from a university hospital, the fewer are treated to
  cure (rank correlation −0.66; −0.37 with the share of residents over 65 held fixed). Drug treatment is on record for
  10.3% of Lapland's patients against 25.1% in Finland; that field is the registry's least reliable.
- **What to do.** For Lapland six actions for €211,500 a year, about 5 of the 12 patients (range 0–7.7, modelled).
  Each action has an owner, a first step this week, the county's own reason for it and the study its effect comes from.
  A live web check asks whether the action is already running there, and the plan changes with the answer.
- **Who does what on Monday.** One printable page per county (`#/monday/21`, Finnish or English): each row is one
  person's job, with the owner's role, the first step this week, the cost a year and what done looks like in 90 days.
- **The ask.** Six months with Lapland and the Oulu university hospital. Week 1: ask the hospital which actions already
  run. Weeks 1–8: audit 50 charts (€8,000). Months 3–6: start the two actions the audit says are new. Counted: about
  71 patients, 64 decisions not to operate reviewed, decisions changed, referrals made. Model estimate: 18.5% → 20.5%
  treated to cure by 2028.
- **A one-page plan** per county, and one for Finland, in Finnish or English.

Every number is tagged `measured`, `estimated` or `assumption` and opens the page and sentence it came from. Public
aggregate data only. No patient-level data, no individual risk prediction. No trial has measured these effects, so
every range starts at zero.

`#/reset` puts a running demo back to its start state (stored web checks, anything the browser remembers).

## Data pipeline

```bash
uv venv && uv pip install -r requirements.txt
.venv/bin/python pipeline/run_all.py            # public data -> data/processed/
.venv/bin/python -m kello_model.precompute      # model outputs -> data/model/ (16 s)
app/run.sh --build                              # http://localhost:8742
```

The app reads keys from the environment; see “Run it” above.

## Sponsor tech

**Oxylabs Web API — "Live web check": the plan is checked against the web before the money is spent.** Each
funded measure has a button that asks one specific question at the moment you click: is this measure already
running in this county, or in the university hospital area that treats its patients, and does recent evidence
support the size of effect we assume?

- `POST https://webapi.oxylabs.io/v1/search` finds the pages. Round 1 is four Finnish searches written by code
  with the words a local page uses ("OYS keuhkosyöpäpotilaan hoitopolku", "Lapha potilashotelli"), run from
  Finland so county, hospital and registry pages rank first.
- `POST https://webapi.oxylabs.io/v1/scrape` reads them: plain fetch, a JavaScript render when a page comes
  back as navigation only, PDFs as text. We keep the passages that match the question and follow the page's
  own links from a hub page to the page that answers.
- The agent loop (Claude; Gemini when Claude is not reachable) reads three to five pages in parallel, names
  what is still unanswered, and searches again: at most 3 rounds, about 75 s. Every step is shown live with
  its endpoint, URL and time.
- Code, not the model, enforces the rules: a quote that is not literally in a page read in this run is
  dropped, and "in use" needs a page that names the county or its university hospital.

What changes in the plan: `yes` takes the measure out and frees its euros for the next one; `partly` or
`planned` flags the line with what to ask whom ("Ask OYS first whether every frail stage I patient is already
referred"); "no public sign of it" keeps the line and says what was searched. Example, Lapland: the check
found on OYS's own pathway page that the university hospital already "vastaa keuhkosyövän moniammatillisista
kokouksista" (runs the lung cancer team meetings), so the video-meeting line is flagged instead of paid in full.
Example of `yes`, Satakunta: direct CT referral from the health centre is "already running", from a
Satakunnan Kansa article of 11.11.2026 ("Vuonna 2022 pilottina alkanut toimintamalli vakiintui käyttöön
vuonna 2024"), found in one round and 21 s.
The last good result per measure and county is stored, so the button answers even when the web or the model
does not. Code: `app/server/integrations/` (`verify.py`, `agent.py`, `oxylabs.py`, `llm.py`); details and
measured runs in its `README.md`; real outputs in `examples/verify_*.json`.

**Gemini API — reading reports that have no API.** County-level lung cancer quality data in Finland exists only in
PDFs, a Shiny app and dashboards. Gemini (`gemini-4-hydrogen`) read them into 966 rows, each with page number
and the quoted text it was read from (`data/processed/gemini_extracted.jsonl`). These rows are what the map leads
with. In the app, "Read a report" does the same for any URL or uploaded file. Code: `app/server/integrations/gemini_reader.py`.

**Reproducible analyses.** `science/drive.py` drives a local analysis app from a script and
answers its permission cards from a fixed allowlist. Each analysis is saved with its code, environment and
execution log under `science/out/` and listed in the app under Sources & method.

## Hosted demo

`https://kello-care.fly.dev` runs on Fly.io (one small always-on machine in Stockholm) and needs nothing else running.

```bash
deploy/fly.sh            # build app/web into deploy/dist, build the image, deploy
deploy/fly.sh --dist     # ship app/web/dist as it is
deploy/fly.sh --secrets  # only resend the Oxylabs and Gemini keys
```

The image (`Dockerfile`, `fly.toml`, `.dockerignore`) holds the API, the built web app, `data/processed`,
`data/model`, `data/evidence`, `science/out` and the stored plans, checks, scouts and report reads. The hosted copy serves Claude-written plans from the stored pages (a budget that is not stored shows the nearest stored plan, labelled),
the live check and the scout run on Oxylabs with Gemini as the model, and when a live run fails the stored
result is shown with its date. Keys are Fly secrets (`JUNCTION_OXYLABS_API_KEY`, `JUNCTION_GEMINI_API_KEY`).

## Layout

`pipeline/` data scripts · `data/processed/` clean data and sources · `data/evidence/` measures and parameters ·
`model/kello_model/` simulation and optimiser · `app/server/` API · `app/web/` frontend · `science/` Claude Science.
Shared contract: `docs/CONTRACT.md`.

## Limits

- Cancer stage is not published per county, so early-detection gaps are inferred, not measured.
- Our first model, an estimated clock from first symptom to treatment, does not correlate with measured outcomes across counties (Spearman −0.30, p = 0.17 for
  curative-intent share). The app says so and leads with the measured gaps.
- All costs except the symptom campaign are assumptions and can be edited.
