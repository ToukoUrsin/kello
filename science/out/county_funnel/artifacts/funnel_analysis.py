"""Funnel-plot analysis of curative-intent treatment share, lung cancer, Finnish
wellbeing services counties, 2019-2023. Input: county_table_input.csv only."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

YEARS = 5  # 2019-2023
d = pd.read_csv("county_table_input.csv", dtype={"area_id": str})
nat = d[d.area_id == "FI"].iloc[0]
cty = d[d.area_id != "FI"].copy()

# ---- 1. County table -------------------------------------------------------
cty["n"] = cty.lung_patients_2019_2023_n
cty["x"] = cty.curative_intent_n
cty["count_source"] = np.where(cty.n.notna() & cty.x.notna(), "registry counts", "")
# fallback: derive from share x case count, only if registry counts missing but both present
need = (cty.n.isna() | cty.x.isna()) & cty.lung_curative_intent_pct.notna() & cty.lung_cases_5y_n.notna()
cty.loc[need, "n"] = cty.loc[need, "lung_cases_5y_n"]
cty.loc[need, "x"] = (cty.loc[need, "lung_curative_intent_pct"] / 100 * cty.loc[need, "n"]).round()
cty.loc[need, "count_source"] = "derived: share x lung_cases_5y_n"
excluded = cty[cty.n.isna() | cty.x.isna()]
use = cty[cty.n.notna() & cty.x.notna()].copy()
use["n"] = use.n.astype(int); use["x"] = use.x.astype(int)
use["share_pct"] = 100 * use.x / use.n
use["published_pct"] = use.lung_curative_intent_pct
use["n_matches_cases_5y"] = use.n == use.lung_cases_5y_n

p0 = nat.curative_intent_n / nat.lung_patients_2019_2023_n   # national row = centre line
k = len(use)

# ---- 2. Limits, z-scores, overdispersion -----------------------------------
def exact_limits(n, p, q):
    """Exact binomial control limit (Spiegelhalter 2005 interpolation), as proportion."""
    n = np.asarray(n, float)
    r = stats.binom.ppf(q, n, p)
    alpha = (stats.binom.cdf(r, n, p) - q) / (stats.binom.cdf(r, n, p) - stats.binom.cdf(r - 1, n, p))
    return (r - alpha) / n

use["z"] = (use.share_pct / 100 - p0) / np.sqrt(p0 * (1 - p0) / use.n)
# exact two-sided binomial p-value vs national share
use["p_exact"] = [stats.binomtest(int(x), int(n), p0).pvalue for x, n in zip(use.x, use.n)]
chi2 = float((use.z ** 2).sum())
p_chi2 = stats.chi2.sf(chi2, k - 1)   # pooled-national ref; k-1 df (conservative)
# Spiegelhalter multiplicative phi with 10% winsorisation of z
zw = use.z.clip(use.z.quantile(0.10), use.z.quantile(0.90))
phi = float((zw ** 2).mean())
p_phi = stats.chi2.sf(k * phi, k)
# additive random-effects tau^2 (DerSimonian-Laird on proportion scale, Spiegelhalter 2012)
s2 = p0 * (1 - p0) / use.n
w = 1 / s2
tau2 = max(0.0, (chi2 - (k - 1)) / (w.sum() - (w ** 2).sum() / w.sum()))
I2 = max(0.0, (chi2 - (k - 1)) / chi2)

overdispersed = p_phi < 0.05
use["z_od"] = use.z / np.sqrt(phi) if overdispersed else use.z
use["z_re"] = (use.share_pct / 100 - p0) / np.sqrt(s2 + tau2)
def cls(z, lim95=1.959964, lim998=3.090232):
    return np.select([z > lim998, z > lim95, z < -lim998, z < -lim95],
                     ["above 99.8%", "above 95%", "below 99.8%", "below 95%"], "within 95%")
use["binomial_flag"] = cls(use.z)
# exact-limit classification (overrides normal approx for the plain binomial flags)
for q, lab in [(0.975, "95%"), (0.999, "99.8%")]:
    lo = exact_limits(use.n, p0, 1 - q); hi = exact_limits(use.n, p0, q)
    use[f"lo_{lab}"] = 100 * lo; use[f"hi_{lab}"] = 100 * hi
def exact_flag(r):
    s = r.share_pct
    if s > r["hi_99.8%"]: return "above 99.8%"
    if s > r["hi_95%"]: return "above 95%"
    if s < r["lo_99.8%"]: return "below 99.8%"
    if s < r["lo_95%"]: return "below 95%"
    return "within 95%"
use["binomial_flag"] = use.apply(exact_flag, axis=1)
use["od_flag"] = cls(use.z_od)
use["re_flag"] = cls(use.z_re)
use["gap_patients_per_year"] = (p0 * use.n - use.x) / YEARS   # positive = fewer than national share

out = use[["area_id", "county", "collaborative_area", "n", "x", "share_pct", "published_pct",
           "count_source", "n_matches_cases_5y", "lo_99.8%", "lo_95%", "hi_95%", "hi_99.8%", "z",
           "p_exact", "binomial_flag", "z_od", "od_flag", "z_re", "re_flag", "gap_patients_per_year"]]
out = out.rename(columns={"n": "patients_2019_2023", "x": "curative_intent_n"})
out.sort_values("share_pct").round({c: 4 for c in out.columns if c != "p_exact"}).to_csv("county_curative_intent_table.csv", index=False)

# ---- 4. Exploratory ecological rank correlations ---------------------------
covs = {"pop_65plus_pct": "Population aged 65+ (%)", "daily_smokers_pct": "Daily smokers (%)",
        "education_level_index": "Education level index", "km_to_university_hospital": "Distance to university hospital (km)",
        "lung_incidence_per_100k": "Lung cancer incidence /100k"}
rng = np.random.default_rng(20261114)
rows = []
for c, lab in covs.items():
    sub = use[[c, "share_pct"]].dropna(); m = len(sub)
    rho, p = stats.spearmanr(sub[c], sub.share_pct)
    se = np.sqrt((1 + rho ** 2 / 2) / (m - 3))       # Bonett-Wright SE for Spearman
    lo, hi = np.tanh(np.arctanh(rho) + np.array([-1, 1]) * 1.959964 * se)
    bs = []
    for _ in range(5000):
        i = rng.integers(0, m, m); bs.append(stats.spearmanr(sub[c].values[i], sub.share_pct.values[i])[0])
    blo, bhi = np.nanpercentile(bs, [2.5, 97.5])
    rows.append(dict(covariate=lab, n_counties=m, spearman_rho=rho, ci95_lo_fisher=lo, ci95_hi_fisher=hi,
                     ci95_lo_boot=blo, ci95_hi_boot=bhi, p_value=p))
cor = pd.DataFrame(rows); cor.round(3).to_csv("ecological_correlations.csv", index=False)

# ---- Funnel plot -----------------------------------------------------------
plt.rcParams.update({"font.size": 13, "axes.spines.top": False, "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(12, 7.5))
nn = np.arange(100, 1701)  # integer n required by binom.ppf
ax.axhline(100 * p0, color="0.2", lw=1.3)
for q, ls, lab in [(0.975, "-", "95% binomial limits"), (0.999, "--", "99.8% binomial limits")]:
    ax.plot(nn, 100 * exact_limits(nn, p0, q), color="#3a6ea5", ls=ls, lw=1.4, label=lab)
    ax.plot(nn, 100 * exact_limits(nn, p0, 1 - q), color="#3a6ea5", ls=ls, lw=1.4)
if overdispersed:
    for zq, ls, lab in [(1.959964, "-", "95% overdispersion-adjusted"), (3.090232, "--", "99.8% overdispersion-adjusted")]:
        h = zq * np.sqrt(phi * p0 * (1 - p0) / nn)
        ax.plot(nn, 100 * (p0 + h), color="#d08c2a", ls=ls, lw=1.6, label=lab)
        ax.plot(nn, 100 * (p0 - h), color="#d08c2a", ls=ls, lw=1.6)
col = {"within 95%": "0.55", "above 95%": "#2a7a3b", "above 99.8%": "#2a7a3b",
       "below 95%": "#b2382f", "below 99.8%": "#b2382f"}
for _, r in use.iterrows():
    ax.scatter(r.n, r.share_pct, s=70, color=col[r.binomial_flag], edgecolor="white", lw=0.8, zorder=3)
offs = {"Helsinki": (-10, 10), "West Uusimaa": (8, 6), "Pirkanmaa": (8, 6), "Vantaa and Kerava": (8, 4),
        "Central Uusimaa": (8, 4), "Kymenlaakso": (-8, 6), "South Karelia": (8, -6), "Lapland": (8, -14),
        "Southwest Finland": (-8, -20), "North Ostrobothnia": (-8, -20), "North Karelia": (8, -10)}
for _, r in use[use.binomial_flag != "within 95%"].iterrows():
    dx, dy = offs.get(r.county, (8, 4))
    ax.annotate(r.county, (r.n, r.share_pct), xytext=(dx, dy), textcoords="offset points",
                fontsize=12, color=col[r.binomial_flag], ha="right" if dx < 0 else "left",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.5), zorder=4)
ax.text(1690, 100 * p0 + 0.3, f"National share {100*p0:.1f}%", ha="right", va="bottom", fontsize=11, color="0.2")
ax.set_xlabel("Lung cancer patients, 2019–2023 (n)")
ax.set_ylabel("Patients with curative-intent treatment (%)")
ax.set_title("Curative-intent treatment varies more between counties than chance predicts", loc="left", fontsize=15)
ax.set_xlim(100, 1700); ax.set_ylim(12, 42)
ax.legend(frameon=False, fontsize=11, loc="upper right", ncol=2)
fig.text(0.01, 0.005, f"22 wellbeing services counties (Åland: no data). Centre line = national share\n"
         f"(4,009/14,873). Overdispersion φ = {phi:.2f} (10% winsorised). Source: Finnish Cancer Registry.",
         fontsize=10, color="0.35")
fig.tight_layout(rect=(0, 0.06, 1, 1))
fig.savefig("funnel_plot_curative_intent.png", dpi=200)

# ---- console summary -------------------------------------------------------
print(f"k={k} p0={p0:.5f} chi2={chi2:.2f} df={k-1} p={p_chi2:.2e} phi={phi:.3f} p_phi={p_phi:.2e} "
      f"tau={np.sqrt(tau2)*100:.2f}pp I2={I2:.2f}")
print("excluded:", list(excluded.county), "| derived:", list(use.county[use.count_source != 'registry counts']))
print("county sums:", use.n.sum(), use.x.sum(), "national:", nat.lung_patients_2019_2023_n, nat.curative_intent_n)
print(out[out.binomial_flag != "within 95%"].sort_values("share_pct")[["county", "patients_2019_2023",
      "curative_intent_n", "share_pct", "p_exact", "binomial_flag", "od_flag", "re_flag", "gap_patients_per_year"]].round(4).to_string())
print(cor.round(3).to_string())
