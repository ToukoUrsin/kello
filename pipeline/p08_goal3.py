"""Goal 3 scoreboard (National Cancer Strategy 2026-2035, "equal and effective cancer care"):
survival of poor-prognosis cancers vs the Sweden/Norway average, cancer mortality -10 %, and
patients treated within target times - nationally and for the 23 areas.

    .venv/bin/python pipeline/p08_goal3.py          # fresh downloads
    KELLO_CACHE=1 .venv/bin/python pipeline/p08_goal3.py                         # reuse data/raw/goal3

Sources (all public aggregates, cached under data/raw/goal3/):
- Finnish Cancer Registry statistics application (R Shiny, no API). The app state is set through its
  own bookmark URL and the app's "csv" button is clicked in a headless browser, so the numbers are the
  registry's own table export (no screen reading): incidence and mortality 2020-2024 by wellbeing
  services county, relative survival 2022-2024 by collaborative area, national series by year.
- NORDCAN API: 5-year relative survival FI/SE/NO (re-fetched to confirm the figures in
  science/out/nordic_gap/artifacts) and Finnish national counts as a second source.
- Statistics Finland 13u5: deaths by county and cause, second source for the registry's death counts.
- THL Ohjaus 21/2016 and the THL specialist-care queue report list, for the "treated within target
  times" indicator (no cancer-specific share is published; recorded as a data gap).

Writes data/processed/goal3.json and adds its sources to data/processed/sources.json (adds or
refreshes its own keys only). run_all.py rewrites sources.json, so run this script after it.
Downloaded content is only ever parsed as data (csv / json / text), never executed.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (AREA_IDS, BROWSER_UA, PROC, RAW, ROOT, USE_CACHE, FetchError, Out, fetch,  # noqa: E402
                    jsonstat2_records, load_areas, now_iso, num)

G3 = "goal3"
RAWDIR = RAW / G3
SCI = ROOT / "science" / "out" / "nordic_gap" / "artifacts"

# ---- Finnish Cancer Registry statistics app -------------------------------------------------
FCR_APP = "https://tilastot.syoparekisteri.fi/syovat/"
FCR_PAGE = "https://cancerregistry.fi/statistics/cancer-statistics/"
FCR_LIC = "Finnish Cancer Registry, open statistics (cite source)"
SITES = {"0L": "all", "14L": "liver", "16L": "pancreas", "21L": "lung"}
SITE_FI = {"Kaikki syövät yhdessä": "all", "Maksa": "liver", "Haima": "pancreas", "Keuhkot, henkitorvi": "lung"}
SITE_ICD = {"all": "C00-96, D09.0-1, D32-33, D41-43, D45-47, D76", "liver": "C22", "pancreas": "C25", "lung": "C33-34"}
SEXES = {"-1L": "all", "0L": "male", "1L": "female"}
SEX_FI = {"Molemmat yhdessä": "all", "Miehet": "male", "Naiset": "female"}
YTA_APP = {"10100L": "HUS", "10200L": "KYS", "10300L": "TAYS", "10400L": "TYKS", "10500L": "OYS"}
COUNTY_APP = [f"101{i:02d}L" for i in (1, 2, 3, 4, 9, 10, 11, 90)] + [f"102{i}L" for i in (12, 13, 14, 15)] + \
             [f"103{i:02d}L" for i in (7, 8, 16)] + [f"104{i:02d}L" for i in (5, 6, 17)] + [f"105{i}L" for i in (18, 19, 20, 21)]
ALL_AREAS = ["-1L"] + sorted(list(YTA_APP) + COUNTY_APP) + ["10600L"]       # 1 + 5 + 22 + Åland = 29
SURV_AREAS = ["-1L"] + sorted(YTA_APP) + ["10600L"]                          # survival: collaborative areas only

VIEWS = {  # key -> (theme, classification, value type, areas)
    "incidence_latest5": ("theme_inc", "inc_latest5", "inc.rate_finland_2014", ALL_AREAS),
    "mortality_latest5": ("theme_mort", "mort_latest5", "mort.rate_finland_2014", ALL_AREAS),
    "survival": ("theme_surv", "surv", "r.e2.as", SURV_AREAS),
    "mortality_by_year": ("theme_mort", "mort_ts1", "mort.rate_finland_2014", ["-1L"]),
    "incidence_by_year": ("theme_inc", "inc_ts1", "inc.rate_finland_2014", ["-1L"]),
}

# ---- NORDCAN / Statistics Finland -----------------------------------------------------------
NORDCAN = "https://canapi.iarc.who.int/api/nordcan/v2/961"
NC_CANCER = {"lung": 160, "pancreas": 130, "liver": 110, "all": 980}
NC_COUNTRY = {246: "finland", 752: "sweden", 578: "norway", 208: "denmark"}
NC_SEX = {"all": 0, "male": 1, "female": 2}
PX = "https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/ksyyt/13u5.px"
SF_CAUSE = {"04-21": "all", "09": "liver", "10": "pancreas", "11": "lung"}

THL_GUIDE = "https://www.julkari.fi/server/api/core/bitstreams/de33d584-bdce-40a1-b100-df48c4906a49/content"
THL_QUEUE_REPORTS = "https://sampo.thl.fi/pivot/prod/fi/eshjono/"
STRATEGY_TARGET_PP = {"lung": 14, "pancreas": 6, "liver": 14}
SMALL_N = 20


# =============================================================================================
# Finnish Cancer Registry app
# =============================================================================================
def fcr_url(theme: str, tabu: str, value_type: str, areas: list[str], panel: str = "2") -> str:
    """The app's own bookmark format (button "Kopioi linkki"), pointed at the app host."""
    q = [("in.subset.sites", list(SITES)), ("value_type", value_type), ("submit", 1), ("tabset_panel", panel),
         ("value_theme", theme), ("in.subset.sex", list(SEXES)), ("tabu", tabu), ("in.subset.area", areas),
         ("language", "fi"), ("table_view", "v2")]
    enc = lambda v: urllib.parse.quote(json.dumps(v, separators=(",", ":")), safe=",")  # noqa: E731
    return FCR_APP + "?_inputs_&" + "&".join(f"{k}={enc(v)}" for k, v in q)


def _fcr_download(page, url: str, want: dict, dest: Path) -> dict:
    """Open one bookmarked view, check the app really is in the requested state, save its csv export."""
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_function("() => { const e = document.getElementById('value_theme'); return !!(e && e.selectize); }",
                           timeout=120000)
    state_js = """() => { const g = id => { const e = document.getElementById(id); return e && e.selectize ? e.selectize : null; };
        const th = g('value_theme'), tb = g('tabu'), vt = g('value_type'), sx = g('in.subset.sex'), ar = g('in.subset.area'), si = g('in.subset.sites');
        if (!th || !tb || !vt || !sx || !ar || !si) return null;
        const lab = (s, k) => (s.options[k] || {}).label || null;
        const a = document.getElementById('download_csv');
        return { theme: th.getValue(), tabu: tb.getValue(), tabu_label: lab(tb, tb.getValue()), value_type: vt.getValue(),
                 value_type_label: lab(vt, vt.getValue()), sex: sx.getValue(), areas: ar.getValue(), sites: si.getValue(),
                 csv_ready: !!(a && a.href && a.href.includes('/session/')),
                 table_rows: document.querySelectorAll('table.dataTable tbody tr').length }; }"""
    state = None
    for _ in range(40):  # the inputs are re-rendered after the theme is restored: poll until they settle
        page.wait_for_timeout(1500)
        state = page.evaluate(state_js)
        if (state and state["theme"] == want["theme"] and state["tabu"] == want["tabu"]
                and sorted(state["areas"]) == sorted(want["areas"]) and sorted(state["sites"]) == sorted(SITES)
                and sorted(state["sex"]) == sorted(SEXES) and state["csv_ready"] and state["table_rows"] > 0):
            break
    else:
        raise FetchError(f"registry app did not reach the requested state: {state}")
    page.wait_for_timeout(3000)
    with page.expect_download(timeout=120000) as dl:
        page.locator("#download_csv").click(timeout=30000)
    dl.value.save_as(str(dest))
    return state


