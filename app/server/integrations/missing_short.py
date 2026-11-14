"""Write a short "what is missing" phrase into every stored check that found the action partly in place.

    cd app/server && python -m integrations.missing_short            # fill the checks that have none
    python -m integrations.missing_short --redo                      # write them all again
    python -m integrations.missing_short --dry                       # print, do not write

The map shows the phrase on the pin ("Partly in place. Missing: a written referral rule"). The model may only
shorten what the check already says in missing_en / model_reason_en; a phrase longer than 10 words, or one that
adds a number the check does not contain, is refused and the first clause of missing_en is used instead
(verify.missing_short). Needs ANTHROPIC_API_KEY (ANTHROPIC_BASE_URL if you use a gateway).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import verify

MODEL = os.environ.get("KELLO_CLAUDE_MODEL", "claude-opus-5-5")
SYSTEM = (
    "You shorten one finding of a web check for a map label. The check asked whether a health-care action is already "
    "running in a Finnish county and found it partly in place. Write what is still MISSING as a noun phrase of 4 to 9 "
    "words, plain English a hospital manager would use, no capital at the start (keep 'stage I', names and abbreviations as they are), no full stop. Use only what the text says is not "
    "shown, not found or to be asked; add nothing, no numbers that are not in the text. Say 'chest surgeon' for thoracic "
    "surgeon and 'precise radiotherapy' for stereotactic radiotherapy or SBRT. Answer with the phrase only."
)


def _ok(phrase: str, source: str) -> bool:
    words = phrase.split()
    if not 2 <= len(words) <= 10 or "\n" in phrase:
        return False
    return all(n in source for n in re.findall(r"\d+", phrase))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m integrations.missing_short")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    import anthropic

    client = anthropic.Anthropic(base_url=os.environ.get("KELLO_CLAUDE_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or None,
                                 api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(), timeout=60.0, max_retries=2)
    done = kept = 0
    for f in sorted(verify.STORE.glob("*__*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("in_use_here") not in ("partly", "planned", "yes") or (d.get("missing_short_en") and not a.redo):
            continue
        source = "\n".join(f"{k}: {d.get(k)}" for k in ("intervention_name_en", "in_use_here", "missing_en", "model_reason_en", "unanswered_en") if d.get(k))
        if not (d.get("missing_en") or d.get("model_reason_en")):
            continue
        try:
            msg = client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM, messages=[{"role": "user", "content": source}])
            phrase = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip().strip('"').rstrip(".")
        except Exception as e:  # noqa: BLE001 - a failed call leaves the check as it was
            print(f"{f.name}: no answer ({type(e).__name__})", file=sys.stderr)
            continue
        if not _ok(phrase, source):
            phrase = verify.missing_short(d.get("missing_en")) or ""
            kept += 1
        if not phrase:
            continue
        print(f"{f.name}: {phrase}")
        if not a.dry:
            d["missing_short_en"], d["missing_short_by"] = phrase, MODEL
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(f)
        done += 1
    print(f"{done} written, {kept} of them from the first clause of missing_en", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
