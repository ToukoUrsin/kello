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
FOCAL, BENCH = "Finland", ["Sweden", "Norway"]
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

def slope_per_decade(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 3:
        return (np.nan,) * 4 + (int(m.sum()),)
    lr = stats.linregress(x[m], y[m])
    tcrit = stats.t.ppf(0.975, m.sum() - 2)
    return (lr.slope * 10, (lr.slope - tcrit * lr.stderr) * 10,
            (lr.slope + tcrit * lr.stderr) * 10, lr.pvalue, int(m.sum()))

def lag_years(years, bench, fi_latest, latest_year):
    y = np.asarray(years, float); b = np.asarray(bench, float)
    m = ~np.isnan(b); y, b = y[m], b[m]
    if len(y) < 2 or np.isnan(fi_latest):
        return np.nan, "insufficient benchmark series"
    if b[-1] <= fi_latest:
        return 0.0, "Finland at or above benchmark in latest period"
    for i in range(1, len(b)):
        if b[i] >= fi_latest > b[i - 1]:
            t = y[i - 1] + (fi_latest - b[i - 1]) * (y[i] - y[i - 1]) / (b[i] - b[i - 1])
            return float(latest_year - t), (f"interpolated between benchmark {b[i-1]:.2f}% at "
                                            f"{int(y[i-1])} and {b[i]:.2f}% at {int(y[i])}")
    if b[0] >= fi_latest:
        return float(latest_year - y[0]), f">= {latest_year - y[0]:.0f} y (benchmark already above in {int(y[0])})"
    return np.nan, "no crossing within available periods"

def summarise(t):
    rows = []
    for (can, sex), g in t.groupby(["cancer", "sex"], sort=False):
        g = g.sort_values("year_mid")
        gv = g.dropna(subset=["gap_FI_minus_benchmark"])
        last = g[g.period == PERIODS[-1]]
        last = last.iloc[0] if len(last) else None
        sl = slope_per_decade(gv.year_mid, gv.gap_FI_minus_benchmark)
        fi_sl = slope_per_decade(g.year_mid, g.surv_Finland)
        bn_sl = slope_per_decade(g.year_mid, g.benchmark_SE_NO_mean)
        lag, lagnote = (lag_years(g.year_mid, g.benchmark_SE_NO_mean,
                                 last["surv_Finland"], last["year_mid"])
                        if last is not None else (np.nan, "latest period absent"))
        rows.append(dict(
            cancer=can, sex=sex,
            latest_period=PERIODS[-1],
            surv_Finland_latest=None if last is None else last["surv_Finland"],
            benchmark_latest=None if last is None else last["benchmark_SE_NO_mean"],
            gap_latest=None if last is None else last["gap_FI_minus_benchmark"],
            gap_latest_lowCI=None if last is None else last["gap_lowCI"],
            gap_latest_upCI=None if last is None else last["gap_upCI"],
            gap_change_per_decade=sl[0], gap_change_lowCI=sl[1],
            gap_change_upCI=sl[2], gap_change_p=sl[3], n_periods_gap=sl[4],
            gap_periods_used=f"{gv.period.iloc[0]}..{gv.period.iloc[-1]}" if len(gv) else "none",
            finland_trend_per_decade=fi_sl[0], benchmark_trend_per_decade=bn_sl[0],
            lag_years=lag, lag_note=lagnote))
    return pd.DataFrame(rows)

payloads, manifest = get_payloads()
df = tidy(payloads)
tab = build_table(df)
summ = summarise(tab)
summ.to_csv("nordcan_gap_summary.csv", index=False)