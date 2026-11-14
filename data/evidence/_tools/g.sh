#!/bin/bash
# usage: g.sh slug regex [ctxchars]
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
f="$ROOT/data/raw/evidence/$1/page.txt"
c=${3:-220}
grep -o -i -E ".{0,$c}($2).{0,$c}" "$f" | head -${4:-8}
