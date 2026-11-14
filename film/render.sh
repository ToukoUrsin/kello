#!/bin/bash
# Render the Kello film: typecheck, render (composition Kello), loudness to -16 LUFS, then a review pack
# (a frame every second, contact sheets, loudness, black frames).
#   ./render.sh v1            -> $OUT/out/kello-demo-v1.mp4 and $OUT/out/review-v1/
#   ./render.sh v1 --fast     -> half-size review render (kello-demo-v1-half.mp4), no loudness pass
# Heavy outputs go to OUT=${KELLO_FILM_OUT:-out} (the repo-relative default is ignored).
set -euo pipefail
cd "$(dirname "$0")"
v=${1:?version, e.g. v1}
# KELLO_MUSIC=0 ./render.sh v2-nomusic   renders without the music bed
props="{\"music\": ${KELLO_MUSIC:-1}}"; props=${props/1\}/true\}}; props=${props/0\}/false\}}
OUT=${KELLO_FILM_OUT:-out}
mkdir -p "$OUT/out"
npx tsc --noEmit -p . && echo "typecheck OK"
python3 scripts/make-data.py
scripts/frames.sh
if [[ "${2:-}" == "--fast" ]]; then
	nice -n 10 npx remotion render src/index.ts Kello "$OUT/out/kello-demo-$v-half.mp4" --scale=0.5 --concurrency=24 --log=error --timeout=240000
	exit 0
fi
raw="$OUT/out/kello-demo-$v-raw.mp4"
final="$OUT/out/kello-demo-$v.mp4"
nice -n 10 npx remotion render src/index.ts Kello "$raw" --codec=h264 --crf=16 --concurrency=${KELLO_CONC:-12} --offthreadvideo-video-threads=${KELLO_OTV_THREADS:-4} --audio-codec=aac --audio-bitrate=192k --props="$props" --log=error --timeout=240000
# loudness: two-pass loudnorm to -16 LUFS / -1.5 dBTP, video copied
m=$(ffmpeg -nostdin -hide_banner -i "$raw" -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
gi() { echo "$m" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }
nice -n 10 ffmpeg -nostdin -loglevel error -y -i "$raw" -c:v copy -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(gi input_i):measured_TP=$(gi input_tp):measured_LRA=$(gi input_lra):measured_thresh=$(gi input_thresh):offset=$(gi target_offset):linear=true,aresample=48000" -c:a aac -b:a 192k -movflags +faststart "$final"
rm -f "$raw"
scripts/review.sh "$final" "$OUT/out/review-$v"
