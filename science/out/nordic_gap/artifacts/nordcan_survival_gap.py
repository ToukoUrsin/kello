"""Finland vs Sweden/Norway mean: 5-year relative survival, lung/pancreas/liver, NORDCAN API.
Usage: python nordcan_survival_gap.py            (fetch live, save raw JSON to raw/)
       python nordcan_survival_gap.py --offline  (re-run from raw/ JSON)
"""
import sys, os, json, requests, numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

URL = ("https://canapi.iarc.who.int/api/nordcan/v2/961/survival/population/5/{sex}/"
       "246_752_578_208/{c}/?&surv_period=5&age_surv=0&year_start={ys}&year_end={ye}")
YS, YE = 1973, 2024          # fetch full span; 1990+ used for trends, earlier only for lag search
TREND_START = 1990
CANCERS = {160: "Lung", 130: "Pancreas", 110: "Liver"}
SEXES = {1: "Men", 2: "Women"}
CTRY = {246: "Finland", 752: "Sweden", 578: "Norway", 208: "Denmark"}
OFFLINE = "--offline" in sys.argv
os.makedirs("raw", exist_ok=True)

# ---------- 1. fetch / load ----------
rows, log = [], []
for c in CANCERS:
    for s in SEXES:
        fn = f"raw/nordcan_surv5_cancer{c}_sex{s}_{YS}_{YE}.json"
        url = URL.format(sex=s, c=c, ys=YS, ye=YE)
        if OFFLINE:
            j = json.load(open(fn))
        else:
            r = requests.get(url, timeout=60); r.raise_for_status(); j = r.json()
            j["_request_url"] = url
            json.dump(j, open(fn, "w"), indent=1)
        log.append((c, s, len(j.get("dataset", [])), j.get("error")))
        for d in j["dataset"]:
            v = d["survival"]
            rows.append(dict(cancer=CANCERS[c], sex=SEXES[s], country=CTRY[d["country"]],
                             period=d["period"], mid=float(d["year"]),
                             rs=float(v["value"]) if v["value"] not in (None, "") else np.nan,
                             lo=float(v["lowCI"]) if v["lowCI"] not in (None, "") else np.nan,
                             hi=float(v["upCI"]) if v["upCI"] not in (None, "") else np.nan))
for l in log: print("cancer %s sex %s: %d rows, error=%s" % l)
df = pd.DataFrame(rows)
df.to_csv("nordcan_surv5_long.csv", index=False)

# missing-cell report for the trend window
tw = df[df.mid >= TREND_START]
grid = pd.MultiIndex.from_product([CANCERS.values(), SEXES.values(), CTRY.values(),
                                   sorted(tw.period.unique())])
have = set(map(tuple, tw.dropna(subset=["rs"])[["cancer","sex","country","period"]].values))
missing = [g for g in grid if g not in have]
print("Missing cells 1990-2024:", missing if missing else "none")

# ---------- 2. gap metrics ----------
def se(lo, hi): return (hi - lo) / (2 * 1.96)   # approx SE from (asymmetric) 95% CI

def lag_years(t, ref, target, t_latest):
    """First calendar time at which ref series (linear interp. between period midpoints)
    reached `target`; returns (lag, flag)."""
    o = np.argsort(t); t, ref = np.asarray(t)[o], np.asarray(ref)[o]
    if ref[0] >= target: return np.nan, f"ref already >= target in {int(t[0])} (lag > {t_latest - t[0]:.0f} y)"
    for i in range(1, len(t)):
        if ref[i] >= target:
            tc = t[i-1] + (target - ref[i-1]) / (ref[i] - ref[i-1]) * (t[i] - t[i-1])
            return t_latest - tc, ""
    return 0.0, "Finland at/above reference"

