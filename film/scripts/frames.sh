#!/bin/bash
# Unpack each screen capture into JPEG frames (30 fps) next to it: public/frames/<id>/f00001.jpg ...
# The film shows captures as still images per frame (<Img>, with retries), not as video: on this box Chrome drops
# in-flight video-frame requests whenever a docker interface comes or goes (ERR_NETWORK_CHANGED), which kills a render.
# Skips a capture whose frames are newer than its mp4.
set -euo pipefail
OUT=${KELLO_FILM_OUT:-out}
cd "$OUT/public/captures"
for mp4 in *.mp4; do
	id=${mp4%.mp4}
	d="$OUT/public/frames/$id"
	[[ -f "$d/.done" && "$d/.done" -nt "$mp4" ]] && continue
	[[ -f "$(dirname "$0")/../src/data/captures/$id.json" ]] || continue
	mkdir -p "$d"
	find "$d" -name 'f*.jpg' -delete
	nice -n 10 ffmpeg -nostdin -loglevel error -i "$mp4" -vf fps=30 -q:v 2 "$d/f%05d.jpg"
	touch "$d/.done"
	echo "frames $id: $(find "$d" -name 'f*.jpg' | wc -l)"
done
