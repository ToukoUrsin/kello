#!/bin/bash
# Re-record every app shot of the film and render it, in one command. Use after the app's look changes.
#   film/recapture.sh v5                    -> captures + kello-demo-v5.mp4 (music) + kello-demo-v5-nomusic.mp4
#   KELLO_BASE=http://127.0.0.1:8742 film/recapture.sh v5
# Every capture step waits for a selector (film/shots.json), and "expect" steps stop the run if the page no longer
# says what the voice-over says. make-data.py then checks the live API against every spoken number.
# A failed shot keeps its old capture and the script stops before rendering.
set -euo pipefail
cd "$(dirname "$0")"
v=${1:?version, e.g. v5}
nice -n 10 ../.venv/bin/python capture/capture.py
python3 scripts/make-data.py
./render.sh "$v"
scripts/remux-nomusic.sh "$v"
