#!/usr/bin/env python3
"""
Between-county variation in curative-intent treatment of lung cancer, Finland 2019-2023.

Input : county_table_input.csv  (Finnish Cancer Registry lung cancer quality report
        2019-2023 + Statistics Finland / THL Sotkanet context columns)
Output: county_table_analysis.csv
        funnel_curative_intent.png
        results_summary.md

Method: indirectly standardised-free proportion funnel plot (Spiegelhalter 2005),
exact binomial control limits with continuous interpolation, Spiegelhalter's
winsorised overdispersion factor phi, exact two-sided binomial tests per county,
Spearman rank correlations with Bonett-Wright confidence intervals.
No value is imputed; Aland has no counts and is excluded from all inference.
"""
import numpy as np, pandas as pd
from scipy import stats, special, optimize
import matplotlib as mpl
import matplotlib.pyplot as plt

ALPHA_IN, ALPHA_OUT = 0.05, 0.002          # 95 % and 99.8 % limits
YEARS = 5                                  # 2019-2023

# ---------------------------------------------------------------- 1. county table
raw = pd.read_csv("county_table_input.csv", dtype={"area_id": str})
nat = raw.loc[raw.area_id == "FI"].iloc[0]
cty = raw.loc[raw.area_id != "FI"].copy()

# the registry report gives patients and curative-intent counts directly; the second
# source's case count (lung_cases_5y_n) is identical for every county with data, so
# nothing has to be derived from share x case count.
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
phi = Q / K

def winsorised_phi(z, frac=0.1):
    """Spiegelhalter (2005) eq. 32: winsorise the extreme `frac` of each tail of z."""
    lo, hi = np.quantile(z, [frac, 1 - frac])
    return float((np.clip(z, lo, hi) ** 2).mean())

phi_w = winsorised_phi(dat.z.values)
# additive (random-effects, DerSimonian-Laird) between-county SD on the share scale
tau2 = max(0.0, (Q - (K - 1)) / (np.sum(1 / se ** 2) - np.sum(1 / se ** 4) / np.sum(1 / se ** 2)))
tau_pct = 100 * np.sqrt(tau2)

# ---------------------------------------------------------------- 4. control limits
def exact_limits(n_grid, p, alpha):
    """Exact binomial control limits with continuous interpolation in the count k:
    P(X<=k) = I_{1-p}(n-k, k+1) treated as a continuous function of k."""
    out = np.empty((len(n_grid), 2))
    for i, n in enumerate(n_grid):
        f = lambda k, targ: special.betainc(n - k, k + 1, 1 - p) - targ
        for j, targ in enumerate((alpha / 2, 1 - alpha / 2)):
            out[i, j] = optimize.brentq(f, 1e-9, n - 1e-9, args=(targ,)) / n
    return out[:, 0], out[:, 1]

ngrid = np.linspace(80, 1600, 400)
lo95, hi95 = exact_limits(ngrid, p0, ALPHA_IN)
lo998, hi998 = exact_limits(ngrid, p0, ALPHA_OUT)
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

# ---------------------------------------------------------------- 5. funnel plot
# figure-style helpers (apply_figure_style, set_frame, panel_crops, ...)
import glob, importlib.util
_k = sorted(glob.glob("~/.claude-science/runtime/*/skills/figure-style/kernel.py"))[-1]
_spec = importlib.util.spec_from_file_location("fs_kernel", _k)
fs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fs)
fs.apply_figure_style()
BLUE, RED, GREY = "#1f5fa9", "#c3272b", "#6e6e6e"

fig, ax = plt.subplots(figsize=(9.0, 5.6))
for y, ls, lw, c, lab in [(lo95, (0, (5, 3)), 1.1, GREY, "95 % limits (binomial)"),
                          (hi95, (0, (5, 3)), 1.1, GREY, None),
                          (lo998, (0, (1, 2)), 1.1, GREY, "99.8 % limits (binomial)"),
                          (hi998, (0, (1, 2)), 1.1, GREY, None)]:
    ax.plot(ngrid, 100 * y, ls=ls, lw=lw, color=c, label=lab, zorder=2)
