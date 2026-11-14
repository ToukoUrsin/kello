"""Read the four public sources with Gemini, ahead of time, into data/raw/gemini/*.json.

These are the reads behind data/processed/gemini_extracted.jsonl (build_extracted.py turns them into rows).
Nobody waits on them, so they use the strongest Gemini on the key (gemini_reader.OFFLINE_MODEL); the
"read a report" box in the app, where a person waits, keeps gemini_reader.DEFAULT_MODEL.

    cd app/server && python -m integrations.build_raw_reads                 # all 13 reads, 4 at a time
    python -m integrations.build_raw_reads --only b_pdf,d_ihe --out /tmp/x  # some reads, another folder
    PYTHONPATH=. python integrations/build_extracted.py                     # then rebuild the rows

Needs GEMINI_API_KEY. About 15 minutes. A read that fails keeps the file already in the folder.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import gemini_reader as g
from . import syoparekisteri_app as sa

RAW = g.ROOT / "data" / "raw" / "gemini"
A = "https://syoparekisteri.fi/assets/themes/ssy3/factsheets/keuhkosyoparaportti.html"
B = "https://syoparekisteri.fi/assets/files/2024/12/Keuhkosyopa_Suomessa.pdf"
D = "https://ihe.se/app/uploads/2026/04/IHE-Cancer-Dashboard-Finland_.pdf"

_C = ("The page has tabs 'yhteistyöalueittain' and 'hyvinvointialueittain'; all tabs are expanded. The per-county "
      "(hyvinvointialueittain) bar charts print patient counts on the bars: read them for EVERY county and category "
      "(value = count, unit n), and percentages where printed.")
_T = ("Use the tables given as text in PAGE TEXT ([TABLE on screenshot N: ...]) and cite that screenshot number as the "
      "page. Keep labels short. Skip everything else.")

# name -> (source, hint). The registry statistics app has its own entries below (one per view).
READS: dict[str, tuple[str, str]] = {
    "a_cases": (A, "ONLY: number of lung cancer patients/cases per wellbeing services county and per collaborative area "
                   "and whole country (lung_incidence_n); histological type per area (counts per cell type incl. unknown: "
                   "lung_histology_<type>_n, lung_histology_unknown_n, and shares if printed: lung_histology_unknown_pct, "
                   "lung_histology_defined_pct); basis of diagnosis (toteamistapa) per area. " + _C + " Skip everything else."),
    "a_stage": (A, "ONLY: stage at diagnosis (levinneisyysluokitus) per wellbeing services county and per collaborative "
                   "area and whole country: counts per stage class (lung_stage_<class>_n incl. unknown) and shares if "
                   "printed (lung_stage_1_2_pct, lung_stage_3_pct, lung_stage_4_pct, lung_stage_unknown_pct, "
                   "lung_stage_known_pct). " + _C + " Skip everything else."),
    "a_time": (A, "ONLY: time intervals in days (referral / first visit / diagnosis to treatment start), survival "
                  "(elossaolo-osuus) at 12 months per area and sex, and deaths within follow-up, per wellbeing services "
                  "county and per collaborative area and whole country. " + _C + " Skip everything else."),
    "a_histhva": (A, "ONLY Kuva 10 (Keuhkosyöpäpotilaiden histologinen tyyppi hyvinvointialueittain), the 100 % stacked "
                     "horizontal bar chart with one bar per wellbeing services county (21 counties + Helsingin kaupunki). "
                     "If patient counts are printed on the bars read them (lung_histology_small_cell_n, "
                     "lung_histology_non_small_cell_n, lung_histology_other_or_undefined_n). Otherwise read each bar "
                     "against the printed x axis 'Osuus potilaista (%)': for EVERY county give "
                     "lung_histology_other_or_undefined_pct = width of the last 'Muu tai määrittämätön' segment (100 minus "
                     "where it starts), to the nearest whole percent, read_from 'chart', confidence 0.6, label must say "
                     "'read off chart, approximate'. quote = 'Kuva 10: Keuhkosyöpäpotilaiden histologinen tyyppi "
                     "hyvinvointialueittain | Muu tai määrittämätön | Osuus potilaista (%)'. Reading a bar against its "
                     "axis is allowed here. Skip everything else."),
    "a_stagehva": (A, "ONLY Kuva 13 (Keuhkosyöpäpotilaiden levinneisyysluokitus hyvinvointialueittain), the 100 % stacked "
                      "horizontal bar chart with one bar per wellbeing services county (21 counties + Helsingin kaupunki). "
                      "No numbers are printed on the bars, so read each bar against the printed x axis 'Osuus potilaista "
                      "(%)' (0, 25, 50, 75, 100): for EVERY county give (1) lung_stage_unknown_pct = where the first, blue "
                      "'Ei tietoa' segment ends, to the nearest whole percent, and (2) lung_stage_tnm_pct = width of the "
                      "last, orange 'TNM' segment (100 minus where it starts). read_from 'chart', confidence 0.6, label "
                      "must say 'read off chart, approximate'. quote = 'Kuva 13: Keuhkosyöpäpotilaiden levinneisyysluokitus "
                      "hyvinvointialueittain | Ei tietoa | Osuus potilaista (%)' (or TNM). Reading a bar against its axis "
                      "is allowed here. 44 values expected. Skip everything else."),
    "a_treatA": (A, "ONLY the 'Parantava' (curative-intent treatment) block of Taulukko 10 (per collaborative area) and "
                    "Taulukko 11 (per wellbeing services county, 'hyvinvointialueittain'): for EVERY county, every "
                    "collaborative area total ('Yhteistyöalue yhteensä') and the whole country give "
                    "lung_curative_intent_pct (Osuus %), lung_curative_intent_n (Lukumäärä) and lung_patients_n (Yhteensä, "
                    "patients in 12-month follow-up). Also the national rows of Taulukko 7 (curative procedures: surgery "
                    "-> lung_surgery_n / lung_surgery_pct, curative radiotherapy etc.). " + _T),
    "a_treatB": (A, "ONLY Taulukko 10 (per collaborative area) and Taulukko 11 (per wellbeing services county): the blocks "
                    "OTHER than 'Parantava': for EVERY county, collaborative area total and whole country give only the "
                    "share (Osuus %) of: Jarruttava -> lung_noncurative_treatment_pct, Oireenmukainen -> "
                    "lung_palliative_treatment_pct, no treatment record (Ei hoitotietoa or similar) -> "
                    "lung_no_treatment_record_pct, MDT recorded -> lung_mdt_recorded_pct. Shares only, no counts. " + _T),
    "b_pdf": (B, "Finnish Cancer Registry report on lung cancer in Finland. Extract, with priority: every per-area number "
                 "(per wellbeing services county / hyvinvointialue, per collaborative area / yhteistyöalue, whole country) "
                 "for lung cancer cases, stage, stage-known share, histology, treatment (curative-intent, surgery, "
                 "radiotherapy, drug therapy, palliative, no treatment), MDT, survival; and any time-to-treatment figures "
                 "in days. Then the main national figures. At most 250 values."),
    "d_ihe": (D, "Finland's waiting-time and care pathway indicators (time to diagnosis, time to treatment, screening "
                 "participation, survival, stage at diagnosis, access to medicines/radiotherapy), with any lung cancer "
                 "values; whole-country values, area_id FI"),
}
APP_VIEWS = {"c2_shiny_0": 0, "c2_shiny_1": 1, "c2_shiny_2": 2, "c_shiny_3": 3}  # views of syoparekisteri_app.VIEWS
ALL = list(READS) + list(APP_VIEWS)


def run_one(name: str, out_dir: Path, model: str, tries: int = 2) -> dict:
    """A read, tried again once when it comes back empty (a model sometimes answers with no values)."""
    row: dict = {}
    for attempt in range(tries):
        row = _run_once(name, out_dir, model)
        if row["ok"]:
            break
    print(json.dumps({**row, "tries": attempt + 1}, ensure_ascii=False), flush=True)
    return row


def _run_once(name: str, out_dir: Path, model: str) -> dict:
    """One read in its own process (each drives its own browser). Writes <name>.json only when the read worked."""
    log = out_dir / f"{name}.log"
    tmp = out_dir / f"{name}.json.tmp"
    env = {**os.environ, "GEMINI_READER_MODEL": model}
    if name in READS:
        src, hint = READS[name]
        cmd = [sys.executable, "-W", "ignore", "-m", "integrations.gemini_reader", src, "--hint", hint, "--out", str(tmp)]
        with open(log, "w") as lf:
            rc = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=lf).returncode
    else:
        cmd = [sys.executable, "-W", "ignore", "-m", "integrations.syoparekisteri_app", "--view", str(APP_VIEWS[name])]
        with open(log, "w") as lf, open(tmp, "w") as of:
            rc = subprocess.run(cmd, env=env, stdout=of, stderr=lf).returncode
    row = {"read": name, "ok": False, "model": model}
    try:
        res = json.loads(tmp.read_text(encoding="utf-8"))
        items = [it for r in (res if isinstance(res, list) else [res]) for it in r["extracted"]]
        row.update(values=len(items), confirmed=sum(1 for it in items if it.get("verified")),
                   seconds=sum(float(r.get("seconds") or 0) for r in (res if isinstance(res, list) else [res])))
        row["ok"] = rc == 0 and row["confirmed"] > 0  # none confirmed: the page did not show its numbers (try again)
    except Exception as exc:  # noqa: BLE001 - no usable answer
        row["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    if row["ok"]:
        tmp.replace(out_dir / f"{name}.json")
    elif tmp.exists():
        tmp.unlink()
    return row


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m integrations.build_raw_reads")
    ap.add_argument("--only", help="comma-separated read names; default all: " + ",".join(ALL))
    ap.add_argument("--out", default=str(RAW), help="folder for <name>.json and <name>.log")
    ap.add_argument("--model", default=g.OFFLINE_MODEL)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.only.split(",")] if a.only else ALL
    bad = [n for n in names if n not in ALL]
    if bad:
        ap.error("unknown read: " + ", ".join(bad))
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(lambda n: run_one(n, out_dir, a.model), names))
    failed = [r["read"] for r in rows if not r["ok"]]
    print(f"{len(rows) - len(failed)} of {len(rows)} reads stored in {out_dir}" + (f"; failed: {', '.join(failed)}" if failed else ""),
          file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
