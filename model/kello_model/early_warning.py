"""Early warning: 6-month forecast of "% waiting over 90 days" per area and specialty.

Method (deliberately simple): last value + half of last year's seasonal change over the same
months + a damped recent trend. Checked by rolling backtest; the interval comes from the
backtest errors, not from a distributional assumption.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

import numpy as np

from .inputs import FILES, MODEL, _read_jsonl

MEASURE = "queue_over_90d_pct"
H = 6
METHOD = ("Level = median of the last 3 monthly values (single months are noisy). Trend = Theil-Sen slope (median of all pairwise "
          "slopes) over the last 12 months, damped by 0.85 per month ahead. Forecast = level + damped trend, kept within 0-100. "
          "Backtest: the same rule applied at every past month with at least 18 months of history and compared with what happened "
          "6 months later; backtest_mae is the mean absolute error in percentage points (backtest_mae_naive: same for 'no change'), "
          "and the 80% band is the 10th-90th percentile of those errors. Flag = projected rise over 2 points AND at least 60% of "
          "pairwise slopes in the last 12 months point up. This is the all-diagnosis queue of the specialty, not lung cancer only.")
PHI = 0.85


def _slope(y):
    w = y[-12:]
    i, j = np.triu_indices(len(w), 1)
    sl = (w[j] - w[i]) / (j - i)
    return float(np.median(sl)), float((sl > 0).mean())


def _fc(y, h):
    """Forecast path for h steps ahead from series y."""
    level, (b, _) = float(np.median(y[-3:])), _slope(y)
    return [float(np.clip(level + b * sum(PHI ** i for i in range(1, k + 1)), 0, 100)) for k in range(1, h + 1)]


def _add_months(d: str, k: int) -> str:
    y, mth = int(d[:4]), int(d[5:7]) + k
    y, mth = y + (mth - 1) // 12, (mth - 1) % 12 + 1
    nxt = date(y + (mth == 12), mth % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1).isoformat()   # month end


def build():
    rows = _read_jsonl(FILES["queue_series"])
    if not rows:
        return None
    series = defaultdict(dict)
    notes = {}
    for r in rows:
        if r.get("measure") == MEASURE and r.get("value") is not None and r.get("specialty") in ("pulmonology", "oncology"):
            series[(r["area_id"], r["specialty"])][r["date"][:7]] = (r["date"], float(r["value"]))
            if r.get("note"):
                notes[(r["area_id"], r["specialty"])] = r["note"]
    out = []
    for (area, sp), d in sorted(series.items()):
        pts = [d[k] for k in sorted(d)]
        dates, y = [p[0] for p in pts], np.array([p[1] for p in pts])
        if len(y) < 24:
            continue
        errs = [_fc(y[:t], H)[-1] - y[t + H - 1] for t in range(18, len(y) - H + 1)]
        naive = [y[t - 1] - y[t + H - 1] for t in range(18, len(y) - H + 1)]
        mae = float(np.mean(np.abs(errs))) if errs else None
        lo_e, hi_e = (np.percentile(errs, [10, 90]) if len(errs) >= 8 else (-(mae or 5) * 1.6, (mae or 5) * 1.6))
        f = _fc(y, H)
        fc = []
        for k, v in enumerate(f, 1):
            sc = (k / H) ** 0.5
            fc.append({"date": _add_months(dates[-1], k), "value": round(v, 1),
                       "lo": round(float(np.clip(v - hi_e * sc, 0, 100)), 1), "hi": round(float(np.clip(v - lo_e * sc, 0, 100)), 1)})
        level, (slope, up_share) = float(np.median(y[-3:])), _slope(y)
        rise = f[-1] - level
        out.append({"area_id": area, "specialty": sp, "measure": MEASURE, "last": round(float(y[-1]), 1), "last_date": dates[-1],
                    "history": [{"date": dt, "value": v} for dt, v in pts[-24:]],
                    "forecast": fc, "backtest_mae": None if mae is None else round(mae, 2),
                    "backtest_mae_naive": round(float(np.mean(np.abs(naive))), 2) if naive else None,
                    "backtest_n": len(errs), "flag": bool(rise > 2.0 and up_share >= 0.6),
                    "trend": ("worsening" if rise > 2.0 and up_share >= 0.6 else
                              "improving" if rise < -2.0 and up_share <= 0.4 else "stable"),
                    "level_last3": round(level, 1), "slope_pp_per_month": round(slope, 2),
                    "change_pp": round(rise, 1), "kind": "estimated", "note": notes.get((area, sp)), "method_en": METHOD})
    MODEL.mkdir(parents=True, exist_ok=True)
    (MODEL / "early_warning.json").write_text(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    res = build() or []
    print(f"{len(res)} series, {sum(r['flag'] for r in res)} flagged")
