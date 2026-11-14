"""Finnish Cancer Registry lung cancer quality report (county level). The site sits behind a
bot challenge; if the pages cannot be fetched they are recorded as unverified sources."""
from __future__ import annotations

import io
import json
import re

import pandas as pd

from common import Out, fetch, FetchError, BROWSER_UA, now_iso, load_areas, PARTS, AREA_IDS

MODALITIES = {  # Finnish label in the report -> (key, English, Finnish, direction, step)
    "Parantava": ("lung_curative_intent_pct", "Lung cancer patients who received curative-intent treatment",
                  "Parantavaan hoitoon ohjautuneet keuhkosyöpäpotilaat", "higher_is_better", "treatment"),
    "Jarruttava": ("lung_life_prolonging_treatment_pct", "Lung cancer patients whose first treatment was life-prolonging (non-curative) oncological treatment",
                   "Jarruttavaa hoitoa saaneet keuhkosyöpäpotilaat", "context", "treatment"),
    "Oireenmukainen": ("lung_symptomatic_care_only_pct", "Lung cancer patients with symptomatic (palliative) care as treatment modality",
                       "Oireenmukaista hoitoa saaneet keuhkosyöpäpotilaat", "context", "treatment"),
    "Ei hoitotietoa": ("lung_no_treatment_record_pct", "Lung cancer patients with no treatment information in the care register",
                       "Keuhkosyöpäpotilaat, joilla ei hoitotietoa", "higher_is_worse", "treatment"),
    "MDT-käsittely": ("lung_mdt_recorded_pct", "Lung cancer patients with a recorded multidisciplinary team (MDT) meeting",
                      "Keuhkosyöpäpotilaat, joilla kirjattu MDT-käsittely", "higher_is_better", "diagnosis"),
}


def parse_lung_report(raw: bytes, out: Out, sid: str) -> int:
    """Parse the county tables of the FCR lung cancer quality report (new cases 2019-2023)."""
    html = raw.decode("utf-8", "replace")
    html = re.sub(r'src="data:image/[^"]{200,}"', 'src=""', html)
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    tabs = pd.read_html(io.StringIO(html))
    name2id = {a["name_fi"]: a["id"] for a in load_areas()}
    name2id["Helsingin kaupunki"] = "90"
    period = "2019-2023"
    for lab, (key, en, fi, direction, step) in MODALITIES.items():
        out.define(key, label_en=en, label_fi=fi, unit="%", direction=direction, step=step,
                   definition_en=(f"Finnish Cancer Registry lung cancer quality report: share of new lung cancer patients diagnosed 2019-2023 in treatment category '{lab}' "
                                  "(first-line treatment modality within 12 months, from the hospital care register HILMO), by county of residence. Crude share, not age- or stage-adjusted."))
    out.define("lung_cases_5y_n", label_en="New lung cancer cases 2019-2023", label_fi="Uudet keuhkosyövät 2019-2023", unit="cases", direction="context", step="outcome",
               definition_en="Finnish Cancer Registry lung cancer quality report: number of new lung cancers diagnosed 2019-2023 (denominator of the treatment shares).")
    out.define("lung_incidence_per_100k", label_en="Lung cancer incidence, crude, 2019-2023", label_fi="Keuhkosyövän ilmaantuvuus 2019-2023, vakioimaton",
               unit="per 100,000 per year", direction="higher_is_worse", step="outcome",
               definition_en=("New lung cancers 2019-2023 (Finnish Cancer Registry quality report) / sum of year-end populations 2019-2023 (Statistics Finland 11ra) x 100,000. "
                              "Crude; computed by the pipeline from two measured sources."))
    out.define("lung_stage_known_pct", label_en="Lung cancers with stage information recorded", label_fi="Keuhkosyövät, joilla levinneisyystieto", unit="%",
               direction="higher_is_better", step="diagnosis",
               definition_en="Finnish Cancer Registry lung cancer quality report, stage coverage table: 100 minus the share with 'Ei tietoa' (no stage information), new cases 2019-2023. National only in table form.")
    n = 0
    totals = {}
    for tb in tabs:
        cols = [str(c) for c in tb.columns]
        if cols[:3] == ["Hoitomuoto", "Yhteistyöalue", "Hyvinvointialue"]:
            cur = None
            for row in tb.itertuples(index=False):
                vals = [str(v) for v in row]
                if vals[1] in MODALITIES and vals[2] == vals[1]:
                    cur = vals[1]
                    continue
                if vals[0] in MODALITIES:
                    cur = vals[0]
                area = name2id.get(vals[2])
                if cur is None or area is None:
                    continue
                try:
                    cnt, tot, pct = float(vals[3]), float(vals[4]), float(vals[5])
                except ValueError:
                    continue
                out.add(area, MODALITIES[cur][0], pct, period, sid, note=f"{int(cnt)} of {int(tot)} patients")
                n += 1
                if cur == "Parantava":
                    totals[area] = int(tot)
        elif cols[:2] == ["Hoitomuoto", "Yhteistyöalue"]:
            for row in tb.itertuples(index=False):
                if str(row[0]) in MODALITIES and str(row[1]) == "Koko maa":
                    out.add("FI", MODALITIES[str(row[0])][0], float(row[4]), period, sid, note=f"{int(row[2])} of {int(row[3])} patients")
                    n += 1
                    if str(row[0]) == "Parantava":
                        totals["FI"] = int(row[3])
        elif cols[:1] == ["Levinneisyysluokitus"]:
            for row in tb.itertuples(index=False):
                if str(row[0]) == "Ei tietoa":
                    out.add("FI", "lung_stage_known_pct", round(100 - float(row[2]), 1), period, sid,
                            note=f"100 - {row[2]} % with no stage information ({int(row[1])} cases)")
                    n += 1
    pop = {}
    try:
        pop = json.loads((PARTS / "p03_statfin.json").read_text())["extra"].get("pop", {})
    except (OSError, ValueError, KeyError):
        out.problems.append("fcr: population part missing, crude lung incidence not computed")
    for area, tot in totals.items():
        out.add(area, "lung_cases_5y_n", tot, period, sid)
        ps = [pop.get(f"{area}|{y}") for y in range(2019, 2024)]
        if all(ps):
            out.add(area, "lung_incidence_per_100k", round(tot / sum(ps) * 1e5, 1), period, sid,
                    note="computed: cases 2019-2023 (FCR) / sum of year-end population 2019-2023 (Statistics Finland 11ra); crude")
    return n

