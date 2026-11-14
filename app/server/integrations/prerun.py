"""Run the live check for every funded measure in every county ahead of time, and the scout for
every county, so that the page has a stored answer when Oxylabs or the models do not answer.

    cd app/server && python -m integrations.prerun                  # all 23 counties, 1 M EUR, curative + default objective
    python -m integrations.prerun --areas 21,10,05 --no-scout       # some counties, checks only
    python -m integrations.prerun --dry                             # list what would run

Two runs at a time. A check stored by the current code and younger than 24 h is skipped, so the
command can be stopped and started again. When a run fails because no model answered, it waits
60 s and tries again (three times), and a failed run never replaces a stored result.
Needs the same env as the server (app/run.sh): JUNCTION_OXYLABS_API_KEY and ANTHROPIC_API_KEY
and/or GEMINI_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import counties, scout, verify

FIRST = ["21", "10", "05"]  # the counties shown in the demo go first


def _areas() -> list[str]:
    data = json.loads((counties.ROOT / "data" / "processed" / "areas.json").read_text(encoding="utf-8"))
    rows = data.get("areas") if isinstance(data, dict) else data
    ids = [str(a["id"]) for a in rows if counties.hints(str(a["id"]))]
    return [a for a in FIRST if a in ids] + [a for a in ids if a not in FIRST]


def funded(area_id: str, budget_eur: float, objectives: list[str | None]) -> list[str]:
    """Ids of the measures the optimiser funds for this county, over the given objectives."""
    import providers  # app/server/providers.py

    out: list[str] = []
    for obj in objectives:
        for c in providers.optimize(area_id, budget_eur, obj).get("chosen") or []:
            if c["intervention_id"] not in out:
                out.append(c["intervention_id"])
    return out


def _retry(run, failed, label: str, tries: int = 3) -> dict:
    res: dict = {}
    for attempt in range(tries):
        res = run()
        err = failed(res)
        if not err:
            break
        print(f"  {label}: {err[:140]}" + ("; waiting 60 s" if attempt + 1 < tries else "; giving up"), flush=True)
        if attempt + 1 < tries:
            time.sleep(60)
    return res


def _failed(res: dict) -> str | None:
    return res.get("error") or res.get("live_error")


def run_check(iv: dict, area_id: str) -> dict:
    res = _retry(lambda: verify.check_measure(iv, area_id), _failed, f"{iv['id']} {area_id}")
    row = {"kind": "check", "intervention_id": iv["id"], "area_id": area_id, "ok": not _failed(res),
           "in_use_here": res.get("in_use_here"), "in_use_scope": res.get("in_use_scope"), "effect_check": res.get("effect_check"),
           "plan_effect": res.get("plan_effect"), "rounds": res.get("rounds"), "seconds": res.get("seconds"),
           "models": res.get("models"), "quote": res.get("in_use_quote"), "url": (res.get("in_use_source") or {}).get("url"),
           "error": _failed(res)}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def run_scout(area_id: str) -> dict:
    res = _retry(lambda: scout.scout(area_id), _failed, f"scout {area_id}")
    row = {"kind": "scout", "area_id": area_id, "ok": not _failed(res), "findings": len(res.get("findings") or []),
           "rounds": res.get("rounds"), "seconds": res.get("seconds"), "models": res.get("models"), "error": _failed(res)}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m integrations.prerun")
    ap.add_argument("--areas", help="comma-separated county ids; default: all 23")
    ap.add_argument("--budget", type=float, default=1_000_000)
    ap.add_argument("--objectives", default="curative,default", help="optimiser objectives whose funded measures are checked")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-age-h", type=float, default=24.0)
    ap.add_argument("--no-checks", action="store_true")
    ap.add_argument("--no-scout", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    areas = [x.strip() for x in a.areas.split(",") if x.strip()] if a.areas else _areas()
    objectives = [None if o.strip() in ("", "default") else o.strip() for o in a.objectives.split(",")]
    ivs = json.loads((counties.ROOT / "data" / "evidence" / "interventions.json").read_text(encoding="utf-8"))
    by_id = {i["id"]: i for i in (ivs.get("interventions") if isinstance(ivs, dict) else ivs)}
    age = a.max_age_h * 3600

    checks, skipped = [], 0
    if not a.no_checks:
        for area in areas:
            for iid in funded(area, a.budget, objectives):
                if verify.is_fresh(iid, area, age):
                    skipped += 1
                elif iid in by_id:
                    checks.append((by_id[iid], area))
    scouts = [] if a.no_scout else [ar for ar in areas if not scout.is_fresh(ar, age)]
    print(f"{len(checks)} checks to run ({skipped} stored and fresh), {len(scouts)} scouts to run, {a.workers} at a time", flush=True)
    if a.dry:
        for iv, area in checks:
            print(f"  check {iv['id']} {area}")
        for ar in scouts:
            print(f"  scout {ar}")
        return 0

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        rows = list(pool.map(lambda x: run_check(*x), checks))
        rows += list(pool.map(run_scout, scouts))
    bad = [r for r in rows if not r["ok"]]
    print(f"done in {int(time.time() - t0)} s: {len(rows) - len(bad)} stored, {len(bad)} failed", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
