"""Run the whole Kello data pipeline and write data/processed/*.

    .venv/bin/python pipeline/run_all.py            # fresh downloads
    KELLO_CACHE=1 .venv/bin/python pipeline/run_all.py                           # reuse data/raw

Outputs: sources.json, indicators.jsonl, indicators_catalog.json, thl_queue_series.jsonl,
nordic_benchmarks.json, pipeline_report.json; adds population fields to areas.json.
"""
from __future__ import annotations

import importlib
import json
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import PARTS, PROC, AREA_IDS, now_iso, load_areas  # noqa: E402

MODULES = ["p01_sotkanet", "p02_thl_queues", "p03_statfin", "p04_nordcan", "p05_fcr", "p06_kela", "p07_distance"]
YTA_CODE = {"Etelä-Suomen yhteistyöalue": "HUS", "Itä-Suomen yhteistyöalue": "KYS", "Sisä-Suomen yhteistyöalue": "TAYS",
            "Länsi-Suomen yhteistyöalue": "TYKS", "Pohjois-Suomen yhteistyöalue": "OYS", "Ahvenanmaa": "ALAND"}


def main():
    if PARTS.exists():
        shutil.rmtree(PARTS)
    rows, sources, catalog, problems, extra = [], {}, {}, [], {}
    for name in MODULES:
        print(f"[{now_iso()}] {name} ...", flush=True)
        try:
            out = importlib.import_module(name).run()
        except Exception as e:  # one failing source must not stop the others
            traceback.print_exc()
            problems.append(f"{name}: crashed: {e!r}")
            continue
        rows += out.rows
        sources.update(out.sources)
        catalog.update(out.catalog)
        problems += out.problems
        extra[name] = out.extra
        print(f"    {len(out.rows)} rows, {len(out.sources)} sources, {len(out.problems)} problems", flush=True)

    # de-duplicate (area, indicator, period, sex): first writer wins
    seen, uniq = set(), []
    for r in rows:
        k = (r["area_id"], r["indicator"], r["period"], r.get("sex"))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    rows = sorted(uniq, key=lambda r: (r["indicator"], r["area_id"], r["period"], r.get("sex") or ""))

    # coverage per indicator at its latest period
    cov = {}
    for key in catalog:
        rs = [r for r in rows if r["indicator"] == key]
        if not rs:
            continue
        latest_by_area = {}
        for r in rs:
            if r["area_id"] not in latest_by_area or r["period"] > latest_by_area[r["area_id"]]:
                latest_by_area[r["area_id"]] = r["period"]
        areas = [a for a in latest_by_area if a != "FI"]
        cov[key] = {"n_areas": len(areas), "has_national": "FI" in latest_by_area,
                    "latest_period": max(latest_by_area.values()), "periods": sorted({r["period"] for r in rs}),
                    "missing_areas": sorted(set(AREA_IDS) - set(areas)), "source_ids": sorted({r["source_id"] for r in rs})}
    catalog = {k: {**v, **cov[k]} for k, v in sorted(catalog.items()) if k in cov}

    PROC.mkdir(parents=True, exist_ok=True)
    (PROC / "indicators.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (PROC / "sources.json").write_text(json.dumps(dict(sorted(sources.items())), ensure_ascii=False, indent=1))
    (PROC / "indicators_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1))
    (PROC / "pipeline_report.json").write_text(json.dumps(
        {"generated_at": now_iso(), "rows": len(rows), "indicators": len(catalog), "sources": len(sources),
         "unverified_sources": sorted(k for k, v in sources.items() if not v.get("verified", True)),
         "problems": problems}, ensure_ascii=False, indent=1))

    # areas.json: add population, 65+ share, verify yta (keep existing keys and ids)
    areas = load_areas()
    latest = {}
    for r in rows:
        if r["indicator"] in ("pop_total", "pop_65plus_pct"):
            k = (r["area_id"], r["indicator"])
            if k not in latest or r["period"] > latest[k]["period"]:
                latest[k] = r
    yta = extra.get("p01_sotkanet", {}).get("yta_by_area", {})
    for a in areas:
        p, s = latest.get((a["id"], "pop_total")), latest.get((a["id"], "pop_65plus_pct"))
        if p:
            a["population"] = p["value"]
            a["population_period"] = p["period"]
        if s:
            a["pop_65plus_pct"] = s["value"]
        names = yta.get(a["id"]) or []
        if names and names[0] in YTA_CODE:
            code = YTA_CODE[names[0]]
            if a.get("yta") != code:
                a["yta_previous"] = a.get("yta")
                a["yta"] = code
            a["yta_name_fi"] = names[0]
            a["yta_verified"] = True
            a["yta_source_id"] = "sotkanet_regions"
    (PROC / "areas.json").write_text(json.dumps(areas, ensure_ascii=False, indent=1))

    print(f"\n{len(rows)} indicator rows, {len(catalog)} indicators, {len(sources)} sources")
    print(f"\n{'indicator':52s} {'areas':>5s} {'FI':>3s}  latest period")
    for k, v in catalog.items():
        print(f"{k:52s} {v['n_areas']:5d} {'y' if v['has_national'] else '-':>3s}  {v['latest_period']}")
    print("\nPROBLEMS / NOT VERIFIED")
    for p in problems:
        print(" -", p[:300])
    for k, v in sources.items():
        if not v.get("verified", True):
            print(" - verified:false source:", k, v["url"])


if __name__ == "__main__":
    main()