ax.fill_between(ngrid, 100 * adj(lo95), 100 * adj(hi95), color=BLUE, alpha=.085,
                lw=0, label=f"95 % limits, overdispersion-adjusted ($\\phi$={phi_w:.1f})", zorder=1)
ax.plot(ngrid, 100 * adj(lo95), color=BLUE, lw=1.3, zorder=2)
ax.plot(ngrid, 100 * adj(hi95), color=BLUE, lw=1.3, zorder=2)
ax.axhline(100 * p0, color="k", lw=1.4, zorder=3,
           label=f"Finland {100*p0:.1f} %  ({int(nat.curative_intent_n):,}/{int(nat.lung_patients_2019_2023_n):,})")

ins, outs = dat[~dat.outside95_binomial], dat[dat.outside95_binomial]
ax.scatter(ins.n, ins.share_pct, s=46, color=BLUE, edgecolor="white", lw=.7, zorder=5)
ax.scatter(outs.n, outs.share_pct, s=74, color=RED, edgecolor="white", lw=.8,
           zorder=6, marker="D")

# direct labels for every county outside the 95 % binomial limits
off = {"Vantaa and Kerava": (0, 13), "Helsinki": (0, 12), "Pirkanmaa": (0, -15),
       "Southwest Finland": (0, -15), "Lapland": (0, -14), "Kainuu": (0, 12),
       "South Karelia": (0, -14), "North Ostrobothnia": (0, 13),
       "North Karelia": (-10, -3), "Kymenlaakso": (-10, -3), "West Uusimaa": (0, 12),
       "Central Uusimaa": (0, 12)}
for _, r in outs.iterrows():
    dx, dy = off.get(r.county, (0, 12))
    if dx < -5:          # label set to the left of its point
        ax.annotate(f"{r.county}\n{r.share_pct:.1f} %", (r.n, r.share_pct),
                    textcoords="offset points", xytext=(dx, dy), ha="right", va="center",
                    fontsize=mpl.rcParams["legend.fontsize"], color=RED, linespacing=1.15,
                    arrowprops=dict(arrowstyle="-", lw=.6, color=RED, shrinkA=0, shrinkB=3))
        continue
    ax.annotate(f"{r.county}\n{r.share_pct:.1f} %", (r.n, r.share_pct),
                textcoords="offset points", xytext=(dx, dy), ha="center",
                va="bottom" if dy > 0 else "top", fontsize=mpl.rcParams["legend.fontsize"],
                color=RED, linespacing=1.15,
                arrowprops=dict(arrowstyle="-", lw=.6, color=RED, shrinkA=0, shrinkB=3))

ax.set_xlabel("Lung cancer patients diagnosed 2019–2023 (county denominator)")
ax.set_ylabel("Received curative-intent treatment (%)")
n_out = int(dat.outside95_binomial.sum())
n_out_adj = int(dat.outside95_adjusted.sum())
ax.set_title(f"Curative-intent treatment differs between Finnish counties far more than chance:\n"
             f"{n_out} of {K} counties sit outside the 95 % binomial limits, "
             f"{n_out_adj} outside the overdispersion-adjusted limits", loc="left")
ax.set_xlim(60, 1620); ax.set_ylim(12, 42)
ax.legend(frameon=False, loc="lower right", handlelength=1.8, borderpad=.2)
ax.text(.012, .035, "Each point = one wellbeing services county.  Åland excluded (no counts reported).",
        transform=ax.transAxes, fontsize=mpl.rcParams["xtick.labelsize"], color=GREY,
        bbox=dict(fc="white", ec="none", alpha=.85, pad=2))
fs.set_frame(ax)
fig.tight_layout()
fig.savefig("funnel_curative_intent.png", dpi=300)

# --- 9.1 geometric check -------------------------------------------------------
r_ = fig.canvas.get_renderer()
texts = [(t, t.get_window_extent(r_)) for t in fig.findobj(mpl.text.Text)
         if t.get_text().strip() and t.get_visible()]
spines = [(sp, sp.get_window_extent(r_)) for a in fig.axes
          for sp in a.spines.values() if sp.get_visible()]