PAGES = {
    "fcr_lung_quality_report": ("Keuhkosyöpäraportti (lung cancer quality report, interactive factsheet)",
                                "https://syoparekisteri.fi/assets/themes/ssy3/factsheets/keuhkosyoparaportti.html"),
    "fcr_lung_quality_report_pdf": ("Keuhkosyöpä Suomessa (lung cancer in Finland, PDF report, Dec 2024)",
                                    "https://syoparekisteri.fi/assets/files/2024/12/Keuhkosyopa_Suomessa.pdf"),
    "fcr_cancer_in_finland_2023": ("Cancer in Finland 2023 (factsheet)",
                                   "https://syoparekisteri.fi/assets/themes/ssy3/factsheets/cancer_in_finland_2023.html"),
}
WANTED = ("County-level lung cancer incidence, stage distribution, share with known stage, share treated with curative intent "
          "and time from diagnosis to treatment are expected here (indicators lung_incidence_per_100k, lung_stage_known_pct, lung_curative_intent_pct).")


def run() -> Out:
    out = Out("p05_fcr")
    for sid, (title, url) in PAGES.items():
        hdr = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
               "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8"}
        try:
            raw, ts = fetch(url, "fcr", sid + (".pdf" if url.endswith(".pdf") else ".html"), headers=hdr, retries=1)
            head = raw[:4000].decode("utf-8", "replace")
            if "Just a moment" in head or "cf-chl" in head:
                raise FetchError("bot challenge page returned instead of content")
            n_json = len(re.findall(rb"application/json|Plotly\.newPlot|htmlwidget", raw))
            parsed = 0
            out.source(sid, title=title, publisher="Finnish Cancer Registry (Syöpärekisteri)", url=url, api_call=f"GET {url} (browser User-Agent)",
                       retrieved_at=ts, licence="Finnish Cancer Registry, open statistics (cite source)", notes="", verified=False)
            if sid == "fcr_lung_quality_report":
                try:
                    parsed = parse_lung_report(raw, out, sid)
                except Exception as e:  # parsing of an external HTML layout: keep the pipeline alive
                    out.problems.append(f"fcr {sid}: table parse failed: {e!r}")
            if parsed:
                out.sources[sid]["verified"] = True
                out.sources[sid]["notes"] = (f"Downloaded {len(raw)} bytes; {parsed} values parsed from the HTML tables (treatment modality by county, stage coverage). "
                                             "New cases 2019-2023, treatment from HILMO within 12 months. Stage distribution, time from diagnosis to treatment and survival by county "
                                             "are shown only as figures (embedded images / plotly) and are NOT parsed here.")
                out.problems.append(f"fcr {sid}: county tables parsed; figures (time to treatment, stage by county, survival by county) not parsed - need a chart reader")
            else:
                out.sources[sid]["notes"] = (f"Downloaded {len(raw)} bytes to data/raw/fcr/ ({n_json} embedded data blocks) but NOT parsed into indicators. {WANTED}")
                out.problems.append(f"fcr {sid}: downloaded but not parsed ({len(raw)} bytes)")
        except FetchError as e:
            out.source(sid, title=title, publisher="Finnish Cancer Registry (Syöpärekisteri)", url=url, api_call=f"GET {url} (browser User-Agent)",
                       retrieved_at=None, licence="Finnish Cancer Registry, open statistics (cite source)",
                       notes=f"BLOCKED for scripted access at {now_iso()} ({e}); needs a real browser. No values taken from this source. {WANTED}",
                       verified=False)
            out.problems.append(f"fcr {sid}: blocked ({e})")
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(o.problems)
