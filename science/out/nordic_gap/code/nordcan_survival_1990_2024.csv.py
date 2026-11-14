import json, os, hashlib, time
import numpy as np
import pandas as pd
import requests
from scipy import stats

OFFLINE   = False
BASE      = "https://canapi.iarc.who.int/api/nordcan/v2/961"
COUNTRIES = "246_752_578_208"
CANCERS   = {160: "Lung", 130: "Pancreas", 110: "Liver"}
SEXES     = {1: "Male", 2: "Female"}
PERIODS   = [f"{y}-{y+4}" for y in range(1990, 2021, 5)]
Z = 1.959963985

def get_payloads():
    os.makedirs("raw_api", exist_ok=True)
    payloads, manifest = {}, []
    for c in CANCERS:
        for s in SEXES:
            fn = f"raw_api/survival_cancer{c}_sex{s}.json"
            url = f"{BASE}/survival/population/5/{s}/{COUNTRIES}/{c}/"
            par = {"surv_period": 5, "age_surv": 0, "year_start": 1973, "year_end": 2023}
            if OFFLINE:
                text, status, full = open(fn).read(), "offline", url
            else:
                r = requests.get(url, params=par, timeout=60)
                r.raise_for_status()
                text, status, full = r.text, r.status_code, r.url
                with open(fn, "w") as f:
                    f.write(text)
                time.sleep(0.3)
            j = json.loads(text)
            payloads[(c, s)] = j
            manifest.append(dict(cancer=c, cancer_label=CANCERS[c], sex=s, sex_label=SEXES[s],
                                 url=full, status=status, n_records=len(j.get("dataset", [])),
                                 api_error=j.get("error"), file=fn,
                                 sha256=hashlib.sha256(text.encode()).hexdigest()))
    with open("raw_api/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    return payloads, manifest

def tidy(payloads):
    rows = []
    for (c, s), j in payloads.items():
        for d in j["dataset"]:
            sv = d.get("survival") or {}
            rows.append(dict(cancer=c, cancer_label=CANCERS[c], sex=s, sex_label=SEXES[s],
                             country=d["country"], country_label=d["label"],
                             period=d["period"], year_mid=float(d["year"]),
                             survival=sv.get("value"), lowCI=sv.get("lowCI"), upCI=sv.get("upCI")))
    df = pd.DataFrame(rows)
    for col in ("survival", "lowCI", "upCI"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["se"] = (df.upCI - df.lowCI) / (2 * Z)
    return df.sort_values(["cancer", "sex", "country_label", "year_mid"]).reset_index(drop=True)

def build_table(df):
    d = df[df.period.isin(PERIODS)]
    wide = d.pivot_table(index=["cancer_label", "sex_label", "period", "year_mid"],
                         columns="country_label", values=["survival", "se"])
    out = []
    for (can, sex, per, ymid), r in wide.iterrows():
        rec = dict(cancer=can, sex=sex, period=per, year_mid=ymid)
        for ctry in ["Finland", "Sweden", "Norway", "Denmark"]:
            rec[f"surv_{ctry}"] = r.get(("survival", ctry), np.nan)
            rec[f"se_{ctry}"]   = r.get(("se", ctry), np.nan)
        se_no  = [rec["surv_Sweden"], rec["surv_Norway"]]
        se_var = [rec["se_Sweden"], rec["se_Norway"]]
        if not any(pd.isna(v) for v in se_no):
            rec["benchmark_SE_NO_mean"] = float(np.mean(se_no))
            bse = float(np.sqrt(np.sum(np.array(se_var) ** 2)) / 2)
            rec["benchmark_se"] = bse
            if not pd.isna(rec["surv_Finland"]):
                rec["gap_FI_minus_benchmark"] = rec["surv_Finland"] - rec["benchmark_SE_NO_mean"]
                gse = float(np.sqrt(rec["se_Finland"] ** 2 + bse ** 2))
                rec["gap_se"]    = gse
                rec["gap_lowCI"] = rec["gap_FI_minus_benchmark"] - Z * gse
                rec["gap_upCI"]  = rec["gap_FI_minus_benchmark"] + Z * gse
        out.append(rec)
    t = pd.DataFrame(out).sort_values(["cancer", "sex", "year_mid"])
    for c in ["benchmark_SE_NO_mean", "benchmark_se", "gap_FI_minus_benchmark",
              "gap_se", "gap_lowCI", "gap_upCI"]:
        t[c] = t.get(c, np.nan)
    return t.reset_index(drop=True)

payloads, manifest = get_payloads()
df = tidy(payloads)
df.to_csv("nordcan_survival_long_all_periods.csv", index=False)
tab = build_table(df)
tab.to_csv("nordcan_survival_1990_2024.csv", index=False)