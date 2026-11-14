import json, os, hashlib, time
import numpy as np
import pandas as pd
import requests
from scipy import stats
import matplotlib as mpl
import matplotlib.pyplot as plt

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

COL = {"Finland": "#C2272D", "Sweden": "#2B6CB0", "Norway": "#1B9E77",
       "Denmark": "#9AA0A6", "SE/NO mean": "#111111"}

def apply_figure_style(sizes=(9, 8, 7)):
    base, ann, tick = sizes
    mpl.rcParams.update({"figure.dpi": 150, "savefig.dpi": 300, "savefig.bbox": None,
                         "font.size": base, "axes.titlesize": base, "axes.labelsize": base,
                         "legend.fontsize": ann, "xtick.labelsize": tick, "ytick.labelsize": tick,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "xtick.direction": "out", "ytick.direction": "out",
                         "legend.frameon": False, "axes.titlelocation": "left",
                         "axes.titleweight": "regular"})

def panel_letter(ax, letter, case="lower"):
    ax.text(-0.02, 1.06, letter.lower() if case == "lower" else letter.upper(),
            transform=ax.transAxes, fontweight="bold",
            fontsize=mpl.rcParams["font.size"] + 2, va="bottom", ha="right")

def set_frame(ax, which="lb"):
    for s, k in [("left", "l"), ("bottom", "b"), ("top", "t"), ("right", "r")]:
        ax.spines[s].set_visible(k in which)

def make_figure(t, cancer, fname):
    apply_figure_style()
    sub = t[t.cancer == cancer]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.5))
    for ax, sex in zip(axes[:2], ["Male", "Female"]):
        g = sub[sub.sex == sex].sort_values("year_mid")
        ax.fill_between(g.year_mid, g.surv_Finland - Z * g.se_Finland,
                        g.surv_Finland + Z * g.se_Finland, color=COL["Finland"], alpha=.15, lw=0)
        for ctry, lw, ls, alpha, mk, ms in [("Denmark", 1.2, (0, (1, 1.6)), .9, ".", 3.0),
                                            ("Sweden", 1.5, "-", .95, ".", 3.4),
                                            ("Norway", 1.5, "-", .95, ".", 3.4),
                                            ("Finland", 2.6, "-", 1.0, "o", 3.6)]:
            ax.plot(g.year_mid, g[f"surv_{ctry}"], ls=ls, lw=lw, color=COL[ctry],
                    alpha=alpha, marker=mk, ms=ms, zorder=3)
        ax.plot(g.year_mid, g.benchmark_SE_NO_mean, ls=(0, (5, 2)), lw=1.6,
                color=COL["SE/NO mean"], zorder=4)
        ax.set_title(f"{sex}s", loc="left")
        ax.set_xlabel("Period of diagnosis (mid-year)")
        ax.margins(.05)
    axes[0].set_ylabel("5-year relative survival (%)")
    ymax = max(np.nanmax(sub[[f"surv_{c}" for c in COL if c != 'SE/NO mean']].values) * 1.12, 5)
    for ax in axes[:2]:
        ax.set_ylim(0, ymax)
    axes[1].set_yticklabels([])

    ax = axes[2]
    ax.axhline(0, color=COL["SE/NO mean"], lw=1.1, ls=(0, (5, 2)), zorder=1)
    for sex, mk, ls in [("Male", "o", "-"), ("Female", "s", (0, (4, 1.5)))]:
        g = sub[sub.sex == sex].sort_values("year_mid").dropna(subset=["gap_FI_minus_benchmark"])
        ax.fill_between(g.year_mid, g.gap_lowCI, g.gap_upCI, color=COL["Finland"], alpha=.12, lw=0)
        ax.plot(g.year_mid, g.gap_FI_minus_benchmark, ls=ls, lw=2.0, marker=mk, ms=4,
                color=COL["Finland"], label=sex, zorder=3)
    ax.set_title("Finland minus Sweden/Norway mean", loc="left")
    ax.set_xlabel("Period of diagnosis (mid-year)")
    ax.set_ylabel("Gap (percentage points)")
    ax.legend(frameon=False, loc="best")
    ax.margins(.08)

    g = sub[sub.sex == "Male"].sort_values("year_mid")
    hand = [mpl.lines.Line2D([], [], color=COL[k], lw=lw, ls=ls, label=k) for k, lw, ls in
            [("Finland", 2.6, "-"), ("Sweden", 1.5, "-"), ("Norway", 1.5, "-"),
             ("SE/NO mean", 1.6, (0, (5, 2))), ("Denmark", 1.2, (0, (1, 1.6)))]]
    axes[0].legend(handles=hand, frameon=False, loc="upper left", ncol=1,
                   handlelength=1.8, borderaxespad=0.2)
    for a, L in zip(axes, "abc"):
        panel_letter(a, L)
        set_frame(a, "lb")
    fig.suptitle(f"{cancer} cancer: 5-year relative survival, Nordic countries, 1990-2024",
                 x=0.005, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(fname, dpi=300)
    return fig

payloads, manifest = get_payloads()
df = tidy(payloads)
tab = build_table(df)
make_figure(tab, "Lung", "nordcan_lung.png")