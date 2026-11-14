#!/bin/bash
# Review pack for a render: a frame every second, 5x4 contact sheets (20 s each), loudness, black stretches.
#   scripts/review.sh out/kello-demo-v1.mp4 out/review-v1
set -euo pipefail
in=$1; out=$2
mkdir -p "$out/frames"
rm -f "$out"/frames/*.jpg "$out"/sheet-*.jpg
ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate -of default=nw=1 "$in" > "$out/probe.txt"
nice -n 10 ffmpeg -nostdin -loglevel error -i "$in" -vf "fps=1,scale=960:-1" -q:v 3 "$out/frames/f%03d.jpg"
nice -n 10 ffmpeg -nostdin -loglevel error -pattern_type glob -i "$out/frames/f*.jpg" -vf "tile=5x4:padding=6:color=white" -q:v 3 "$out/sheet-%02d.jpg"
ffmpeg -nostdin -hide_banner -i "$in" -af ebur128=peak=true -f null - 2>&1 | grep -A14 "Summary" > "$out/loudness.txt" || true
ffmpeg -nostdin -hide_banner -i "$in" -vf "blackdetect=d=0.5:pix_th=0.05" -an -f null - 2>&1 | grep blackdetect > "$out/black.txt" || true
cat "$out/probe.txt" "$out/loudness.txt" "$out/black.txt"