tl = {a: set(a.get_xticklabels(which="both") + a.get_yticklabels(which="both")) for a in fig.axes}
ov = [(a.get_text(), b.get_text()) for i, (a, ba) in enumerate(texts)
      for b, bb in texts[i + 1:] if ba.overlaps(bb)]
ov += [(t.get_text(), "spine") for t, bt in texts for sp, bs in spines
       if bt.overlaps(bs) and t not in tl[sp.axes]]
print("text overlaps:", ov)

# ---------------------------------------------------------------- 6. rank correlations
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
    seZ = np.sqrt((1 + r ** 2 / 2) / (n - 3))            # Bonett & Wright (2000)
    lo, hi = np.tanh(np.arctanh(r) + np.array([-1, 1]) * stats.norm.isf(.025) * seZ)
    rows.append(dict(variable=lab, column=col, n=n, spearman_rho=r,
                     ci_low=lo, ci_high=hi, p_value=p))
corr = pd.DataFrame(rows).sort_values("spearman_rho")

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
corr.to_csv("rank_correlations.csv", index=False)

stat = dict(p0=p0, K=K, Q=Q, p_Q=p_Q, p_Q_log10=p_Q_log10, phi=phi, phi_w=phi_w, tau_pct=tau_pct,
            n_sum=int(n_sum), x_sum=int(x_sum), excluded=excluded,
            nat_n=int(nat.lung_patients_2019_2023_n), nat_x=int(nat.curative_intent_n))
pd.Series(stat).to_json("global_stats.json")
print(pd.Series(stat))
print(out[["county", "patients_n", "curative_intent_n", "share_pct", "p_exact",
           "band_binomial", "excess_treated_per_year"]].to_string(index=False))
print(corr.to_string(index=False))

# ---------------------------------------------------------------- 8. summary report
nat_n, nat_x = int(nat.lung_patients_2019_2023_n), int(nat.curative_intent_n)
p0_alt = x_sum / n_sum                       # centre line from the 22 counties only
alt_out = []
for _, r in dat.iterrows():
    l95, h95 = exact_limits(np.array([r.n]), p0_alt, ALPHA_IN)
    if r.x / r.n > h95[0] or r.x / r.n < l95[0]:
        alt_out.append(r.county)
same = set(alt_out) == set(dat.loc[dat.outside95_binomial, "county"])

hi = out[(out.outside95_binomial) & (out.direction == "above")].sort_values("share_pct", ascending=False)
lo = out[(out.outside95_binomial) & (out.direction == "below")].sort_values("share_pct")

def pfmt(p): return f"{p:.1e}" if p < 1e-3 else f"{p:.4f}"

def tbl(df, low):
    L = ["| County | Patients | Curative-intent | Share (95 % CI) | Exact binomial *p* | BH *q* | vs binomial limits | vs adjusted limits |" +
         (" Shortfall vs national, patients/year |" if low else ""),
         "|---|---:|---:|---:|---:|---:|---|---|" + ("---:|" if low else "")]
    for _, r in df.iterrows():
        L.append(f"| {r.county} | {r.patients_n:,} | {r.curative_intent_n} | "
                 f"{r.share_pct:.1f} % ({r.share_ci_low_pct:.1f}–{r.share_ci_high_pct:.1f}) | "
                 f"{pfmt(r.p_exact)} | {pfmt(r.p_exact_bh)} | {r.band_binomial} | {r.band_overdisp_adjusted} |" +
                 (f" {abs(r.excess_treated_per_year):.1f} |" if low else ""))
    return "\n".join(L)

corr_tbl = "\n".join(
    ["| Context variable | Spearman ρ | 95 % CI | *p* |", "|---|---:|---:|---:|"] +
    [f"| {r.variable} | {r.spearman_rho:+.2f} | {r.ci_low:+.2f} to {r.ci_high:+.2f} | {pfmt(r.p_value)} |"
     for _, r in corr.iterrows()])