def fcr_fetch_all(out: Out) -> dict[str, dict]:
    """Returns {view key: {"rows": [dict], "meta": {...}}}; csv + meta cached under data/raw/goal3/."""
    RAWDIR.mkdir(parents=True, exist_ok=True)
    res, todo = {}, []
    for key, (theme, tabu, vt, areas) in VIEWS.items():
        path, meta = RAWDIR / f"fcr_{key}.csv", RAWDIR / f"fcr_{key}.csv.meta.json"
        if USE_CACHE and path.exists() and meta.exists():
            res[key] = {"meta": json.loads(meta.read_text())}
        else:
            todo.append(key)
    if todo:
        from playwright.sync_api import sync_playwright  # only needed for fresh downloads
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for key in todo:
                    theme, tabu, vt, areas = VIEWS[key]
                    url = fcr_url(theme, tabu, vt, areas)
                    path = RAWDIR / f"fcr_{key}.csv"
                    last = None
                    for attempt in range(3):
                        page = browser.new_page(viewport={"width": 1400, "height": 1800}, accept_downloads=True)
                        try:
                            state = _fcr_download(page, url, {"theme": theme, "tabu": tabu, "areas": areas}, path)
                            m = {"url": url, "retrieved_at": now_iso(), "status": 200, "bytes": path.stat().st_size,
                                 "how": "headless Chromium: opened the bookmark URL, clicked the app's .csv download button",
                                 "app_state": {k: state[k] for k in ("theme", "tabu", "tabu_label", "value_type", "value_type_label")}}
                            (RAWDIR / f"fcr_{key}.csv.meta.json").write_text(json.dumps(m, ensure_ascii=False))
                            res[key] = {"meta": m}
                            last = None
                            break
                        except Exception as e:  # browser / network trouble: retry with a new page
                            last = e
                        finally:
                            page.close()
                    if last is not None:
                        out.problems.append(f"goal3 fcr {key}: download failed: {last!r}"[:300])
            finally:
                browser.close()
    for key in list(res):
        text = (RAWDIR / f"fcr_{key}.csv").read_text(encoding="utf-8-sig")
        res[key]["rows"] = list(csv.DictReader(io.StringIO(text), delimiter=";"))
        m = re.search(r"\((\d{4}(?:-\d{4})?)\)", res[key]["meta"]["app_state"]["tabu_label"] or "")
        res[key]["period"] = m.group(1) if m else None
    return res


def col(row: dict, *starts: str) -> str | None:
    """Value of the first column whose header starts with one of `starts` (headers differ per theme)."""
    for s in starts:
        for k, v in row.items():
            if k.startswith(s):
                return v
    return None


def fnum(x):
    v = num(x)
    return None if v is None or (isinstance(v, float) and v != v) else v  # NaN -> None


