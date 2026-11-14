"""Read a figure that the Cancer Registry publishes only as an image into numbers, and measure the error.

The registry's lung cancer report (data/raw/fcr/fcr_lung_quality_report.html) gives the stage
classification by wellbeing services county only as Kuva 13, a stacked bar chart with no numbers.
Gemini reads it (gemini_reader.read_chart). Three checks, all written to examples/chart_read_accuracy.json:

  A  blind test on Kuva 12 (same design, collaborative areas): the counts printed in its bars are
     painted out before Gemini sees it; truth = printed count / area total from Taulukko 10.
  B  every county value against a pixel measurement of the same bar (the ruler is itself checked
     against the Taulukko 10 truth on Kuva 12).
  C  the county values, weighted by the county totals of Taulukko 11, against the national
     shares printed in Taulukko 4.

Rows go to data/processed/gemini_chart_read.jsonl only when A and B pass (ERR_LIMIT_PP).

    python -m integrations.build_chart_read          (needs GEMINI_API_KEY; about 1 minute)
"""

from __future__ import annotations

import base64
import html as html_mod
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pymupdf

from . import gemini_reader as g

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "fcr" / "fcr_lung_quality_report.html"
URL = "https://syoparekisteri.fi/assets/themes/ssy3/factsheets/keuhkosyoparaportti.html"
OUT_ROWS = ROOT / "data" / "processed" / "gemini_chart_read.jsonl"
EXAMPLES = Path(__file__).resolve().parent / "examples"
MODEL = g.OFFLINE_MODEL  # done ahead of time, nobody waits: the strongest Gemini on the key
ERR_LIMIT_PP = 2.0   # largest error (percentage points) we accept before shipping rows
PERIOD = "2019-2023"
SERIES = {  # legend name -> (indicator, English label)
    "TNM": ("lung_stage_class_tnm_pct", "Stage reported to the registry as TNM"),
    "Stage": ("lung_stage_class_stage_pct", "Stage reported to the registry as a stage group"),
    "Sanallinen": ("lung_stage_class_verbal_pct", "Stage reported to the registry in words only"),
    "Syre -levinneisyys": ("lung_stage_class_registry_coded_pct", "Stage coded by the registry (Syre) from other records"),
    "Ei tietoa": ("lung_stage_unknown_pct", "No stage information in the registry"),
}
# Kuva 12: counts printed in the bars; totals per collaborative area from Taulukko 10
K12_TOTAL = {"Etelä-Suomen yhteistyöalue": 5497, "Itä-Suomen yhteistyöalue": 2236, "Länsi-Suomen yhteistyöalue": 2568,
             "Pohjois-Suomen yhteistyöalue": 2134, "Sisä-Suomen yhteistyöalue": 2339}
