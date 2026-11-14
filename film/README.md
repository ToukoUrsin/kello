# Kello demo film

Remotion project for the Kello submission film (about 115 s, 1080p30, white, voice-over with burned-in captions).
Heavy outputs go to the ignored repo-relative **`film/out/`** by default (override with `KELLO_FILM_OUT`):

| Where | What |
|---|---|
| `public/captures/<shot>.mp4` | screen captures (3840×2160 from a 1920×1080 viewport, 60 fps) |
| `public/audio/vo-*.mp3` | voice-over, one file per line (ElevenLabs stock voice "George") |
| `out/kello-demo-vN.mp4` | renders; `out/review-vN/` frames every second, contact sheets, loudness |

## Files

- `script.json`: the voice-over, line by line, grouped in scenes. Scene lengths follow the synthesized lines.
- `shots.json`: the shot list for the screen captures (url, setup, steps, and named **marks** the film zooms to).
- `capture/capture.py`: records every shot from `shots.json` with Playwright; writes `<shot>.mp4` + metadata
  (cursor track, clicks, marks with element boxes, kept API answers) to `public/captures/` and the metadata to `src/data/captures/`.
- `scripts/make-data.py`: builds `src/data/film.json` (map, funnel, Nordic lines, Gemini rows, facts) from the repo's data;
  fails if a number the voice-over speaks moved. `FACTS.md` lists every number and its source.
- `scripts/make-vo.mjs`: voice-over via ElevenLabs; only changed lines are re-synthesized.
- `src/`: `Film.tsx` (scenes, audio, captions), `scenes/*.tsx`, `screen.tsx` (capture player: camera on marks, cursor, highlights).
- `render.sh`: typecheck, render, loudness to −16 LUFS, review pack.

## Re-capture when the UI changes, then re-render

```sh
cd <repo>
# 1. edit film/shots.json if selectors changed (put the new UI's target first in each "any" list; keep the mark names)
nice -n 10 .venv/bin/python film/capture/capture.py                 # all eight shots (plan waits for the Finnish plan, up to 5 min)
nice -n 10 .venv/bin/python film/capture/capture.py path verify     # or only some
KELLO_BASE=http://127.0.0.1:8743 .venv/bin/python film/capture/capture.py   # against a test server
# 2. render
cd film && ./render.sh v2            # -> out/kello-demo-v2.mp4 (+ review-v2/)
./render.sh v2 --fast                # half-size check render, ~4 min
```

Shots that are screen captures (v5): `home`, `dots`, `top`, `gap`, `card`, `plan`, `source`, `ask`. The scenes
(`src/scenes/V5.tsx`) find their zoom targets by mark name (`home/lap/best/chart/head`, `dots/switch/settled/lap_after/miss`,
`gap/head/strip/c0-c4`, `card/askpre/title/cost/first/owner/click/live_box/trace/done/vdiff/was/now/ask/quote`,
`plan/row/note/fi/title_fi`, `source/chip/focus/quote/read`, `ask/lead/acts/figs/f0-f3`); a missing mark falls back to the
whole page. `dots` records the plan's dot motion at 1/8 speed (`"slowmo": 0.125` step; the capture's meta `slowmo`
lists the stretch) and the Switch scene plays it back over 1.6 s. Voice: `script.json` `say_map` sends phonetic
spellings of Finnish names ("Kel lo", "Oh-oo-loo"); captions keep the written word.
One command re-records and renders: `KELLO_FILM_OUT=... ./recapture.sh v6`.

Music: a bed made for this film with ElevenLabs Music (`scripts/make-music.mjs`, prompt in `src/data/music.json`), ducked
under each voice line in `Film.tsx`. `KELLO_MUSIC=0 ./render.sh v3-nomusic` renders without it; `scripts/remux-nomusic.sh v3` makes a voice-only
copy of a finished render in a few seconds (no video re-render).

If a render dies with `net::ERR_NETWORK_CHANGED` / "Failed to fetch …/proxy?src=…captures…", Chrome saw the box's
network change (Docker containers starting and stopping); it is not disk space. Re-run when the churn stops.

Change a line: edit `script.json`, then `ELEVENLABS_API_KEY=... node film/scripts/make-vo.mjs` and render.
Preview: `npx remotion studio src/index.ts`.
