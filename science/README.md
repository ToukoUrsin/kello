# Claude Science on this box

State on 2026-11-13 23:40 EET: installed, sandbox on, signed in (Max plan), two analyses run from the
script and collected:

- `out/nordic_gap/`: NORDCAN survival 1990–2024, Finland against the Sweden/Norway average (lung, pancreas, liver).
- `out/county_funnel/`: funnel plot of curative-intent treatment share by county, with control limits.

Each folder has `answer.md`, `artifacts/` (figures, CSVs, the script), `provenance/` (environment and lineage per
artifact), `execution_log.json`, `approvals.jsonl` (every permission card and how it was answered) and a
hand-written `meta.json` (title, one-paragraph finding, main figure) that the app shows under Sources & method.

Three things that cost time, now handled in `drive.py`:

- Start the daemon **without** `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` in the
  environment. If it inherits a proxy base URL, every model call fails with "Your Claude session is no longer valid".
  `env -u ANTHROPIC_BASE_URL -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude-science serve --no-browser --detached --port 8780`
- A network card is only honoured when approved with `scope: "always"`.
- A `usage_checkpoint` card inside the plan's own limit is answered "keep going"; one with `boundary: "overage"`
  (paid usage credits) is refused.

## Install and start

```bash
curl -fsSL https://claude.ai/install-claude-science.sh | bash      # -> ~/.local/bin/claude-science (0.1.72)
claude-science serve --no-browser --detached --port 8780           # app 8780, HTML previews 8781, host 127.0.0.1
claude-science status                                              # JSON; sandbox_active must be true
claude-science stop
```

Data lives in `~/.claude-science` (13 GB after the starter Python/R environments).

One system change was needed. Ubuntu 24.04 blocks bubblewrap's user namespaces
(`kernel.apparmor_restrict_unprivileged_userns = 1`), so the sandbox refused to start. Fixed with an
AppArmor profile for bwrap only; the sysctl is unchanged:

```
/etc/apparmor.d/bwrap        profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

To undo: `sudo apparmor_parser -R /etc/apparmor.d/bwrap`, then delete that file.

## Sign-in

Two layers:

1. **Local app session** (scriptable). `claude-science url` prints a single-use link valid 3 minutes.
   `GET` it, then `POST /api/auth/nonce {"nonce": ...}`; the app sets `operon_auth` and `operon_csrf`
   cookies. `drive.py` does this and keeps the cookie in `science/.session/` (gitignored, mode 600).
2. **Claude account** (needs a person). OAuth on claude.ai. From this box it is blocked by bot checks:
   the T3 browser gets a Cloudflare "Verify you are human" box, and the personal Chrome reaches the
   consent page but Authorize answers "Couldn't verify your browser".

Paste-code route, works from any device signed in to claude.ai:

```bash
python science/drive.py signin-url           # prints a claude.ai URL, valid 10 minutes
# open it, click Authorize, copy the code shown
python science/drive.py signin-code '<code>'
python science/drive.py status               # signed_in: true, email, plan
```

The plan must be Pro, Max, Team or Enterprise; on Team/Enterprise an Owner must have turned Claude
Science on. Do not copy credentials between unrelated environments.

## drive.py

```bash
python science/drive.py --project kello --prompt-file science/prompts/nordic_gap.md --out science/out/nordic_gap/
python science/drive.py collect --frame <root_frame_id> --out science/out/<name>/
```

It uses the web app's own HTTP API under `http://localhost:8780/api` (route table read from the web
bundle; a session is a "frame"):

| Step | Call |
| - | - |
| find or create project | `GET /projects`, `POST /projects {name}` |
| start a session | `POST /projects/{pid}/request {input_data:{request}}` |
| poll | `GET /frames/{id}?include_children=true`, field `status` |
| permission cards | `output_data.pending_input_requests[]` -> `POST /frames/{id}/resolve-input {responses:[{requestId, tool_id, approved, action, scope, mode}]}` |
| plan approval | `POST /frames/{id}/approve-plan` |
| results | `GET /frames/{id}/artifacts`, `/artifacts/versions/{vid}`, `/artifacts/{id}/lineage`, `/frames/{id}/execution-log`, `/frames/{id}/export` |

Card policy (`decide()` in `drive.py`): allow `local_exec` for Python, R, shell and environment
setup, scope "this conversation"; allow `network` only for canapi.iarc.who.int, nordcan.iarc.who.int,
sotkanet.fi, pxdata.stat.fi, sampo.thl.fi and the PyPI, conda and CRAN hosts; allow `host` folders only
under `science/work/`. Everything else is denied. Each decision is logged to `<out>/approvals.jsonl`.

Output folder: `artifacts/` (figures, tables, scripts), `provenance/<file>.lineage.json` (the code,
language, environment snapshot and dependencies that produced each artifact), `code/`, `execution_log.json`,
`session_export.json` (full transcript and approval decisions), `answer.md`, `manifest.json` (sha256 per file).

Tested: local session, `status`, project creation, `signin-url`, and `collect` on an Example-project
session (3 PNGs, checksums match the app's). **Not tested, because no account is signed in:** starting
a session, the card loop, and lineage on freshly generated artifacts. Expect to adjust field names on the first live run.

## Our data as a connector or skill

- **Connector = MCP server.** Settings > Connectors > Add connector: *Remote* (HTTPS, SSE or Streamable
  HTTP) or *Local command* (stdio; runs inside the sandbox with the same network limits and its own
  writable folder). API: `POST /api/mcp-servers` and `POST /api/mcp-servers/local`; rows land in the
  `custom_mcp_servers` table. A Finnish-data connector would be a small stdio MCP server exposing tools
  such as `sotkanet_indicator(id, region, year)`, `nordcan_survival(cancer, sex, countries)`,
  `kello_indicators(area_id)` reading `data/processed/indicators.jsonl`. Every tool starts as "ask
  before use". Not registered yet.
- **Skill = a folder with `SKILL.md`** (YAML front matter `name`, `description`, `license`, then
  Markdown; optional `kernel.py` helpers). Bundled ones are in `~/.claude-science/skills/`; custom ones
  are stored in the database (`custom_skills`) and come in through Settings or `POST /api/skills/import`
  (file upload). The docs say not to edit `~/.claude-science` by hand, so do not drop folders in.

## Not possible

- No public API and no API key mode for this purpose; a person must authorize once on claude.ai.
- The local API is undocumented and can change with any update (auto-update is on; pin with `--no-auto-update`).
- Projects and artifacts do not sync between machines; they exist only in `~/.claude-science` here.
- Restarting the daemon signs every browser tab out of the local app (the Claude account sign-in is kept).
