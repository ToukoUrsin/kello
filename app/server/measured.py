"""Measured county gaps straight from data/processed/gemini_extracted.jsonl.

Used ONLY to fill v2 contract fields that kello_model.api does not return yet
(`national.headline_measured`, area `measured`, `measured_gaps`). Every value is a row read
from a registry report, with its page and verbatim quote; nothing is modelled here.
Anything filled from this module carries "measured_filled_by": "app-server".
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JSONL = ROOT / "data/processed/gemini_extracted.jsonl"
AREAS = ROOT / "data/processed/areas.json"

# key, indicator in the jsonl, label, direction, sex, level
SPEC = [
    ("curative_intent_pct", "lung_curative_intent_pct", "Patients given curative-intent treatment", "higher_is_better", "all", "county"),
    ("no_treatment_record_pct", "lung_no_treatment_record_pct", "Patients with no treatment recorded", "lower_is_better", "all", "county"),
    ("one_year_survival_pct", "lung_survival_1y_pct", "One-year survival, men", "higher_is_better", "men", "county"),
    ("dx_to_treatment_days", "lung_days_diagnosis_to_surgery", "Median days from diagnosis to surgery", "lower_is_better", "all", "collaborative_area"),
]
YTA_NAME = {"HUS": "Helsinki (HUS)", "TYKS": "Turku (TYKS)", "TAYS": "Tampere (TAYS)", "KYS": "Kuopio (KYS)", "OYS": "Oulu (OYS)"}


def _mtime() -> float:
    try:
        return JSONL.stat().st_mtime
    except OSError:
        return 0.0


@lru_cache(maxsize=2)
def _load(_stamp: float) -> dict:
    rows = []
    if JSONL.exists():
        for line in JSONL.read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    try:
        areas = json.loads(AREAS.read_text())
    except Exception:  # noqa: BLE001
        areas = []
    table: dict[str, dict[str, dict]] = {}
    for key, ind, _label, _dir, sex, _level in SPEC:
        cand = [r for r in rows if r.get("indicator") == ind and (r.get("sex") or "all") == sex and isinstance(r.get("value"), (int, float))]
        if not cand:
            continue
        # one period per indicator: the one that covers the most areas (the five-year or study window, not single years)
        periods: dict[str, int] = {}
        for r in cand:
            periods[r.get("period")] = periods.get(r.get("period"), 0) + 1
        period = max(periods, key=lambda p: (periods[p], str(p)))
        table[key] = {r["area_id"]: r for r in cand if r.get("period") == period}
    patients = {r["area_id"]: r for r in rows if r.get("indicator") == "lung_patients_n" and r.get("period") == "2019-2023"}
    return {"rows": rows, "areas": areas, "table": table, "patients": patients}


def data() -> dict:
    return _load(_mtime())


def _name(d: dict, aid: str) -> str:
    if aid.startswith("yta:"):
        return YTA_NAME.get(aid[4:], aid[4:])
    return next((a.get("short_en") for a in d["areas"] if a["id"] == aid), aid)


def _scope_rows(d: dict, key: str, level: str) -> dict[str, dict]:
    t = d["table"].get(key, {})
    if level == "collaborative_area":
        return {k: v for k, v in t.items() if k.startswith("yta:")}
    return {k: v for k, v in t.items() if not k.startswith("yta:") and k != "FI"}


def _row_for(d: dict, key: str, level: str, area_id: str) -> dict | None:
    t = d["table"].get(key, {})
    if level == "collaborative_area":
        yta = next((a.get("yta") for a in d["areas"] if a["id"] == area_id), None)
        return t.get(f"yta:{yta}") if yta else None
    return t.get(area_id)


def _prov(r: dict) -> dict:
    return {"period": r.get("period"), "source_url": r.get("source_url"), "page": r.get("page"), "quote": r.get("quote"),
            "read_by": r.get("read_by"), "verified": r.get("verified")}


def headline() -> list[dict]:
    d = data()
    out = []
    for key, _ind, label, direction, _sex, level in SPEC:
        rows = _scope_rows(d, key, level)
        if len(rows) < 2:
            continue
        lo = min(rows.values(), key=lambda r: r["value"])
        hi = max(rows.values(), key=lambda r: r["value"])
        nat = d["table"][key].get("FI")
        out.append({"key": key, "label_en": label, "value_low": lo["value"], "area_low": lo["area_id"], "area_low_en": _name(d, lo["area_id"]),
                    "value_high": hi["value"], "area_high": hi["area_id"], "area_high_en": _name(d, hi["area_id"]),
                    "national": nat["value"] if nat else None, "unit": lo.get("unit"), "direction": direction, "level": level,
                    "kind": "measured", **_prov(lo)})
    return out


def _rank(rows: dict[str, dict], value: float, direction: str) -> int:
    """1 = worst."""
    vals = [r["value"] for r in rows.values()]
    return 1 + sum(1 for v in vals if (v < value if direction == "higher_is_better" else v > value))


def _top_quartile(vals: list[float]) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(0.75 * (len(s) - 1))))]


def area_measured(area_id: str) -> dict:
    d = data()
    out: dict = {}
    for key, _ind, _label, direction, _sex, level in SPEC:
        r = _row_for(d, key, level, area_id)
        if not r:
            out[key] = None
            continue
        nat = d["table"][key].get("FI")
        out[key] = {"value": r["value"], "national": nat["value"] if nat else None, "rank": _rank(_scope_rows(d, key, level), r["value"], direction),
                    "unit": r.get("unit"), "level": level, **_prov(r)}
    return out


def patients_per_year(area_id: str) -> float | None:
    r = data()["patients"].get(area_id)
    return round(r["value"] / 5, 1) if r else None


def curative_gap(area_id: str) -> dict | None:
    d = data()
    rows = _scope_rows(d, "curative_intent_pct", "county")
    mine, ppy = rows.get(area_id), patients_per_year(area_id)
    if not mine or ppy is None or len(rows) < 4:
        return None
    q3 = _top_quartile([r["value"] for r in rows.values()])
    n = max(0.0, ppy * (q3 - mine["value"]) / 100)
    return {"value": round(n, 1), "top_quartile_pct": q3,
            "note_en": (f"Arithmetic, not a forecast: {ppy:.0f} patients a year x ({q3:.1f}% top-quartile county share - {mine['value']:.1f}% here). "
                        "It does not adjust for stage, age or other illness, which also decide who can be treated to cure.")}


def area_gaps(area_id: str) -> list[dict]:
    d = data()
    out = []
    for key, ind, label, direction, _sex, level in SPEC:
        r = _row_for(d, key, level, area_id)
        rows = _scope_rows(d, key, level)
        nat = d["table"].get(key, {}).get("FI")
        if not r or len(rows) < 2:
            continue
        better = max if direction == "higher_is_better" else min
        worse = min if direction == "higher_is_better" else max
        b = better(rows.values(), key=lambda x: x["value"])
        w = worse(rows.values(), key=lambda x: x["value"])
        g = {"indicator": ind, "key": key, "label_en": label, "value": r["value"], "national": nat["value"] if nat else None,
             "best": b["value"], "best_area": b["area_id"], "best_area_en": _name(d, b["area_id"]),
             "worst": w["value"], "worst_area": w["area_id"], "worst_area_en": _name(d, w["area_id"]),
             "rank": _rank(rows, r["value"], direction), "n_ranked": len(rows), "unit": r.get("unit"), "direction": direction,
             "level": level, "kind": "measured", **_prov(r)}
        if level == "collaborative_area":
            g["note_en"] = f"Published for the collaborative area ({_name(d, r['area_id'])}), not for the county alone."
        if key == "curative_intent_pct":
            cg = curative_gap(area_id)
            if cg and cg["value"] >= 0.5:
                g["gap_patients_per_year"] = cg["value"]
                g["note_en"] = cg["note_en"]
        out.append(g)

    def dist(g):
        if not g.get("national"):
            return 0
        rel = (g["value"] - g["national"]) / g["national"]
        return -(rel if g["direction"] == "lower_is_better" else -rel)  # worse than national first
    return sorted(out, key=dist)


def documents() -> list[dict]:
    """The reports Gemini read, with row counts (group by source_url)."""
    d = data()
    docs: dict[str, dict] = {}
    for r in d["rows"]:
        u = r.get("source_url")
        if not u:
            continue
        x = docs.setdefault(u, {"url": u, "rows": 0, "verified": 0, "pages": set(), "read_by": r.get("read_by"), "indicators": set()})
        x["rows"] += 1
        x["verified"] += 1 if r.get("verified") else 0
        if r.get("page") is not None:
            x["pages"].add(r["page"])
        x["indicators"].add(r.get("indicator"))
    out = []
    for x in docs.values():
        out.append({**x, "pages": len(x["pages"]), "indicators": len(x["indicators"])})
    return sorted(out, key=lambda x: -x["rows"])


def surgery_days_by_area() -> dict | None:
    """Median days from diagnosis to surgery for each collaborative area, as the registry report prints them."""
    d = data()
    t = d["table"].get("dx_to_treatment_days", {})
    rows = [{"yta": k[4:], "label_en": _name(d, k), "value": r["value"], "unit": r.get("unit"), **_prov(r)} for k, r in t.items() if k.startswith("yta:")]
    if len(rows) < 2:
        return None
    nat = t.get("FI")
    # Provenance of the table the area values come from (Table 4.1), not of the national row, which the report prints on another page.
    first = sorted(rows, key=lambda r: r["value"])[0]
    return {"label_en": "Median days from diagnosis to surgery, by collaborative area", "kind": "measured",
            "areas": sorted(rows, key=lambda r: r["value"]), "national": nat["value"] if nat else None,
            **{k: first.get(k) for k in ("period", "source_url", "page", "quote", "read_by", "verified")},
            "national_page": nat.get("page") if nat else None}
