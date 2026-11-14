import json, os, hashlib, time
import numpy as np
import pandas as pd
import requests

OFFLINE   = False
BASE      = "https://canapi.iarc.who.int/api/nordcan/v2/961"
COUNTRIES = "246_752_578_208"
CANCERS   = {160: "Lung", 130: "Pancreas", 110: "Liver"}
SEXES     = {1: "Male", 2: "Female"}
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

payloads, manifest = get_payloads()
df = tidy(payloads)
df.to_csv("nordcan_survival_long_all_periods.csv", index=False)