K12_COUNT = {
    "Etelä-Suomen yhteistyöalue": {"Ei tietoa": 2704, "Syre -levinneisyys": 1103, "TNM": 1485},
    "Itä-Suomen yhteistyöalue": {"Ei tietoa": 1189, "Syre -levinneisyys": 407, "TNM": 558},
    "Länsi-Suomen yhteistyöalue": {"Ei tietoa": 1192, "Syre -levinneisyys": 391, "Stage": 157, "TNM": 745},
    "Pohjois-Suomen yhteistyöalue": {"Ei tietoa": 879, "Syre -levinneisyys": 354, "Sanallinen": 418, "TNM": 441},
    "Sisä-Suomen yhteistyöalue": {"Ei tietoa": 1065, "Syre -levinneisyys": 341, "TNM": 817},
}
T4_NATIONAL = {"TNM": 27.3, "Sanallinen": 5.8, "Stage": 1.7, "Syre -levinneisyys": 17.6, "Ei tietoa": 47.7}  # Taulukko 4
PALETTE = {"Ei tietoa": (0, 119, 175), "TNM": (255, 180, 0), "Syre -levinneisyys": (247, 73, 64),
           "Sanallinen": (136, 126, 179), "Stage": (255, 224, 1)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def figure_png(n: int, raw: str) -> bytes:
    """The n-th <img> of the report (Kuva n for n = 1..13)."""
    imgs = re.findall(r'<img[^>]*src="data:image/png;base64,([^"]+)"', raw)
    return base64.b64decode(imgs[n])


def report_text(raw: str) -> str:
    s = re.sub(r"data:[a-z/+\-.0-9]+;base64,[A-Za-z0-9+/=]+", "", raw)
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    return " ".join(html_mod.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def county_totals(text: str) -> dict[str, int]:
    """Patients per county id from Taulukko 11 (the 'Yhteensä' column of its first block)."""
    block = text[text.index("Taulukko 11: "):]
    block = block[:block.index("Jarruttava")]
    out = {}
    for m in re.finditer(r"([A-ZÅÄÖ][\wåäöÅÄÖ\- ]*?(?:hyvinvointialue|kaupunki|Ahvenanmaa\w*)) (\d+) (\d+) \d+\.\d", block):
        name = re.sub(r"^.*yhteistyöalue ", "", m.group(1)).strip()
        out[g.map_area(name) or name] = int(m.group(3))
    return out


def _rgb(png: bytes) -> np.ndarray:
    pm = pymupdf.Pixmap(png)
    if pm.alpha:
        pm = pymupdf.Pixmap(pm, 0)
    if pm.n != 3:
        pm = pymupdf.Pixmap(pymupdf.csRGB, pm)
    return np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, 3).astype(int).copy()


def _labels(a: np.ndarray) -> np.ndarray:
    """Per pixel: index of the legend colour, or -1."""
    pal = np.array(list(PALETTE.values()))
    d = np.abs(a[:, :, None, :] - pal[None, None, :, :]).sum(3)
    lab = d.argmin(2)
    lab[d.min(2) > 12] = -1
    return lab


def pixel_shares(png: bytes) -> list[dict[str, float]]:
    """Exact share of each legend colour in every bar, top to bottom (the ruler for check B)."""
    lab = _labels(_rgb(png))
    wide = (lab >= 0).sum(1)
    in_bar = wide > 0.5 * wide.max()                 # legend swatches and axis text are far narrower
    cols = np.where((lab[in_bar] >= 0).mean(0) > 0.5)[0]   # the bars' own x range (the area labels share a legend colour)
    runs = np.split(cols, np.where(np.diff(cols) > 40)[0] + 1)   # a group rule left of the labels can share the colour too
    run = max(runs, key=len)
    x0, x1 = run.min(), run.max() + 1
    bars, y = [], 0
    while y < len(in_bar):
        if in_bar[y]:
            y0 = y
            while y < len(in_bar) and in_bar[y]:
                y += 1
            if y - y0 >= 6:
                row = lab[y0 + max(2, int(0.15 * (y - y0))), x0:x1]   # above any number printed in the middle of the bar
                n = (row >= 0).sum()
                bars.append({name: round(float(100 * (row == i).sum() / n), 2) for i, name in enumerate(PALETTE)})
        else:
            y += 1
    return bars


def blind(png: bytes) -> bytes:
    """The figure with the numbers printed inside the bars painted over in the bar's own colour."""
    a = _rgb(png)
    lab = _labels(a)
    white = a.min(2) > 235
    pal = np.array(list(PALETTE.values()))
    out = a.copy()
    for y in range(a.shape[0]):
        x, n = 0, a.shape[1]
        while x < n:
            if lab[y, x] < 0 and not white[y, x]:
                x0 = x
                while x < n and lab[y, x] < 0 and not white[y, x]:
                    x += 1
                if x0 > 0 and x < n and lab[y, x0 - 1] >= 0 and lab[y, x0 - 1] == lab[y, x]:
                    out[y, x0:x] = pal[lab[y, x]]
            else:
                x += 1
    pm = pymupdf.Pixmap(pymupdf.csRGB, a.shape[1], a.shape[0], out.astype(np.uint8).tobytes(), False)
    return pm.tobytes("png")


def _stats(errs: list[float]) -> dict:
    ab = sorted(abs(e) for e in errs)
    return {"n": len(ab), "mean_abs_error_pp": round(sum(ab) / max(1, len(ab)), 2), "max_abs_error_pp": round(max(ab or [0]), 2),
            "within_1pp": sum(1 for e in ab if e <= 1.0), "within_2pp": sum(1 for e in ab if e <= 2.0)}


def main() -> int:
    raw = RAW.read_text(encoding="utf-8", errors="replace")
    text = report_text(raw)
    k12, k13 = figure_png(12, raw), figure_png(13, raw)
    cap12 = "Keuhkosyöpäpotilaiden levinneisyysluokitus yhteistyöalueittain"
    cap13 = "Keuhkosyöpäpotilaiden levinneisyysluokitus hyvinvointialueittain"

    # ---- A: blind test against the table
    truth12 = {a: {s: 100 * n / K12_TOTAL[a] for s, n in c.items()} for a, c in K12_COUNT.items()}
    r12 = g.read_chart(blind(k12), figure="Kuva 12", caption=cap12, model=MODEL)
    a_rows = []
    for b in r12["bars"]:
        for s, t in (truth12.get(b["area"]) or {}).items():
            got = b["shares"].get(s)
            a_rows.append({"area": b["area"], "series": s, "table_pct": round(t, 1), "gemini_pct": got,
                           "error_pp": None if got is None else round(got - t, 1)})
    check_a = {**_stats([r["error_pp"] for r in a_rows if r["error_pp"] is not None]),
               "expected_values": sum(len(c) for c in K12_COUNT.values()), "values": a_rows}
    px12 = pixel_shares(k12)
    ruler = _stats([px12[i][s] - t for i, a in enumerate(K12_COUNT) for s, t in truth12[a].items()])
    print(f"[chart] A blind Kuva 12: {check_a}"[:230], file=sys.stderr, flush=True)
    print(f"[chart] ruler (pixel measure vs table, Kuva 12): {ruler}", file=sys.stderr, flush=True)

    # ---- the county figure, read twice
    r13 = g.read_chart(k13, figure="Kuva 13", caption=cap13, model=MODEL)
    r13b = g.read_chart(k13, figure="Kuva 13", caption=cap13, model=MODEL)
    px13 = pixel_shares(k13)
    same_bars = len(px13) == len(r13["bars"])
    second = {b["area"]: b["shares"] for b in r13b["bars"]}
    totals = county_totals(text)
    rows, b_errs, rep_errs = [], [], []
    for i, b in enumerate(r13["bars"]):
        for s, (ind, label_en) in SERIES.items():
            v = b["shares"].get(s, 0.0)
            px = px13[i].get(s) if same_bars else None
            v2 = (second.get(b["area"]) or {}).get(s, 0.0) if b["area"] in second else None
            if px is not None:
                b_errs.append(v - px)
            if v2 is not None:
                rep_errs.append(v - v2)
            agree = v2 is not None and abs(v - v2) <= 1.0
            rows.append({
                "area_id": b["area_id"], "area_name": b["area"], "indicator": ind, "label_en": label_en,
                "label_fi": f"Levinneisyysluokitus: {s}", "value": round(v, 1), "unit": "%", "period": PERIOD,
                "kind": "measured", "verified": False, "read_by": f"gemini:{r13['model']}", "read_from": "chart",
                "confidence": 0.6 if agree else 0.4, "figure": "Kuva 13",
                "quote": f"Kuva 13: {cap13} ({s})", "source_url": URL, "source_title": "Keuhkosyöpäpotilaiden hoidon laatu Suomessa (Suomen Syöpärekisteri)",
                "check": {"second_read": v2, "pixel_measure": None if px is None else round(px, 1),
                          "error_pp": None if px is None else round(v - px, 1)},
                "n_patients_table_11": totals.get(b["area_id"]), "read_at": _now(),
            })
    check_b = {**_stats(b_errs), "bars_gemini": len(r13["bars"]), "bars_in_image": len(px13),
               "areas_mapped": sum(1 for b in r13["bars"] if b["area_id"]), "ruler_vs_table_kuva_12": ruler,
               "two_gemini_reads": _stats(rep_errs)}
    print(f"[chart] B county values vs pixel measure: {check_b}", file=sys.stderr, flush=True)

    # ---- C: weighted to the national table
    c_rows, n_all = [], sum(totals.get(b["area_id"], 0) for b in r13["bars"])
    for s, t in T4_NATIONAL.items():
        got = sum(b["shares"].get(s, 0.0) * totals.get(b["area_id"], 0) for b in r13["bars"]) / max(1, n_all)
        c_rows.append({"series": s, "table_4_pct": t, "gemini_weighted_pct": round(got, 1), "error_pp": round(got - t, 1)})
    check_c = {**_stats([r["error_pp"] for r in c_rows]), "patients_covered": n_all, "patients_in_table_4": 14873, "values": c_rows}
    print(f"[chart] C weighted to Taulukko 4: {check_c}"[:400], file=sys.stderr, flush=True)

    ok = (check_a["n"] == check_a["expected_values"] and check_a["max_abs_error_pp"] <= ERR_LIMIT_PP and same_bars
          and check_b["max_abs_error_pp"] <= ERR_LIMIT_PP and check_b["areas_mapped"] == len(r13["bars"]))
    acc = {
        "figure": "Kuva 13", "caption": cap13, "source_url": URL, "model": r13["model"], "built_at": _now(),
        "what": "Stage classification by wellbeing services county, published only as a stacked bar chart without numbers.",
        "rows": len(rows), "shipped": ok, "error_limit_pp": ERR_LIMIT_PP,
        "check_a_blind_read_vs_table": {"how": "Kuva 12 (same chart design, collaborative areas) with its printed counts painted out; "
                                               "truth = printed count / area total in Taulukko 10", **check_a},
        "check_b_county_values_vs_pixel_measure": {"how": "each county value against the exact colour widths of the same bar in the image", **check_b},
        "check_c_weighted_vs_national_table": {"how": "county values weighted by county patient counts (Taulukko 11) against Taulukko 4", **check_c},
        "seconds": {"kuva_12": r12["seconds"], "kuva_13": r13["seconds"], "kuva_13_second_read": r13b["seconds"]},
        "limits": "Values are read off an axis, so they stay unverified with confidence 0.6 (0.4 where two reads differ by more than "
                  "1 point). Segments thinner than about 1 point can be missed. Only this chart design (100 % stacked bars) was tested.",
    }
    EXAMPLES.mkdir(exist_ok=True)
    (EXAMPLES / "chart_read_accuracy.json").write_text(json.dumps(acc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (EXAMPLES / "chart_read_kuva_13.json").write_text(json.dumps({**r13, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if ok:
        OUT_ROWS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"[chart] wrote {len(rows)} rows to {OUT_ROWS}", file=sys.stderr)
    else:
        print("[chart] NOT shipped: a check failed; see examples/chart_read_accuracy.json", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
