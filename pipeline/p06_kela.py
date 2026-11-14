"""Kela open data: new special reimbursement entitlements for cancer medicines by county and year."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from common import Out, fetch, FetchError, RAW, PARTS, AREA_IDS, now_iso

URL = ("https://avoindata.suomi.fi/data/dataset/70832958-f7b6-4e09-8350-615362e6ee30/resource/"
       "cc74cc46-2b92-42b5-9a52-55adb3df512f/download/data.csv")
LOCAL = Path("/tmp/kela_lko.csv")
CODES = {"115": ("breast", "breast cancer", "rintasyöpä"), "116": ("prostate", "prostate cancer", "eturauhassyöpä"),
         "117": ("haematological", "leukaemias and other malignant blood diseases", "pahanlaatuiset veritaudit"),
         "128": ("gynaecological", "gynaecological cancers", "gynekologiset syövät"),
         "130": ("other_malignant", "other malignant tumours (includes lung cancer)", "muut pahanlaatuiset kasvaimet")}
KEEP_YEARS = 5


def run() -> Out:
    out = Out("p06_kela")
    try:
        if LOCAL.exists():
            path, ts = LOCAL, None
            ts = __import__("datetime").datetime.fromtimestamp(os.path.getmtime(LOCAL), __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            note_dl = f"File downloaded earlier to {LOCAL} (file time used as retrieval time)."
        else:
            _, ts = fetch(URL, "kela", "lko_data.csv", timeout=600)
            path = RAW / "kela" / "lko_data.csv"
            note_dl = "Downloaded by the pipeline."
    except FetchError as e:
        out.problems.append(f"kela: {e}")
        out.save()
        return out
    agg: dict[tuple[str, str, str], int] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            code = r["korvausoikeus_koodi"]
            if code not in CODES or r["aikatyyppi"] != "Vuosi":
                continue
            area = r["hyvinvointialue_nro"].zfill(2)
            try:
                v = int(r["alkanut_lkm"] or 0)
            except ValueError:
                continue
            for a in (area, "FI"):
                agg[(a, r["vuosi"], code)] = agg.get((a, r["vuosi"], code), 0) + v
    years = sorted({y for (_, y, _) in agg})[-KEEP_YEARS:]
    out.source("kela_special_reimbursement", title="Kela: entitlements to special reimbursement of medicines by wellbeing services county, age, sex and entitlement code",
               publisher="Kela (Social Insurance Institution of Finland)", url="https://avoindata.suomi.fi/data/dataset/70832958-f7b6-4e09-8350-615362e6ee30",
               api_call=f"GET {URL}", retrieved_at=ts, licence="CC BY 4.0",
               notes=(note_dl + " Column alkanut_lkm (entitlements that started during the year) summed over age groups and sexes; rows with area code outside the 23 counties "
                      "are only in the national sum. Lung cancer has no own code: it falls under 130 'other malignant tumours'. National value = sum of all rows."))
    pop = {}
    try:
        pop = json.loads((PARTS / "p03_statfin.json").read_text())["extra"].get("pop", {})
    except (OSError, ValueError, KeyError):
        pass
    for code, (stem, en, fi) in CODES.items():
        k1, k2 = f"kela_new_entitlements_{stem}_n", f"kela_new_entitlements_{stem}_per_100k"
        out.define(k1, label_en=f"New special reimbursement entitlements, {en}", label_fi=f"Alkaneet erityiskorvausoikeudet, {fi} ({code})", unit="persons",
                   direction="context", step="treatment",
                   definition_en=f"Kela entitlement code {code}: number of special reimbursement entitlements for medicines that started during the year.")
        out.define(k2, label_en=f"New special reimbursement entitlements per 100,000, {en}", label_fi=f"Alkaneet erityiskorvausoikeudet / 100 000 as., {fi} ({code})",
                   unit="per 100,000", direction="context", step="treatment",
                   definition_en=f"Kela code {code} new entitlements / year-end population (Statistics Finland 11ra) x 100,000. Crude; computed by the pipeline.")
        for a in AREA_IDS + ["FI"]:
            for y in years:
                v = agg.get((a, y, code))
                if v is None:
                    continue
                out.add(a, k1, v, y, "kela_special_reimbursement")
                p = pop.get(f"{a}|{y}")
                if p:
                    out.add(a, k2, round(v / p * 1e5, 1), y, "kela_special_reimbursement",
                            note="computed: Kela count / Statistics Finland year-end population; crude")
    out.save()
    return out


if __name__ == "__main__":
    o = run()
    print(len(o.rows), "rows;", o.problems)
