#!/bin/bash
# usage: fetch.sh slug url
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
R="$ROOT/data/raw/evidence"
slug="$1"; url="$2"
d="$R/$slug"; mkdir -p "$d"
code=$(curl -sL --max-time 60 -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36" -H "Accept-Language: fi,en;q=0.8" -o "$d/page.bin" -w "%{http_code} %{content_type}" "$url")
if file "$d/page.bin" | grep -qi pdf; then pdftotext -layout "$d/page.bin" "$d/page.txt"; else pandoc -f html -t plain --wrap=none "$d/page.bin" -o "$d/page.txt" 2>/dev/null; fi
echo "$slug $code $(wc -c < "$d/page.txt" 2>/dev/null)"