# =============================================================================================
def run() -> Out:
    out = Out("p08_goal3")
    notes: list[str] = []
    checks: list[dict] = []
    areas = load_areas()
    name2id = {a["name_fi"]: a["id"] for a in areas}
    yta_of = {a["id"]: a["yta"] for a in areas}
    name2yta = {a["yta_name_fi"]: "yta:" + a["yta"] for a in areas if a.get("yta_name_fi") and a["yta"] != "ALAND"}

    def check(name: str, passed: bool, result: str):
        checks.append({"check": name, "passed": bool(passed), "result": result})
        if not passed:
            out.problems.append(f"goal3 check failed: {name}: {result}")

    # ------------------------------------------------------------------ registry app tables
    fcr = fcr_fetch_all(out)
    src_of = {}
    titles = {"incidence_latest5": "new cancer cases and incidence rates by area, latest 5-year period",
              "mortality_latest5": "cancer deaths and mortality rates by area, latest 5-year period",
              "survival": "age-standardised relative survival 1-5 years from diagnosis, by collaborative area",
              "mortality_by_year": "cancer deaths and mortality rates by year, whole country",
              "incidence_by_year": "new cancer cases and incidence rates by year, whole country"}
    for key, v in fcr.items():
        sid = f"fcr_stats_app_{key}"
        src_of[key] = sid
        st = v["meta"]["app_state"]
        out.source(sid, title=f"Cancer statistics application: {titles[key]} ({st['tabu_label']})",
                   publisher="Finnish Cancer Registry (Syöpärekisteri)", url=v["meta"]["url"],
                   api_call=f"GET {v['meta']['url']} in a headless browser, then the app's '.csv' download button "
                            f"(session download link); saved as data/raw/goal3/fcr_{key}.csv",
                   retrieved_at=v["meta"]["retrieved_at"], licence=FCR_LIC,
                   notes=(f"Interactive R Shiny application embedded at {FCR_PAGE} (no API). Sites: all cancers, liver C22, pancreas C25, "
                          f"lung and trachea C33-34; both sexes, men, women. {len(v['rows'])} table rows. Value types in the export: counts, "
                          "crude rate, age-standardised rate (Finland 2014 and World standard populations)." if key != "survival" else
                          f"Interactive R Shiny application embedded at {FCR_PAGE} (no API). Survival is published for the whole country, the five "
                          f"collaborative areas and Åland only, not by wellbeing services county. {len(v['rows'])} table rows with 95 % CI."))

    def area_id(name: str | None) -> str | None:
        if name is None or name == "Koko maa":
            return "FI"
        if name in name2yta:
            return name2yta[name]
        return name2id.get(name)

    county, yta_rows, national = [], [], []
    period5 = None

    def emit(aid: str, row: dict):
        (national if aid == "FI" else yta_rows if aid.startswith("yta:") else county).append({"area_id": aid, **row})

    # incidence and mortality, latest 5-year period
    tables = {}  # (kind, area, cancer, sex) -> {"n":, "crude":, "asr":, "asr_world":}
    for key, kind, ncol, n_metric, r_metric, what in (
            ("incidence_latest5", "incidence", "Todettuja", "cases_n", "incidence_asr", "new cases"),
            ("mortality_latest5", "mortality", "Syöpäkuolemia", "deaths_n", "mortality_asr", "deaths")):
        if key not in fcr:
            continue
        v = fcr[key]
        period5 = period5 or v["period"]
        n_years = (lambda p: int(p[5:]) - int(p[:4]) + 1 if p and "-" in p else 1)(v["period"])
        for r in v["rows"]:
            aid, cancer, sex = area_id(r.get("Alue")), SITE_FI.get(r["Syöpätauti"]), SEX_FI.get(r["Sukupuoli"])
            if aid is None or cancer is None or sex is None:
                out.problems.append(f"goal3 fcr {key}: unmapped row {r.get('Alue')} / {r['Syöpätauti']} / {r['Sukupuoli']}")
                continue
            tables[(kind, aid, cancer, sex)] = {
                "n": fnum(r[next(k for k in r if k.startswith(ncol))]),
                "crude": fnum(col(r, "Suhde per 100 000", "Kuolleisuus per 100 000")),
                "asr": fnum(next(val for k, val in r.items() if "Suomi 2014" in k)),
                "asr_world": fnum(next(val for k, val in r.items() if "maailman" in k))}
        for (k2, aid, cancer, sex), t in sorted(tables.items()):
            if k2 != kind:
                continue
            nat = tables.get((kind, "FI", cancer, sex), {})
            base = {"cancer": cancer, "sex": sex, "period": v["period"], "source_url": v["meta"]["url"],
                    "source_id": src_of[key], "kind": "measured"}
            suppressed = t["n"] is None
            small = suppressed or t["n"] < SMALL_N
            row_n = {**base, "metric": n_metric, "value": t["n"], "unit": f"{what} in {v['period']}", "national": nat.get("n")}
            if t["n"] is not None:
                row_n["per_year"] = round(t["n"] / n_years, 1)
            row_r = {**base, "metric": r_metric, "value": t["asr"],
                     "unit": "per 100,000 person-years, age-standardised (Finland 2014)", "national": nat.get("asr"),
                     "n": t["n"], "crude_rate": t["crude"], "asr_world": t["asr_world"]}
            for rr in (row_n, row_r):
                if small:
                    rr["small_n"] = True
                if suppressed:
                    rr["suppressed_n"] = True
                    rr["note"] = ("Count not shown by the registry (blank cell in its table; small number). "
                                  "The rate is published and based on that small count.")
                elif small:
                    rr["note"] = f"Only {t['n']} {what} in {v['period']}: the rate is unstable, do not rank on it."
            # keep order: metric first for readability
            for rr in (row_n, row_r):
                emit(aid, {k: rr[k] for k in ("cancer", "sex", "metric", "value", "unit", "period", "national") if k in rr}
                     | {k: val for k, val in rr.items() if k not in ("cancer", "sex", "metric", "value", "unit", "period", "national")})

    # survival (collaborative areas; counties inherit their collaborative area's value, flagged)
    surv = {}  # (area, cancer, sex, years) -> (value, lo, hi)
    if "survival" in fcr:
        v = fcr["survival"]
        for r in v["rows"]:
            aid = "yta:ALAND" if r.get("Alue") == "Ahvenanmaa" else area_id(r.get("Alue"))
            cancer, sex = SITE_FI.get(r["Syöpätauti"]), SEX_FI.get(r["Sukupuoli"])
            val = fnum(col(r, "Suhteellinen elossaololuku"))
            if aid is None or cancer is None or sex is None or val is None:
                continue
            ci = [fnum(x) for x in re.split(r"(?<=\d)-(?=\d)", col(r, "Luottamusväli") or "")]
            lo, hi = (ci + [None, None])[:2]
            surv[(aid, cancer, sex, int(r["Vuosia toteamisesta"]))] = (val, lo, hi)
        base = {"period": v["period"], "source_url": v["meta"]["url"], "source_id": src_of["survival"], "kind": "measured"}
        unit = "% (age-standardised relative survival)"

        def srow(aid_src, cancer, sex, yrs):
            got = surv.get((aid_src, cancer, sex, yrs))
            if not got:
                return None
            nat = surv.get(("FI", cancer, sex, yrs))
            return {"cancer": cancer, "sex": sex, "metric": f"survival_{yrs}y_pct", "value": got[0], "lo": got[1], "hi": got[2],
                    "unit": unit, "period": v["period"], "national": nat[0] if nat else None, **{k: base[k] for k in ("source_url", "source_id", "kind")}}

        for cancer in ("lung", "pancreas", "liver", "all"):
            for sex in ("all", "male", "female"):
                for yrs in (1, 5):
                    r0 = srow("FI", cancer, sex, yrs)
                    if r0:
                        emit("FI", r0)
                    for y in list(YTA_APP.values()) + ["ALAND"]:
                        ry = srow("yta:" + y, cancer, sex, yrs)
                        if ry:
                            emit("yta:" + y, ry)
                    for a in AREA_IDS:
                        src = "yta:" + yta_of[a]
                        rc = srow(src, cancer, sex, yrs)
                        if rc:
                            rc["level"] = "collaborative_area"
                            rc["level_area_id"] = src
                            rc["note"] = ("Not a county value: the registry publishes survival only by collaborative area; this is the value of "
                                          f"{src[4:]} (the area this county belongs to)." if a != "91" else
                                          "Åland's own value as published by the registry (very small numbers, wide interval).")
                            emit(a, rc)

    # ------------------------------------------------------------------ checks on the registry tables
    if tables:
        # the registry's national total can exceed the sum of its areas by a few cases (not assigned to an area)
        comb = []
        for kind in ("incidence", "mortality"):
            for cancer in SITES.values():
                for sex in SEXES.values():
                    parts = [tables.get((kind, a, cancer, sex), {}).get("n") for a in AREA_IDS]
                    tot = tables.get((kind, "FI", cancer, sex), {}).get("n")
                    if tot is not None:
                        comb.append({"kind": kind, "cancer": cancer, "sex": sex, "national": tot, "sum_areas": sum(p for p in parts if p is not None),
                                     "blank_cells": parts.count(None)})
        for c in comb:
            c["residual"] = c["national"] - c["sum_areas"]
            c["residual_pct"] = round(100 * c["residual"] / c["national"], 3)
        full = [c for c in comb if not c["blank_cells"]]
        blank = [c for c in comb if c["blank_cells"]]
        wr = max(full, key=lambda c: c["residual_pct"])
        check("23 area counts add up to the registry's own national total within 0.1 % (incidence and mortality, 4 sites x 3 sexes)",
              all(0 <= c["residual_pct"] <= 0.1 for c in full) and all(c["residual"] >= 1 for c in blank),
              f"{sum(1 for c in full if c['residual'] == 0)} of {len(comb)} combinations add up exactly; in {sum(1 for c in full if c['residual'] > 0)} the national "
              f"total is slightly larger than the sum of the 23 areas (largest {wr['residual_pct']} %: {wr['kind']} {wr['cancer']} {wr['sex']}, "
              f"{wr['sum_areas']} vs {wr['national']}; never smaller); {len(blank)} contain a count the registry left blank (Åland liver deaths), "
              "remainder there: " + ", ".join(f"{c['sex']} {c['residual']}" for c in blank))
        if any(c["residual"] > 0 for c in full):
            notes.append(f"The registry's national totals are slightly larger than the sum of the 23 areas (at most {wr['residual_pct']} %, e.g. {wr['kind']} "
                         f"{wr['cancer']} {wr['sex']}: {wr['national']} nationally vs {wr['sum_areas']} summed). The registry's table does not say why "
                         "(cases without an area is our unverified reading). Shares of the national total computed from county counts will not sum to exactly 100 %.")
        ybad = []
        for (kind, aid, cancer, sex), t in tables.items():
            if aid.startswith("yta:") and t["n"] is not None:
                parts = [tables[(kind, a, cancer, sex)]["n"] for a in AREA_IDS if "yta:" + yta_of[a] == aid]
                if None not in parts and sum(parts) != t["n"]:
                    ybad.append((kind, aid, cancer, sex, sum(parts), t["n"]))
        check("county counts add up to their collaborative area's count (areas.json yta mapping vs the registry's grouping)",
              not ybad, f"{sum(1 for k in tables if k[1].startswith('yta:'))} collaborative-area cells checked; mismatches: {ybad or 'none'}")
        cov = {}
        for r in county:
            cov.setdefault((r["cancer"], r["metric"], r["sex"]), set()).add(r["area_id"])
        short = {f"{c}/{m}/{s}": len(a) for (c, m, s), a in cov.items() if len(a) != len(AREA_IDS)}
        check("23 areas present for every cancer, metric and sex", not {k: n for k, n in short.items() if "survival" not in k},
              f"{len(cov) - len(short)} of {len(cov)} cancer/metric/sex combinations have all 23 areas; incomplete: {short or 'none'} "
              "(survival gaps are Åland cells the registry does not publish, and all-cancer survival is national only)")

    # ------------------------------------------------------------------ NORDCAN: second source for national counts
    nc_calls, nc_ts, nc_cmp = [], None, []
    for kind, typ in (("incidence", 0), ("mortality", 1)):
        for cancer, cid in NC_CANCER.items():
            for sex, sx in NC_SEX.items():
                url = f"{NORDCAN}/data/population/{typ}/{sx}/246/{cid}/?year_start=2020&year_end=2024"
                try:
                    raw, nc_ts = fetch(url, G3, f"nordcan_{kind}_{cid}_{sx}.json")
                    nc_calls.append(url)
                    ds = [r for r in json.loads(raw)["dataset"] if r.get("country") == 246 and 2020 <= r["year"] <= 2024]
                    tot = tables.get((kind, "FI", cancer, sex), {}).get("n")
                    if len(ds) == 5 and tot:
                        s = sum(r["total"] for r in ds)
                        nc_cmp.append({"kind": kind, "cancer": cancer, "sex": sex, "registry_app": tot, "nordcan": round(s, 1),
                                       "diff_pct": round(100 * (tot - s) / s, 2)})
                except (FetchError, ValueError, KeyError) as e:
                    out.problems.append(f"goal3 nordcan {kind} {cancer} {sex}: {e}")
    if nc_calls:
        out.source("nordcan_goal3_fi_counts", title="NORDCAN: Finland, new cases and deaths 2020-2024, lung / pancreas / liver / all sites, by sex",
                   publisher="NORDCAN (IARC, Association of the Nordic Cancer Registries)", url="https://nordcan.iarc.fr/",
                   api_call="GET " + " ; ".join(nc_calls), retrieved_at=nc_ts, licence="NORDCAN terms of use (free with citation)",
                   notes="Used only as a second source for the national counts taken from the Finnish Cancer Registry application "
                         "(NORDCAN 'All sites' = id 980). API field total summed over 2020-2024.")
    if nc_cmp:
        site = [c for c in nc_cmp if c["cancer"] != "all"]
        ws = max(site, key=lambda c: abs(c["diff_pct"]))
        allc = {(c["kind"], c["sex"]): c for c in nc_cmp if c["cancer"] == "all"}
        both = [c for c in nc_cmp if c["sex"] == "all"]
        check("national counts 2020-2024 match NORDCAN (second source): lung, pancreas, liver within 0.5 %; all sites within 2 % (definitions of 'all cancers' differ)",
              all(abs(c["diff_pct"]) <= 0.5 for c in site) and all(abs(c["diff_pct"]) <= 2 for c in allc.values()),
              f"{len(site)} site-specific comparisons (2 measures x 3 sites x 3 sexes), largest difference {ws['diff_pct']} % "
              f"({ws['kind']} {ws['cancer']} {ws['sex']}: {ws['registry_app']} vs {ws['nordcan']}); all sites, both sexes: incidence "
              f"{allc[('incidence', 'all')]['diff_pct']} %, mortality {allc[('mortality', 'all')]['diff_pct']} %; both sexes: "
              + "; ".join(f"{c['kind']} {c['cancer']} {c['registry_app']} vs {c['nordcan']}" for c in both))

    # ------------------------------------------------------------------ Statistics Finland: second source for deaths by county
    sf_cmp = []
    try:
        body = {"query": [{"code": "alue_23_20260101", "selection": {"filter": "item", "values": ["SSS"] + [f"HVA{a}" for a in AREA_IDS]}},
                          {"code": "kuolinsyyt_1_20210101", "selection": {"filter": "item", "values": list(SF_CAUSE)}},
                          {"code": "timeperiod_y", "selection": {"filter": "item", "values": [str(y) for y in range(2020, 2025)]}},
                          {"code": "contentscode", "selection": {"filter": "item", "values": ["ksyylkm"]}}],
                "response": {"format": "json-stat2"}}
        raw, ts = fetch(PX, G3, "statfin_13u5_deaths_2020_2024.json", post_json=body)
        js = json.loads(raw)
        acode = next(d for d in js["id"] if d.startswith("alue"))
        ccode = next(d for d in js["id"] if d.startswith("kuolinsyyt"))
        sf = {}
        for r in jsonstat2_records(js):
            if r["value"] is not None:
                a = "FI" if r[acode] == "SSS" else r[acode][3:]
                sf[(a, SF_CAUSE[r[ccode]])] = sf.get((a, SF_CAUSE[r[ccode]]), 0) + r["value"]
        out.source("statfin_13u5_goal3_check", title="13u5 -- Deaths by underlying cause of death (time series classification) and wellbeing services county, 2020-2024",
                   publisher="Statistics Finland", url="https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/StatFin__ksyyt/statfin_ksyyt_pxt_13u5.px/",
                   api_call=f"POST {PX} body={json.dumps(body, ensure_ascii=False)}", retrieved_at=ts, licence="CC BY 4.0",
                   notes="Second source for the registry's death counts by county. Causes: 04-21 all cancers (C00-C97), 09 primary liver cancer (C22), "
                         "10 pancreatic cancer (C25), 11 larynx, trachea and lung (C32-C34; includes larynx, unlike the registry's C33-34).")
        for (a, cancer), s in sorted(sf.items()):
            t = tables.get(("mortality", a, cancer, "all"), {}).get("n")
            if t is not None and s:
                sf_cmp.append({"area_id": a, "cancer": cancer, "registry_app": t, "statfin": s, "diff_pct": round(100 * (t - s) / s, 1)})
    except (FetchError, ValueError, KeyError, StopIteration) as e:
        out.problems.append(f"goal3 statfin 13u5: {e}")
    if sf_cmp:
        nat = {c["cancer"]: c for c in sf_cmp if c["area_id"] == "FI"}
        panc = [c for c in sf_cmp if c["cancer"] == "pancreas" and c["area_id"] != "FI"]
        wp = max(panc, key=lambda c: abs(c["diff_pct"]))
        check("pancreas deaths 2020-2024 by county match Statistics Finland cause-of-death table 13u5 (same ICD-10 code C25) within 5 %",
              all(abs(c["diff_pct"]) <= 5 for c in panc) and abs(nat["pancreas"]["diff_pct"]) <= 1,
              f"national {nat['pancreas']['registry_app']} vs {nat['pancreas']['statfin']} ({nat['pancreas']['diff_pct']} %); "
              f"{len(panc)} counties, largest difference {wp['diff_pct']} % (area {wp['area_id']}: {wp['registry_app']} vs {wp['statfin']})")
        liv = [c for c in sf_cmp if c["cancer"] == "liver" and c["area_id"] != "FI"]
        check("liver deaths: registry vs Statistics Finland (expected to differ; reported, not a pass/fail on equality)",
              "liver" in nat,
              f"national {nat['liver']['registry_app']} (registry) vs {nat['liver']['statfin']} (Statistics Finland 'primary liver cancer C22'), "
              f"{nat['liver']['diff_pct']} %; by county {min(c['diff_pct'] for c in liv)} % to {max(c['diff_pct'] for c in liv)} %. "
              f"All cancers {nat['all']['registry_app']} vs {nat['all']['statfin']} ({nat['all']['diff_pct']} %, different code lists); "
              f"lung {nat['lung']['registry_app']} (C33-34) vs {nat['lung']['statfin']} (C32-34) ({nat['lung']['diff_pct']} %)")
        notes.append(f"Liver cancer deaths differ by source: the Cancer Registry counts {nat['liver']['registry_app']} deaths from liver cancer (C22) in 2020-2024, "
                     f"Statistics Finland's cause-of-death table 13u5 counts {nat['liver']['statfin']} ('primary liver cancer, C22'), {abs(nat['liver']['diff_pct'])} % more. "
                     "This file uses the registry's figures throughout (same source as incidence and survival). The reason for the difference was not verified "
                     "from a source; do not mix the two sources in one comparison.")

    # ------------------------------------------------------------------ survival targets (NORDCAN, reuse of science/out/nordic_gap)
    survival_targets = []
    strat = (ROOT / "res" / "strategy" / "s.txt").read_text(encoding="utf-8", errors="replace")
    flat = re.sub(r"\s+", " ", strat.replace("­", ""))
    m_t = re.search(r"yli (\d+) prosenttiyksikköä keuhko ?syövässä, (\d+) prosenttiyksikköä haimasyövässä ja (\d+) prosenttiyksikköä maksasyövässä", flat)
    strat_pp = dict(zip(("lung", "pancreas", "liver"), map(int, m_t.groups()))) if m_t else {}
    check("strategy survival targets (+14 / +6 / +14 percentage points) read from res/strategy/s.txt",
          strat_pp == STRATEGY_TARGET_PP, f"found {strat_pp or 'nothing'}; quote: '{m_t.group(0) if m_t else None}'")
    try:
        summ = {(r["cancer"].lower(), r["sex"].lower()): r for r in csv.DictReader((SCI / "nordcan_gap_summary.csv").open(encoding="utf-8"))}
        wide = {(r["cancer"].lower(), r["sex"].lower(), r["period"]): r for r in csv.DictReader((SCI / "nordcan_survival_1990_2024.csv").open(encoding="utf-8"))}
    except OSError as e:
        summ, wide = {}, {}
        out.problems.append(f"goal3: science nordic_gap artifacts missing: {e}")
    sv_calls, sv_ts, sv_bad, sv_n = [], None, [], 0
    for cancer in ("lung", "pancreas", "liver"):
        for sex in ("male", "female"):
            s = summ.get((cancer, sex))
            if not s:
                continue
            w = wide.get((cancer, sex, s["latest_period"]), {})
            url = (f"{NORDCAN}/survival/population/5/{NC_SEX[sex]}/246_752_578_208/{NC_CANCER[cancer]}/"
                   "?&surv_period=5&age_surv=0&year_start=1973&year_end=2023")
            row = {"cancer": cancer, "sex": sex, "finland": fnum(s["surv_Finland_latest"]), "sweden": fnum(w.get("surv_Sweden")),
                   "norway": fnum(w.get("surv_Norway")), "benchmark": round(float(s["benchmark_latest"]), 2),
                   "gap_pp": round(float(s["gap_latest"]), 2), "gap_lo": round(float(s["gap_latest_lowCI"]), 2),
                   "gap_hi": round(float(s["gap_latest_upCI"]), 2), "lag_years": round(float(s["lag_years"]), 1),
                   "gap_change_pp_per_decade": round(float(s["gap_change_per_decade"]), 2),
                   "strategy_target_pp": strat_pp.get(cancer, STRATEGY_TARGET_PP[cancer]), "period": s["latest_period"],
                   "source_url": url, "source_id": "nordcan_goal3_survival", "kind": "measured",
                   "derived": ["benchmark", "gap_pp", "gap_lo", "gap_hi", "lag_years", "gap_change_pp_per_decade"],
                   "method_en": ("finland / sweden / norway: NORDCAN age-standardised 5-year relative survival (%), as published. benchmark = mean of Sweden and "
                                 "Norway; gap_pp = Finland minus benchmark; lag_years = how many years ago the benchmark was at Finland's current level "
                                 f"({s['lag_note']}); gap_change_pp_per_decade = linear trend of the gap over {s['gap_periods_used']} "
                                 "(negative = Finland falling further behind). Derived values computed in science/out/nordic_gap."),
                   "verified": False}
            try:
                raw, sv_ts = fetch(url, G3, f"nordcan_survival_{NC_CANCER[cancer]}_{NC_SEX[sex]}.json")
                sv_calls.append(url)
                api = {NC_COUNTRY[r["country"]]: fnum((r.get("survival") or {}).get("value")) for r in json.loads(raw)["dataset"]
                       if r.get("period") == s["latest_period"] and r.get("country") in NC_COUNTRY}
                same = all(api.get(k) == row[k] for k in ("finland", "sweden", "norway"))
                row["verified"] = same
                sv_n += 1
                if not same:
                    sv_bad.append((cancer, sex, {k: (row[k], api.get(k)) for k in ("finland", "sweden", "norway")}))
            except (FetchError, ValueError, KeyError) as e:
                out.problems.append(f"goal3 nordcan survival {cancer} {sex}: {e}")
            survival_targets.append(row)
    if sv_calls:
        out.source("nordcan_goal3_survival", title="NORDCAN 5-year relative survival, Finland / Sweden / Norway / Denmark, lung, pancreas and liver, by sex",
                   publisher="NORDCAN (IARC, Association of the Nordic Cancer Registries)", url="https://nordcan.iarc.fr/",
                   api_call="GET " + " ; ".join(sv_calls), retrieved_at=sv_ts, licence="NORDCAN terms of use (free with citation)",
                   notes="Age-standardised 5-year relative survival (%), 5-year periods, API field 'survival'. NORDCAN publishes survival by sex only "
                         "(no both-sexes figure) and for countries only (not for the Finnish regions). Gap, lag and trend are derived in "
                         "science/out/nordic_gap/artifacts/nordcan_gap_summary.csv and re-checked against this download by pipeline/p08_goal3.py.")
    check("NORDCAN survival in the science artifacts equals a fresh API download (Finland, Sweden, Norway, latest period)",
          sv_n == 6 and not sv_bad, f"{sv_n - len(sv_bad)} of {sv_n} cancer x sex rows identical; differences: {sv_bad or 'none'}")

    # ------------------------------------------------------------------ national mortality trend, all cancers
    mortality_trend = None
    m_b = re.search(r"Syöpäkuolleisuus pienenee 10 % \(nykyisin ([\d ]+) henkilöä vuodessa\)", flat)
    if "mortality_by_year" in fcr:
        v = fcr["mortality_by_year"]
        ser = {}
        for r in v["rows"]:
            cancer, sex, y = SITE_FI.get(r["Syöpätauti"]), SEX_FI.get(r["Sukupuoli"]), int(r["Vuosi"])
            if cancer and sex and y >= 2000:
                ser.setdefault((cancer, sex), []).append(
                    {"year": y, "value": fnum(next(val for k, val in r.items() if "Suomi 2014" in k)), "deaths_n": fnum(col(r, "Syöpäkuolemia"))})
        for s in ser.values():
            s.sort(key=lambda p: p["year"])
        main = ser[("all", "all")]
        by_year = {p["year"]: p for p in main}
        last = main[-1]
        stated = int(m_b.group(1).replace(" ", "")) if m_b else None
        cands = [p["year"] for p in main if stated and p["year"] >= 2018 and round(p["deaths_n"], -2) == stated]
        base_year = 2022 if 2022 in cands or not cands else cands[-1]
        b = by_year[base_year]
        ten = by_year.get(last["year"] - 10)
        mortality_trend = {
            "indicator": "All-cancer mortality, both sexes, age-standardised (Finland 2014 standard population)",
            "unit": "deaths per 100,000 person-years", "baseline_year": base_year, "baseline_year_stated_in_strategy": False,
            "baseline_candidates": cands, "target_pct": -10,
            "baseline_value": b["value"], "baseline_deaths_n": b["deaths_n"], "strategy_stated_deaths_per_year": stated,
            "target_value": round(b["value"] * 0.9, 2), "target_deaths_n": round(stated * 0.9) if stated else None,
            "latest": last, "change_since_baseline_pct": round(100 * (last["value"] / b["value"] - 1), 1),
            "deaths_change_since_baseline_pct": round(100 * (last["deaths_n"] / b["deaths_n"] - 1), 1),
            "last_10_years": None if not ten else {"from_year": ten["year"], "to_year": last["year"],
                                                   "rate_change_pct": round(100 * (last["value"] / ten["value"] - 1), 1),
                                                   "deaths_change_pct": round(100 * (last["deaths_n"] / ten["deaths_n"] - 1), 1)},
            "series": main, "series_by_sex": {"male": ser.get(("all", "male")), "female": ser.get(("all", "female"))},
            "by_cancer": {c: ser.get((c, "all")) for c in ("lung", "pancreas", "liver")},
            "source_url": v["meta"]["url"], "source_id": src_of["mortality_by_year"], "kind": "measured",
            "derived": ["target_value", "target_deaths_n", "change_since_baseline_pct", "deaths_change_since_baseline_pct", "last_10_years"],
            "strategy_quote_fi": m_b.group(0) if m_b else None, "strategy_source": "res/strategy/s.txt (Kansallinen syöpästrategia 2026-2035, indicator table)",
            "note_en": (f"The strategy says 'cancer mortality falls by 10 % (currently {stated:,} people a year)' and gives no baseline year and no statement on "
                        f"whether the 10 % is counted in deaths or in the age-standardised rate. The registry's death counts round to {stated:,} in "
                        f"{' and '.join(map(str, cands)) or 'no recent year'}; {base_year} is used here as the baseline (our reading, not the strategy's wording). "
                        f"In {base_year} the rate was {b['value']} and deaths {b['deaths_n']:,}; in {last['year']} {last['value']} and {last['deaths_n']:,}. "
                        + (f"Over the last ten years ({ten['year']}-{last['year']}) the age-standardised rate changed "
                           f"{round(100 * (last['value'] / ten['value'] - 1), 1)} % while the number of deaths changed "
                           f"{round(100 * (last['deaths_n'] / ten['deaths_n'] - 1), 1):+} % (ageing population). " if ten else "")
                        + ("So a 10 % fall in the rate over ten years is close to the existing trend, while a 10 % fall in the number of deaths would "
                           "need a break in the trend. " if ten and last["value"] < ten["value"] * 0.95 and last["deaths_n"] > ten["deaths_n"] else "")
                        + "Rates are per 100,000 person-years, standardised to the Finnish 2014 population; series from 2000.")
            if stated else "Baseline sentence not found in res/strategy/s.txt; baseline year set to 2022 by default."}
        check("strategy mortality baseline ('nykyisin 13 300 henkilöä vuodessa') found in res/strategy/s.txt and matched to registry years",
              bool(stated and cands), f"stated {stated}; registry deaths (all cancers, both sexes): "
              + ", ".join(f"{y}: {by_year[y]['deaths_n']}" for y in range(2020, last["year"] + 1) if y in by_year) + f"; years rounding to it: {cands}")
        # second source for the national series: NORDCAN all sites, deaths per year
        try:
            raw, _ = fetch(f"{NORDCAN}/data/population/1/0/246/980/?year_start=2020&year_end=2024", G3, "nordcan_mortality_980_0.json")
            nd = {r["year"]: r["total"] for r in json.loads(raw)["dataset"] if r.get("country") == 246}
            diffs = {y: round(100 * (by_year[y]["deaths_n"] - nd[y]) / nd[y], 2) for y in sorted(nd) if y in by_year}
            check("national all-cancer deaths by year match NORDCAN 'All sites' within 0.5 %", all(abs(d) <= 0.5 for d in diffs.values()),
                  "; ".join(f"{y}: {by_year[y]['deaths_n']} vs {round(nd[y], 1)} ({diffs[y]} %)" for y in diffs))
        except (FetchError, ValueError, KeyError) as e:
            out.problems.append(f"goal3 nordcan all-sites deaths by year: {e}")
        # the yearly table must agree with the 5-year table
        if tables and period5:
            y0, y1 = int(period5[:4]), int(period5[5:])
            s5 = {c: sum(p["deaths_n"] for p in ser[(c, "all")] if y0 <= p["year"] <= y1) for c in SITES.values()}
            t5 = {c: tables.get(("mortality", "FI", c, "all"), {}).get("n") for c in SITES.values()}
            check(f"registry yearly deaths {period5} add up to the registry's 5-year table (national, both sexes)", s5 == t5, f"yearly sums {s5}; 5-year table {t5}")
    if "incidence_by_year" in fcr and tables and period5:
        y0, y1 = int(period5[:4]), int(period5[5:])
        s5 = {}
        for r in fcr["incidence_by_year"]["rows"]:
            if SEX_FI.get(r["Sukupuoli"]) == "all" and y0 <= int(r["Vuosi"]) <= y1:
                c = SITE_FI[r["Syöpätauti"]]
                s5[c] = s5.get(c, 0) + fnum(col(r, "Todettuja"))
        t5 = {c: tables.get(("incidence", "FI", c, "all"), {}).get("n") for c in s5}
        check(f"registry yearly new cases {period5} add up to the registry's 5-year table (national, both sexes)", s5 == t5, f"yearly sums {s5}; 5-year table {t5}")

    # ------------------------------------------------------------------ treated within target times
    twt = treated_within_target(out)

    # ------------------------------------------------------------------ notes and output
    small = {}
    for r in county:
        if r.get("small_n") and r["metric"] in ("cases_n", "deaths_n"):
            small.setdefault(f"{r['cancer']} {r['metric'][:-2]} ({r['sex']})", []).append(r["area_id"])
    surv_missing = {}
    for cancer in ("lung", "pancreas", "liver"):
        for yrs in (1, 5):
            miss = [y for y in list(YTA_APP.values()) + ["ALAND"] if ("yta:" + y, cancer, "all", yrs) not in surv]
            if miss:
                surv_missing[f"{cancer} {yrs}-year"] = miss
    n_supp = sum(1 for r in county if r.get("suppressed_n") and r["metric"] in ("cases_n", "deaths_n"))
    notes += [
        f"Incidence and mortality: Finnish Cancer Registry statistics application, {period5}, by wellbeing services county of residence (21 counties, "
        "Helsinki, Åland). Counts are five-year totals (per_year = count / 5). Rates are per 100,000 person-years, age-standardised to the Finnish 2014 "
        "population (crude_rate and asr_world, World standard, are kept on each rate row). Standardisation removes age-structure differences only: "
        "nothing is adjusted for smoking, alcohol, hepatitis, stage at diagnosis, comorbidity or socioeconomic position.",
        "Site definitions (registry): lung = lung and trachea C33-34; pancreas = C25; liver = C22; all = all cancers together "
        f"({SITE_ICD['all']}).",
        f"Small numbers: rows with fewer than {SMALL_N} cases or deaths in the five years carry small_n: true (cancer, measure, sex: area ids): "
        + "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(small.items())) + ". A rate built on under 20 events can double or halve by chance. "
        "The registry publishes no confidence intervals for the rates; with 100 events the 95 % range of a rate is still roughly +/- 20 % "
        "(Poisson), so look at n before reading a county difference in pancreas or liver rates. "
        + (f"{n_supp} counts are blank in the registry's table (value null, suppressed_n: true); the rate is still published." if n_supp else ""),
        "Mortality is not a measure of care quality on its own: it mixes how many people get the cancer (incidence) with how long they live after diagnosis. "
        "Compare mortality_asr with incidence_asr for the same county before reading a high death rate as a care problem. No causal claims from county aggregates.",
        "Survival is NOT published by county. The registry publishes age-standardised relative survival (1 to 5 years from diagnosis, "
        f"{fcr['survival']['period'] if 'survival' in fcr else 'n/a'}) for the whole "
        "country, the five collaborative areas and Åland. County rows for survival_1y_pct / survival_5y_pct repeat the collaborative area's value and say so "
        "(level: collaborative_area); true-level rows are in collaborative_area[]. All-cancer survival is national only. Values the registry does not give "
        "(both sexes; collaborative areas without a value): " + "; ".join(f"{k}: {', '.join(v)}" for k, v in surv_missing.items()) + ".",
        "Survival targets use NORDCAN (5-year periods, by sex, countries only) because the strategy defines the target against NORDCAN. The registry's own "
        "national 5-year figures (in national[]) cover a different period and are not interchangeable with NORDCAN's.",
        "The strategy's survival targets (+14 pp lung, +6 pp pancreas, +14 pp liver, 'from the 2023 level shown in NORDCAN', Nordic level = mean of Sweden and "
        "Norway) are not given by sex; strategy_target_pp repeats the same figure on the male and the female row.",
    ]
    goal3 = {"generated_at": now_iso(),
             "survival_targets": survival_targets,
             "mortality_trend": mortality_trend,
             "county": sorted(county, key=lambda r: (r["cancer"], r["metric"], r["sex"], r["area_id"])),
             "collaborative_area": sorted(yta_rows, key=lambda r: (r["cancer"], r["metric"], r["sex"], r["area_id"])),
             "national": sorted(national, key=lambda r: (r["cancer"], r["metric"], r["sex"])),
             "treated_within_target": twt,
             "notes_en": notes,
             "second_source_comparison": {"nordcan_national_2020_2024": nc_cmp, "statfin_13u5_deaths_2020_2024": sf_cmp},
             "checks": checks,
             "problems": out.problems}
    (PROC / "goal3.json").write_text(json.dumps(goal3, ensure_ascii=False, indent=1))

    # sources.json: add / refresh this script's own keys, leave everything else untouched
    sp = PROC / "sources.json"
    sources = json.loads(sp.read_text()) if sp.exists() else {}
    sources.update(out.sources)
    sp.write_text(json.dumps(sources, ensure_ascii=False, indent=1))
    out.extra["rows"] = {"county": len(county), "collaborative_area": len(yta_rows), "national": len(national)}
    out.save()
    return out