out, series = [], {}
for cn in CANCERS.values():
    for sx in SEXES.values():
        w = df[(df.cancer == cn) & (df.sex == sx)].pivot_table(index="mid", columns="country",
                                                              values=["rs", "lo", "hi"])
        ref = (w["rs"]["Sweden"] + w["rs"]["Norway"]) / 2
        ref_se = np.sqrt(se(w["lo"]["Sweden"], w["hi"]["Sweden"])**2 +
                         se(w["lo"]["Norway"], w["hi"]["Norway"])**2) / 2
        fi = w["rs"]["Finland"]; fi_se = se(w["lo"]["Finland"], w["hi"]["Finland"])
        gap = fi - ref; gap_se = np.sqrt(fi_se**2 + ref_se**2)
        series[(cn, sx)] = (w, ref, gap)
        g = gap[gap.index >= TREND_START].dropna()
        tl = g.index.max()
        slope = np.polyfit(g.index, g.values, 1)[0] * 10
        dec = {int(m): g.get(m, np.nan) for m in [1992.0, 2002.0, 2012.0, 2022.0]}
        lag, flag = lag_years(ref.dropna().index, ref.dropna().values, fi[tl], tl)
        per = df.loc[(df.mid == tl), "period"].iloc[0]
        out.append(dict(
            cancer=cn, sex=sx, latest_period=per,
            finland_rs=fi[tl], sweden_rs=w["rs"]["Sweden"][tl], norway_rs=w["rs"]["Norway"][tl],
            denmark_rs=w["rs"]["Denmark"][tl], se_no_mean_rs=round(ref[tl], 2),
            gap_pp=round(gap[tl], 2),
            gap_pp_95ci_lo=round(gap[tl] - 1.96*gap_se[tl], 1), gap_pp_95ci_hi=round(gap[tl] + 1.96*gap_se[tl], 1),
            finland_pct_of_ref=round(100 * fi[tl] / ref[tl], 1),
            gap_1990_94=round(dec[1992], 2), gap_2000_04=round(dec[2002], 2),
            gap_2010_14=round(dec[2012], 2), gap_2020_24=round(dec[2022], 2),
            gap_change_1990s_to_2000s=round(dec[2002]-dec[1992], 2),
            gap_change_2000s_to_2010s=round(dec[2012]-dec[2002], 2),
            gap_change_2010s_to_2020s=round(dec[2022]-dec[2012], 2),
            gap_trend_pp_per_decade_OLS=round(slope, 2),
            finland_change_1990_94_to_2020_24=round(fi[tl] - fi[1992.0], 1),
            ref_change_1990_94_to_2020_24=round(ref[tl] - ref[1992.0], 2),
            lag_years=round(lag, 1) if np.isfinite(lag) else np.nan, lag_note=flag))
res = pd.DataFrame(out)
res.to_csv("nordcan_finland_gap_results.csv", index=False)
print(res.to_string())

# ---------- 3. figures ----------
try:
    apply_figure_style()  # provided in the interactive environment; plain matplotlib otherwise
except NameError:
    plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
COL = {"Finland": "#0b4f9c", "Sweden": "#e0a100", "Norway": "#b2182b", "Denmark": "#9a9a9a"}
for cn in CANCERS.values():
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3), sharey=True)
    for ax, sx in zip(axes, SEXES.values()):
        w, ref, gap = series[(cn, sx)]
        w = w[w.index >= TREND_START]; ref = ref[ref.index >= TREND_START]
        for ctry in ["Denmark", "Norway", "Sweden", "Finland"]:
            focal = ctry == "Finland"
            ax.fill_between(w.index, w["lo"][ctry], w["hi"][ctry], color=COL[ctry],
                            alpha=0.18 if focal else 0.08, lw=0)
            ax.plot(w.index, w["rs"][ctry], "-o", color=COL[ctry], lw=2.2 if focal else 1.1,
                    ms=3.5 if focal else 2.5, zorder=4 if focal else 2,
                    alpha=1 if focal else (0.55 if ctry == "Denmark" else 0.8))
        ax.plot(ref.index, ref.values, "--", color="black", lw=1.3, zorder=3)
        r = res[(res.cancer == cn) & (res.sex == sx)].iloc[0]
        tl = ref.index.max()
        ax.annotate("", xy=(tl + 1.2, r.finland_rs), xytext=(tl + 1.2, r.se_no_mean_rs),
                    arrowprops=dict(arrowstyle="<->", color="black", lw=0.8))
        lagtxt = f", lag ≈ {r.lag_years:.0f} y" if np.isfinite(r.lag_years) else ""
        ax.text(0.03, 0.97, f"{sx}\n2020–24 gap: {r.gap_pp:+.1f} pp{lagtxt}",
                transform=ax.transAxes, va="top", ha="left")
        ax.set_xticks(w.index); ax.set_xticklabels([p for p in sorted(df.period.unique()) if int(p[:4]) >= TREND_START],
                                                    rotation=45, ha="right")
        ax.set_xlim(TREND_START - 0.5, tl + 2.5)
        ax.set_xlabel("Period of diagnosis")
    axes[0].set_ylabel("5-year relative survival (%)")
    axes[0].set_ylim(bottom=0)
    hs = [plt.Line2D([], [], color=COL[c], lw=2.2 if c == "Finland" else 1.1, marker="o", ms=3) for c in COL]
    hs.append(plt.Line2D([], [], color="black", ls="--", lw=1.3))
    fig.legend(hs, list(COL) + ["Sweden–Norway mean"], loc="upper center", ncol=5, frameon=False,
               bbox_to_anchor=(0.5, 1.0))
    fig.suptitle(f"{cn} cancer: Finland vs the Sweden–Norway mean, age-standardised 5-year relative survival",
                 y=1.07)
    fig.tight_layout()
    fig.savefig(f"fig_{cn.lower()}_survival_gap.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
print("done")