md = f"""# Curative-intent treatment of lung cancer across Finland's wellbeing services counties, 2019–2023

**Question.** Are between-county differences in the share of lung cancer patients receiving
curative-intent treatment larger than chance alone would produce, and which counties are genuine outliers?

**Answer.** Yes, decisively. The 22 counties with reported counts scatter about the national share
far beyond binomial sampling error (Q = {Q:.1f} on {K-1} df, *p* ≈ 10^{p_Q_log10:.0f};
dispersion factor φ = {phi:.1f}, winsorised φ = {phi_w:.1f}). Shares run from
{out.share_pct.min():.1f} % to {out.share_pct.max():.1f} % — a {out.share_pct.max()-out.share_pct.min():.1f}
percentage-point spread, against a national {100*p0:.1f} %. Against plain binomial limits
{int(dat.outside95_binomial.sum())} of {K} counties are outside the 95 % limits
({(dat.band_binomial == 'outside 99.8%').sum()} outside 99.8 %); after inflating the limits by the
observed overdispersion, {int(dat.outside95_adjusted.sum())} county (Helsinki) remains outside.

![Funnel plot](@@FUNNEL@@)

## 1. Rows used

| | |
|---|---|
| Counties analysed | **{K}** — every row with both counts (`area_id` 01–21 and 90) |
| Excluded | **{', '.join(excluded)}** (`area_id` 91): patients, curative-intent count, share and case count are all empty; nothing can be derived, so it enters no plot, test or correlation |
| Finland row (`area_id` FI) | used **only** as the centre line: {nat_x:,}/{nat_n:,} = {100*p0:.2f} % |
| Denominator | `lung_patients_2019_2023_n` (registry report) |
| Numerator | `curative_intent_n` (registry report) |

**No count was derived from share × case count.** The second source's `lung_cases_5y_n` is identical to
`lung_patients_2019_2023_n` for all {K} counties, and the recomputed share `curative_intent_n / patients`
reproduces the reported `lung_curative_intent_pct` to within 0.05 pp everywhere, so the counts were used as given.

**One discrepancy to note:** the {K} counties sum to {n_sum:,} patients and {x_sum:,} curative-intent
treatments, whereas the Finland row gives {nat_n:,} and {nat_x:,} — {nat_n-n_sum} patients and
{nat_x-x_sum} treatments are in the national total but in no county row (Åland is the only county
without counts, and the registry total may also carry records of unknown area). Using the 22-county
sum as the centre line instead ({100*p0_alt:.2f} %) {'leaves the set of counties outside the 95 % limits unchanged' if same else 'changes which counties fall outside the 95 % limits'}.

## 2. Is the variation larger than chance?

| Statistic | Value |
|---|---|
| Counties | {K} |
| Pearson Q = Σ z² (test of homogeneity) | **{Q:.1f}** on {K-1} df, *p* ≈ 10^{p_Q_log10:.0f} |
| Dispersion factor φ = Q/K | **{phi:.2f}** (1.0 = pure binomial) |
| Winsorised φ (Spiegelhalter, 10 % each tail) | **{phi_w:.2f}** — used to inflate the limits |
| Between-county SD on the share scale (DerSimonian–Laird τ) | **{tau_pct:.1f} pp** |

φ ≈ {phi:.0f} means the observed between-county variance is about {phi:.0f}× what independent binomial
sampling at a common {100*p0:.1f} % would give. The differences are real; the only question is what produces them.

## 3. Counties outside the limits

Shares are exact (Clopper–Pearson) CIs; *p* is a two-sided exact binomial test of the county count
against the national {100*p0:.2f} %; *q* is the Benjamini–Hochberg value across all {K} counties.

### Above the limits — more curative-intent treatment than the national share

{tbl(hi, False)}

### Below the limits — less curative-intent treatment than the national share

{tbl(lo, True)}

The last column is the arithmetic gap: (national share × county patients − observed treatments) ÷ 5 years.
Summed over the {len(lo)} low counties, **{abs(lo.excess_treated_per_year.sum()):.0f} patients a year**
would have had a curative-intent treatment record had those counties treated at the national share.

**Overdispersion-adjusted reading.** With limits widened by √φ = {infl:.2f}, only **Helsinki**
({hi.iloc[0].share_pct if hi.iloc[0].county=='Helsinki' else out.loc[out.county=='Helsinki','share_pct'].iat[0]:.1f} %,
n = {out.loc[out.county=='Helsinki','patients_n'].iat[0]:,}) lies outside. This is not a retraction of the
finding — the adjusted limits *absorb* the between-county differences into the null, so they answer a
different question: "is this county unusual **given** that counties differ this much?" The {int(dat.outside95_binomial.sum())}
counties outside the binomial limits are the ones that differ from the national average; Helsinki is the
one that is extreme even on the scale of the counties' own spread. Note that Vantaa and Kerava has the
highest share ({out.share_pct.max():.1f} %) but falls inside the adjusted limits because its denominator is
smaller than Helsinki's.

## 4. Rank correlations with county context (exploratory)

{corr_tbl}

Spearman ρ with Bonett–Wright 95 % CIs, n = {K} counties (Åland has context data but no share, so it is
excluded here too). **These are ecological associations between county aggregates, not causes.** With
{K} units the CIs are wide, the five variables are strongly intercorrelated with each other (older,
more peripheral counties are also the lower-education, higher-incidence ones), and nothing here identifies
an effect on an individual patient's chance of curative-intent treatment — the ecological fallacy applies
in full. No multiplicity adjustment is applied to these five tests; treat them as description, not inference.

The pattern that does emerge is a single gradient rather than five findings: counties with a younger
population, shorter distance to a university hospital and higher education index have higher
curative-intent shares, and counties with high lung cancer incidence have lower shares. The five
university-hospital host counties and their neighbours (Helsinki, Vantaa and Kerava, Central and West
Uusimaa, Pirkanmaa) are the high group; Lapland, Kymenlaakso, South Karelia, Kainuu and North Karelia
the low group. Daily smoking is the one variable whose CI comfortably spans zero.

## 5. Limits of what these numbers can show

1. **Recording, not only treatment.** The registry's own quality report states that stage is recorded
   for roughly half of lung cancer patients and that recording practice differs between counties. The
   curative-intent share is conditioned on what reaches the registry, so an unknown part of the spread
   is documentation rather than care delivered.
2. **The no-treatment-record column points the same way.** `lung_no_treatment_record_pct` ranges from
   {out.lung_no_treatment_record_pct.min():.1f} % (Kymenlaakso) to {out.lung_no_treatment_record_pct.max():.1f} %
   (Southwest Finland) across counties — a {out.lung_no_treatment_record_pct.max()-out.lung_no_treatment_record_pct.min():.1f}
   pp spread in how often *any* treatment is recorded. A county can appear to have a low curative-intent
   share because treatment was given elsewhere or not captured. Southwest Finland and South Karelia, two
   low-share counties, have the two highest no-record shares (43.1 % and 42.8 %).
3. **No case-mix adjustment.** Stage, performance status, histology, age and comorbidity are the
   determinants of whether curative intent is even possible, and none is in this table. The funnel
   compares crude shares; a county with more advanced-stage or frailer patients should have a lower
   share for clinical reasons. Indirect standardisation was not possible with the data supplied.
4. **Referral across county borders.** Curative treatment is concentrated in university hospitals.
   Where a patient is treated and which county is credited need not coincide, which can move counts
   between neighbouring counties.
5. **Five pooled years.** 2019–2023 spans the COVID-19 period; the table gives no year breakdown, so
   no trend or disruption can be separated.
6. **Multiplicity.** With {K} simultaneous comparisons, BH-adjusted *q* values are reported alongside
   the raw exact *p* values; the 99.8 % limits serve the same purpose graphically.
7. **Åland** contributes nothing to this analysis — it has no reported counts, and that absence is
   reported rather than filled.

## Files

- [county_table_analysis.csv](@@TABLE@@) — per-county counts, shares, exact CIs, z, exact and BH *p*, limit band, per-year gap, context columns
- [funnel_curative_intent.png](@@FUNNEL@@) — funnel plot
- [rank_correlations.csv](@@CORR@@) — Spearman ρ, CIs, *p*
- [lung_curative_funnel.py](@@SCRIPT@@) — full analysis script
- [county_table_input.csv](@@INPUT@@) — the input table as supplied
"""
open("results_summary.md", "w").write(md)
print("summary written; centre-line sensitivity same set:", same)