def treated_within_target(out: Out) -> dict:
    """Share of cancer patients treated within target times: nothing cancer-specific is published. Record what
    was opened, and attach the nearest public measurements as clearly labelled proxies (from existing pipeline output)."""
    ev = []
    # 1. THL guide: targets, and its own statement on publication
    guide_ok, guide_ts = False, None
    quote = "Syöpään sairastuneiden hoidon osalta tiedot toteutuneista odotusajoista löytyvät THL.fi-sivustolta, heti kun aineiston laatu saadaan hyväksyttävälle tasolle."
    target_quote = "ensimmäiseen hoitoon (leikkaus, lääke- tai sädehoito) on 6 viikkoa"
    target_ok = False
    try:
        raw, guide_ts = fetch(THL_GUIDE, G3, "thl_ohjaus_21_2016.pdf", headers={"User-Agent": BROWSER_UA})
        exe = shutil.which("pdftotext")
        if raw[:4] == b"%PDF" and exe:
            txt = subprocess.run([exe, "-enc", "UTF-8", str(RAWDIR / "thl_ohjaus_21_2016.pdf"), "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
            (RAWDIR / "thl_ohjaus_21_2016.txt").write_text(txt)
            sq = lambda s: re.sub(r"[\s­-]+", "", s)  # noqa: E731  (line breaks and hyphenation differ in the PDF text)
            guide_ok = sq("tiedot toteutuneista odotusajoista löytyvät THL.fi-sivustolta, heti kun aineiston laatu saadaan hyväksyttävälle tasolle") in sq(txt)
            target_ok = sq(target_quote) in sq(txt)
    except (FetchError, OSError, subprocess.SubprocessError) as e:
        out.problems.append(f"goal3 THL Ohjaus 21/2016: {e}")
    out.source("thl_ohjaus_21_2016", title="Hoitoonpääsyn seuranta syövän hoidossa: määrittelyt ja ohjeistus (THL Ohjaus 21/2016, in force from 1 Jan 2017)",
               publisher="Finnish Institute for Health and Welfare (THL)", url=THL_GUIDE, api_call=f"GET {THL_GUIDE} (PDF; text via pdftotext)",
               retrieved_at=guide_ts, licence="THL publication (Julkari open repository)",
               notes=("The target-time definition the strategy's indicator 'patients are treated within target times' points to. Quote checked in the "
                      f"downloaded PDF: '{quote}' (reporting chapter): {'found' if guide_ok else 'NOT confirmed by this run'}. "
                      f"Target quote '{target_quote}' (6 weeks from referral to first treatment): {'found' if target_ok else 'NOT confirmed by this run'}."),
               verified=guide_ok)
    ev.append({"claim_en": "THL's 2016 guide says realised cancer waiting times will be on THL.fi 'as soon as the quality of the data reaches an acceptable level'.",
               "quote_fi": quote, "url": THL_GUIDE, "verified": guide_ok})
    ev.append({"claim_en": "Target in the guide: at most 6 weeks (42 days) from arrival of the referral to first treatment (surgery, drug therapy or radiotherapy) when cancer is suspected.",
               "quote_fi": target_quote, "url": THL_GUIDE, "verified": target_ok})
    # 2. THL open specialist-care queue reports: by specialty and procedure group, not by cancer
    rep_ok, rep_ts, titles = False, None, []
    try:
        raw, rep_ts = fetch(THL_QUEUE_REPORTS, G3, "thl_eshjono_reports.html", headers={"User-Agent": BROWSER_UA})
        html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw.decode("utf-8", "replace"), flags=re.S)
        text = [re.sub(r"\s+", " ", t).strip() for t in re.sub(r"<[^>]+>", "\n", html).split("\n")]
        titles = sorted({t for t in text if re.search(r"odottav|Jonoryhm|Lähetteet|vertailu|Erikoisala|Aikasarja|mielenterveys", t) and len(t) < 160})
        rep_ok = bool(titles) and not any(re.search(r"syöp|syov", t, flags=re.I) for t in titles)
    except FetchError as e:
        out.problems.append(f"goal3 THL queue report list: {e}")
    out.source("thl_eshjono_report_list", title="THL specialist care access (hoitoonpääsy erikoissairaanhoidossa): list of open reports and cubes",
               publisher="Finnish Institute for Health and Welfare (THL)", url=THL_QUEUE_REPORTS, api_call=f"GET {THL_QUEUE_REPORTS}",
               retrieved_at=rep_ts, licence="CC BY 4.0",
               notes=(f"{len(titles)} report titles read: " + " | ".join(titles) + ". None is by cancer diagnosis or reports time from referral to first cancer "
                      "treatment; the breakdowns are specialty and procedure queue group. THL's own web pages (thl.fi) answered scripted and headless-browser "
                      "requests with a bot challenge (HTTP 403) on 13 Nov 2026 and could not be read." if titles else "Report list could not be read."),
               verified=rep_ok)
    ev.append({"claim_en": "THL's open specialist-care waiting-time reports are broken down by specialty and procedure queue group; none by cancer diagnosis.",
               "report_titles_fi": titles, "url": THL_QUEUE_REPORTS, "verified": rep_ok})
    ev.append({"claim_en": "THL's own statistics pages on thl.fi could not be opened (bot challenge, HTTP 403), so the absence of a cancer-specific publication there is not verified.",
               "url": "https://thl.fi/", "verified": False})
    # 3. the strategy's roadmap: cancer-specific access times are still to be defined
    road = re.sub(r"\s+", " ", (ROOT / "res" / "roadmap" / "r.txt").read_text(encoding="utf-8", errors="replace").replace("­", ""))
    m = re.search(r"2026–2028: Kansalliset hoitoketjukuvaukset tehty viidestä syövästä ja syöpäkohtaiset hoitoonpääsyajat on määritetty\.", road)
    ev.append({"claim_en": "The strategy's implementation roadmap schedules the definition of cancer-specific access times for 2026-2028 (measure 3.1.2).",
               "quote_fi": m.group(0) if m else None, "url": None, "local_copy": "res/roadmap/r.txt", "verified": bool(m)})

    # proxies from existing pipeline output (not the indicator itself)
    rows = []
    try:
        srcs = json.loads((PROC / "sources.json").read_text())
        want = {"oncology_referrals_handled_over_21d_pct": "Share of oncology-specialty referrals processed in more than 21 days (statutory limit for all specialist care, not a cancer target; by service provider)",
                "oncology_queue_over_90d_pct": "Share of people waiting for treatment in the oncology specialty who have waited over 90 days (snapshot; all oncology-specialty care, not time to first cancer treatment)",
                "oncology_assessment_over_90d_pct": "Share waiting for assessment of need for care in the oncology specialty for over 90 days (snapshot)"}
        ind = [json.loads(line) for line in (PROC / "indicators.jsonl").read_text().splitlines() if line.strip()]
        for key, what in want.items():
            rs = [r for r in ind if r["indicator"] == key]
            latest = max((r["period"] for r in rs), default=None)
            for r in rs:
                if r["period"] == latest:
                    rows.append({"area_id": r["area_id"], "cancer": "all", "metric": key, "value": r["value"], "unit": r["unit"], "period": r["period"],
                                 "source_id": r["source_id"], "source_url": (srcs.get(r["source_id"]) or {}).get("url"), "kind": "measured",
                                 "proxy": True, "what_en": what})
        for line in (PROC / "gemini_extracted.jsonl").read_text().splitlines():
            r = json.loads(line) if line.strip() else {}
            if r.get("indicator", "").startswith("lung_days_diagnosis_to_") and (r["area_id"] == "FI" or r["area_id"].startswith("yta:")) and r.get("verified") \
                    and "syoparekisteri.fi" in (r.get("source_url") or ""):
                rows.append({"area_id": r["area_id"], "cancer": "lung", "metric": r["indicator"], "value": r["value"], "unit": r["unit"], "period": r["period"],
                             "source_url": r["source_url"], "page": r.get("page"), "quote": r.get("quote"), "read_by": r.get("read_by"), "kind": "measured",
                             "proxy": True, "level": "collaborative_area" if r["area_id"] != "FI" else "national",
                             "what_en": "Median days from diagnosis to first treatment (Cancer Registry lung cancer report; a median from diagnosis, not a share within the 42-day referral-to-treatment target)"})
    except (OSError, ValueError, KeyError) as e:
        out.problems.append(f"goal3 treated_within_target proxies: {e}")
    return {
        "available": False,
        "indicator_en": "Share of cancer patients whose treatment starts within the target times (strategy indicator; targets from THL Ohjaus 21/2016)",
        "target_en": "THL Ohjaus 21/2016: at most 6 weeks (42 days) from arrival of the referral to first treatment when cancer is suspected; imaging report, biopsy and pathology report each within one week.",
        "rows": rows,
        "rows_note_en": "rows[] are PROXIES from other public statistics, not the indicator: none of them is the share of cancer patients treated within the target time.",
        "data_gap_en": ("No public source gives, for any cancer or any area, the share of cancer patients whose first treatment started within the target time. "
                        "What was opened: (1) THL's 2016 guide defines the monitoring from the hospital care register (Hilmo) and says results will appear on THL.fi "
                        "once data quality is acceptable; (2) THL's open specialist-care waiting-time reports are by specialty and procedure group only, so 'oncology' "
                        "there means the oncology clinic's queue, not the cancer pathway; (3) the Cancer Registry's lung cancer report gives median days from diagnosis "
                        "to first treatment by collaborative area (2018 to mid-2022), not by county, and we found no equivalent for pancreas or liver; (4) the strategy's roadmap "
                        "schedules cancer-specific access times to be defined in 2026-2028. thl.fi itself could not be opened by script (bot challenge), so a "
                        "publication there cannot be ruled out; a web search on 13 Nov 2026 found none."),
        "who_could_publish_en": ("THL, from Hilmo: referral date, diagnosis date and first treatment date by cancer and wellbeing services county, as the share within 42 days "
                                 "(the monitoring THL specified in Ohjaus 21/2016). The Finnish Cancer Registry could add time-to-treatment by county and for pancreas and "
                                 "liver to its quality reports (it already links Hilmo treatment dates for lung cancer). The wellbeing services counties and HUS hold the "
                                 "referral and treatment dates in their own patient systems; FICAN / the national cancer centre is named in the strategy as responsible for "
                                 "monitoring equal access."),
        "evidence": ev,
        "kind": "data_gap"}


if __name__ == "__main__":
    o = run()
    g = json.loads((PROC / "goal3.json").read_text())
    print("rows:", o.extra.get("rows"), "| survival_targets:", len(g["survival_targets"]),
          "| trend years:", len((g["mortality_trend"] or {}).get("series") or []), "| proxies:", len(g["treated_within_target"]["rows"]))
    for c in g["checks"]:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + "\n       " + c["result"][:600])
    print("problems:", o.problems)
