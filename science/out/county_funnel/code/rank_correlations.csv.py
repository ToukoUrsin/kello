import numpy as np
import pandas as pd
from scipy import stats, special, optimize

META_GREY = "#888888"


def apply_figure_style(*, frame="open", font=None, sizes=(8, 7, 6), grid=False):
    import matplotlib as mpl
    if frame not in ("open", "boxed", "none"):
        raise ValueError(f"frame must be 'open'|'boxed'|'none', got {frame!r}")

    try:
        import os, sys, glob, matplotlib.font_manager as fm
        fdir = os.path.join(os.environ.get("CONDA_PREFIX") or sys.prefix, "fonts")
        if os.path.isdir(fdir):
            known = {f.fname for f in fm.fontManager.ttflist}
            for f in glob.glob(os.path.join(fdir, "*.ttf")):
                if f not in known:
                    fm.fontManager.addfont(f)
    except Exception:
        pass
    base, secondary, tick = sizes
    boxed = (frame == "boxed")
    rc = {
        "font.family": "sans-serif",
        "font.size": base,
        "axes.labelsize": base,
        "axes.titlesize": base,
        "legend.fontsize": secondary,
        "xtick.labelsize": tick,
        "ytick.labelsize": tick,
        "axes.linewidth": 0.6,
        "xtick.direction": "out", "ytick.direction": "out",
        "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "axes.spines.top": boxed, "axes.spines.right": boxed,
        "axes.spines.left": frame != "none", "axes.spines.bottom": frame != "none",
        "axes.grid": bool(grid),
        "legend.frameon": False,
        "figure.dpi": 200,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "axes.titleweight": "normal",
        "axes.titlelocation": "left",
        "axes.labelweight": "normal",
        "lines.linewidth": 1.2,
        "patch.linewidth": 0.6,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    }
    if font:
        rc["font.sans-serif"] = [font, "DejaVu Sans"]
    mpl.rcParams.update(rc)


csv_text = """area_id,county,collaborative_area,lung_patients_2019_2023_n,curative_intent_n,lung_curative_intent_pct,lung_no_treatment_record_pct,lung_cases_5y_n,lung_incidence_per_100k,pop_65plus_pct,daily_smokers_pct,education_level_index,low_income_rate_pct,km_to_university_hospital
01,East Uusimaa,HUS,272.0,77.0,28.3,31.6,272,55.2,24.2,10.7,388.6,9.8,63.7
02,Central Uusimaa,HUS,481.0,162.0,33.7,26.4,481,47.7,21.1,9.3,393.0,9.2,49.6
03,West Uusimaa,HUS,1058.0,337.0,31.9,28.5,1058,44.0,18.8,8.0,460.7,11.2,33.8
04,Vantaa and Kerava,HUS,595.0,212.0,35.6,28.9,595,42.9,16.7,12.5,368.8,13.8,20.6
05,Southwest Finland,TYKS,1437.0,349.0,24.3,43.1,1437,59.4,24.4,10.2,396.9,14.7,27.8
06,Satakunta,TYKS,682.0,167.0,24.5,29.8,682,63.7,29.2,12.5,351.8,14.6,115.4
07,Kanta-Häme,TAYS,546.0,128.0,23.4,32.1,546,64.2,28,10.2,367.8,13.2,84.3
08,Pirkanmaa,TAYS,1253.0,400.0,31.9,17.9,1253,47.4,22.6,7.4,421.9,14.6,33.3
09,Päijät-Häme,HUS,659.0,195.0,29.6,17.8,659,64.2,29,9.9,358.6,16.1,132.7
10,Kymenlaakso,HUS,591.0,114.0,19.3,16.4,591,73.3,31.1,12.0,351.3,15.5,166.1
11,South Karelia,HUS,355.0,67.0,18.9,42.8,355,56.2,29.9,10.1,366.0,17.6,256.8
12,South Savo,KYS,448.0,105.0,23.4,23.2,448,68.0,34.6,7.2,351.2,16.0,163.0
13,North Savo,KYS,641.0,157.0,24.5,19.3,641,51.6,27.8,9.0,383.5,15.4,46.8
14,North Karelia,KYS,510.0,109.0,21.4,22.2,510,62.5,29.8,10.0,371.0,19.0,165.8
15,Central Finland,KYS,637.0,173.0,27.2,24.5,637,46.7,25.4,7.6,398.5,17.3,145.9
16,South Ostrobothnia,TAYS,540.0,165.0,30.6,25.7,540,56.3,27.7,7.6,355.4,13.7,194.7
17,Ostrobothnia,TYKS,449.0,125.0,27.8,22.9,449,50.9,23.7,7.7,388.4,13.1,258.4
18,Central Ostrobothnia,OYS,148.0,33.0,22.3,25.0,148,43.6,25.3,8.7,362.3,12.2,212.1
19,North Ostrobothnia,OYS,1050.0,248.0,23.6,25.0,1050,50.6,21.9,9.5,407.6,14.8,73.0
20,Kainuu,OYS,226.0,47.0,20.8,28.3,226,63.5,31.8,8.9,353.7,15.4,182.9
21,Lapland,OYS,710.0,131.0,18.5,33.8,710,80.5,28.1,11.4,372.0,13.6,250.4
90,Helsinki,HUS,1486.0,491.0,33.0,29.1,1486,44.9,17.7,6.8,486.5,14.1,8.8
91,Åland,ALAND,,,,,,,24.8,6.8,365.1,9.2,170.9
FI,Finland,,14873.0,4009.0,27.0,27.5,14873,53.5,23.8,9.1,403.2,14.2,86.8
"""
open('county_table_input.csv', 'w').write(csv_text)

ALPHA_IN, ALPHA_OUT = 0.05, 0.002
YEARS = 5

raw = pd.read_csv("county_table_input.csv", dtype={"area_id": str})
nat = raw.loc[raw.area_id == "FI"].iloc[0]
cty = raw.loc[raw.area_id != "FI"].copy()

dat = cty.loc[cty.lung_patients_2019_2023_n.notna()].copy()

dat["n"] = dat.lung_patients_2019_2023_n.astype(int)
dat["x"] = dat.curative_intent_n.astype(int)
dat["share_pct"] = 100 * dat.x / dat.n

p0 = nat.curative_intent_n / nat.lung_patients_2019_2023_n

se = np.sqrt(p0 * (1 - p0) / dat.n)
dat["z"] = (dat.x / dat.n - p0) / se

CTX = {"pop_65plus_pct": "Population aged 65+ (%)",
       "daily_smokers_pct": "Daily smokers (%)",
       "education_level_index": "Education level index",
       "km_to_university_hospital": "Distance to university hospital (km)",
       "lung_incidence_per_100k": "Lung cancer incidence per 100 000"}
rows = []
for col, lab in CTX.items():
    sub = dat[["share_pct", col]].dropna()
    r, p = stats.spearmanr(sub.share_pct, sub[col])
    n = len(sub)
    seZ = np.sqrt((1 + r ** 2 / 2) / (n - 3))
    lo, hi = np.tanh(np.arctanh(r) + np.array([-1, 1]) * stats.norm.isf(.025) * seZ)
    rows.append(dict(variable=lab, column=col, n=n, spearman_rho=r,
                     ci_low=lo, ci_high=hi, p_value=p))
corr = pd.DataFrame(rows).sort_values("spearman_rho")

corr.to_csv("rank_correlations.csv", index=False)