#!/bin/bash
# Make a voice-only copy of a finished render without re-rendering video: lays the VO files at the film's own
# line times (from src/timeline.ts), normalizes to -16 LUFS and swaps the audio track.
#   scripts/remux-nomusic.sh v3   -> out/kello-demo-v3-nomusic.mp4
set -euo pipefail
cd "$(dirname "$0")/.."
v=${1:?version, e.g. v3}
OUT=${KELLO_FILM_OUT:-out}
src="$OUT/out/kello-demo-$v.mp4"; dst="$OUT/out/kello-demo-$v-nomusic.mp4"
tmp=$(mktemp -d)
npx esbuild src/timeline.ts --bundle --platform=node --format=cjs --log-level=error --outfile="$tmp/t.cjs"
node -e "
const {SCENES, FPS, TOTAL} = require('$tmp/t.cjs');
const ls = SCENES.flatMap((s) => s.lines.map((l) => ({f: l.file, ms: Math.round((s.from + Math.round(l.at * FPS)) / FPS * 1000)})));
const ins = ls.map((l) => '-i $OUT/public/' + l.f).join(' ');
const fc = ls.map((l, i) => '[' + (i + 1) + ':a]adelay=' + l.ms + '|' + l.ms + '[a' + i + ']').join(';') + ';' + ls.map((_, i) => '[a' + i + ']').join('') + 'amix=inputs=' + ls.length + ':normalize=0,apad=whole_dur=' + (TOTAL / FPS) + '[vo]';
require('fs').writeFileSync('$tmp/args', ins + '\n' + fc);
"
ins=$(sed -n 1p "$tmp/args"); fc=$(sed -n 2p "$tmp/args")
# shellcheck disable=SC2086
nice -n 10 ffmpeg -nostdin -loglevel error -y -i "$src" $ins -filter_complex "$fc" -map '[vo]' -ac 2 -ar 48000 "$tmp/vo.wav"
m=$(ffmpeg -nostdin -hide_banner -i "$tmp/vo.wav" -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
gi() { echo "$m" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }
nice -n 10 ffmpeg -nostdin -loglevel error -y -i "$src" -i "$tmp/vo.wav" -map 0:v -map 1:a -c:v copy -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(gi input_i):measured_TP=$(gi input_tp):measured_LRA=$(gi input_lra):measured_thresh=$(gi input_thresh):offset=$(gi target_offset):linear=true,aresample=48000" -c:a aac -b:a 192k -shortest -movflags +faststart "$dst"
rm -f "$tmp/t.cjs" "$tmp/args" "$tmp/vo.wav"; rmdir "$tmp"
echo "$dst"
