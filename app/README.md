# Kello app

Build and run (port 8742, serves the API and `web/dist`):

    app/run.sh --build     # pnpm install + build, then start
    app/run.sh             # start only

`run.sh` reads `.env` from the repository root when present; set the required API keys there or in the process environment.
Frontend dev: `cd app/web && pnpm dev` (proxies `/api` to 8742).

Fixtures (`server/fixtures/`, rebuilt by `server/fixtures/build_fixtures.py`) are used only when
`kello_model` and `data/model/*.json` are missing; every such response carries `"fixture": true`.

Screenshots and print PDFs of the last verification run are outside the repo:
Verification screenshots and print PDFs are kept outside the repository.
