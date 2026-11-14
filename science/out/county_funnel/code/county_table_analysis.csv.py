import numpy as np
import pandas as pd
from scipy import stats, special, optimize

ALPHA_IN, ALPHA_OUT = 0.05, 0.002
YEARS = 5

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


# ---------------------------------------------------------------- 1. county table
raw = pd.read_csv("{{artifact:2034e53c-a3b0-4a7f-87ae-0c251a1eed16}}", dtype={"area_id": str})
nat = raw.loc[raw.area_id == "FI"].iloc[0]
cty = raw.loc[raw.area_id != "FI"].copy()

agree = (cty.lung_cases_5y_n == cty.lung_patients_2019_2023_n)
assert agree[cty.lung_patients_2019_2023_n.notna()].all()

dat = cty.loc[cty.lung_patients_2019_2023_n.notna()].copy()     # 22 counties
excluded = cty.loc[cty.lung_patients_2019_2023_n.isna(), "county"].tolist()

dat["n"] = dat.lung_patients_2019_2023_n.astype(int)
dat["x"] = dat.curative_intent_n.astype(int)
dat["share_pct"] = 100 * dat.x / dat.n

p0 = nat.curative_intent_n / nat.lung_patients_2019_2023_n      # national centre line
n_sum, x_sum = dat.n.sum(), dat.x.sum()

# ---------------------------------------------------------------- 2. per-county tests
se = np.sqrt(p0 * (1 - p0) / dat.n)
dat["z"] = (dat.x / dat.n - p0) / se
dat["p_exact"] = [stats.binomtest(int(x), int(n), p0, alternative="two-sided").pvalue
                  for x, n in zip(dat.x, dat.n)]
ci = np.array([stats.binomtest(int(x), int(n), p0).proportion_ci(method="exact")
               for x, n in zip(dat.x, dat.n)])
dat["share_ci_low_pct"], dat["share_ci_high_pct"] = 100 * ci[:, 0], 100 * ci[:, 1]
rej, q, *_ = __import__("statsmodels.stats.multitest", fromlist=["x"]).multipletests(
    dat.p_exact, alpha=0.05, method="fdr_bh")
dat["p_exact_bh"] = q
# patients per year between the county and the national share (negative = shortfall)
dat["excess_treated_per_year"] = (dat.x - p0 * dat.n) / YEARS

# ---------------------------------------------------------------- 3. overdispersion
K = len(dat)
Q = float((dat.z ** 2).sum())                       # == Pearson chi-square on K-1 df
p_Q = stats.chi2.sf(Q, K - 1)
p_Q_log10 = float(stats.chi2.logsf(Q, K - 1) / np.log(10))

def winsorised_phi(z, frac=0.1):
    lo, hi = np.quantile(z, [frac, 1 - frac])
    return float((np.clip(z, lo, hi) ** 2).mean())

phi_w = winsorised_phi(dat.z.values)
tau2 = max(0.0, (Q - (K - 1)) / (np.sum(1 / se ** 2) - np.sum(1 / se ** 4) / np.sum(1 / se ** 2)))
tau_pct = 100 * np.sqrt(tau2)

# ---------------------------------------------------------------- 4. control limits
def exact_limits(n_grid, p, alpha):
    out = np.empty((len(n_grid), 2))
    for i, n in enumerate(n_grid):
        f = lambda k, targ: special.betainc(n - k, k + 1, 1 - p) - targ
        for j, targ in enumerate((alpha / 2, 1 - alpha / 2)):
            out[i, j] = optimize.brentq(f, 1e-9, n - 1e-9, args=(targ,)) / n
    return out[:, 0], out[:, 1]

infl = np.sqrt(phi_w)                                  # multiplicative inflation
adj = lambda lim: p0 + infl * (lim - p0)               # scale the limit's distance to p0

def band(s, l95, h95, l998, h998):
    if s > h998 or s < l998: return "outside 99.8%"
    if s > h95 or s < l95:   return "outside 95%"
    return "within 95%"

def flag(row):
    nn = row.n
    (l95, h95) = [a[0] for a in exact_limits(np.array([nn]), p0, ALPHA_IN)]
    (l998, h998) = [a[0] for a in exact_limits(np.array([nn]), p0, ALPHA_OUT)]
    s = row.x / nn
    return pd.Series({
        "band_binomial": band(s, l95, h95, l998, h998),
        "band_overdisp_adjusted": band(s, adj(l95), adj(h95), adj(l998), adj(h998)),
        "direction": "above" if s > p0 else "below",
        "lcl95_pct": 100 * l95, "ucl95_pct": 100 * h95,
        "lcl998_pct": 100 * l998, "ucl998_pct": 100 * h998,
        "lcl95_adj_pct": 100 * adj(l95), "ucl95_adj_pct": 100 * adj(h95),
        "lcl998_adj_pct": 100 * adj(l998), "ucl998_adj_pct": 100 * adj(h998)})

dat = pd.concat([dat, dat.apply(flag, axis=1)], axis=1)
dat["outside95_binomial"] = ~dat.band_binomial.eq("within 95%")
dat["outside95_adjusted"] = ~dat.band_overdisp_adjusted.eq("within 95%")

# ---------------------------------------------------------------- 7. outputs
keep = ["area_id", "county", "collaborative_area", "n", "x", "share_pct",
        "share_ci_low_pct", "share_ci_high_pct", "z", "p_exact", "p_exact_bh",
        "band_binomial", "band_overdisp_adjusted", "direction", "outside95_binomial", "outside95_adjusted",
        "excess_treated_per_year", "lcl95_pct", "ucl95_pct", "lcl998_pct", "ucl998_pct",
        "lcl95_adj_pct", "ucl95_adj_pct", "lcl998_adj_pct", "ucl998_adj_pct",
        "lung_no_treatment_record_pct", "lung_incidence_per_100k", "pop_65plus_pct",
        "daily_smokers_pct", "education_level_index", "low_income_rate_pct",
        "km_to_university_hospital"]
out = dat[keep].rename(columns={"n": "patients_n", "x": "curative_intent_n"})
out = out.sort_values("share_pct")
out.to_csv("county_table_analysis.csv", index=False)