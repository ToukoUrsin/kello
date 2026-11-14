"""Sanity table:  python -m kello_model.report"""
from __future__ import annotations

import time

from . import api


def main():
    t0 = time.time()
    ov = api.overview()
    n = ov["national"]
    print(f"National: {n['total_days']['median']:.0f} days ({n['total_days']['lo']:.0f}-{n['total_days']['hi']:.0f}); "
          f"{n['patients_per_year']} patients/yr, {n['deaths_per_year']} deaths/yr; benchmarks "
          + ", ".join(f"{b['country']} {b['days']:g}" for b in n["benchmarks"]))
    print(f"{'county':<22}{'days':>6}{'80% interval':>14}  {'worst step':<10}{'cover':>6}{'pat/yr':>7}"
          f"{'deaths avoided @EUR1M':>23}  top pick")
    for a in sorted(ov["areas"], key=lambda a: a["rank"]):
        p = api.optimize(a["id"], 1_000_000)
        d = p["totals"]["deaths_avoided_per_year"]
        top = p["chosen"][0]["intervention_id"] if p["chosen"] else "-"
        t = a["total_days"]
        print(f"{a['short_en'][:21]:<22}{t['median']:>6.0f}{t['lo']:>7.0f}-{t['hi']:<6.0f}  {a['worst_step']:<10}"
              f"{a['data_coverage']:>6.2f}{a['patients_per_year']:>7.0f}"
              f"{d['median']:>9.2f} ({d['lo']:.2f}-{d['hi']:.2f})".ljust(100) + f"  {top}")
    fi = api.optimize("FI", 1_000_000)
    d = fi["totals"]["deaths_avoided_per_year"]
    print(f"FI @EUR1M: {d['median']:.1f} ({d['lo']:.1f}-{d['hi']:.1f}) deaths avoided/yr, {len(fi['chosen'])} picks; "
          "frontier: " + ", ".join(f"{f['budget_eur'] / 1e6:g}M:{f['deaths_avoided_per_year']:.1f}" for f in fi["frontier"]))
    print("inputs:", api.meta()["inputs"])
    print(f"({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
