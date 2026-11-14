"""County pathway estimate + patient-flow simulation. See README.md for the plain-language version."""
from __future__ import annotations

import copy
import zlib

import numpy as np

from . import measured as measured_mod
from . import priors
from .inputs import STEPS, STEP_LABEL, Inputs, load_inputs

SEED = 20261113
Q = (10, 50, 90)  # 80% interval
SIGMA = np.array([priors.SIGMA_PATIENT[s] for s in STEPS])
DELAY_W = np.array([priors.DELAY_WEIGHT[s] for s in STEPS])
QUEUE_IX = {STEPS.index(s): share for s, share in priors.QUEUE_SHARE.items()}
# Scenario grid for every number about patients treated or deaths avoided (v3). t = -1: every effect and assumption at its
# unfavourable bound together; 0: the published / central value; +1: every one at its favourable bound. The point estimate
# is t = 0 and the interval is the lowest and highest value over the grid, so a point always lies inside its interval.
GRID = (-1.0, -0.5, 0.0, 0.5, 1.0)
RANGE_EN = ("Range, not a probability interval: lowest and highest value when every effect size and conversion assumption is moved "
            "together from its lower bound to its upper bound. The point estimate uses the published or central values.")


def at(v, lo, hi, t):
    """Value at scenario t: lo at -1, v at 0, hi at +1, linear in between."""
    return v + t * (hi - v) if t >= 0 else v + t * (v - lo)


def span(vals, nd=2):
    """{median, lo, hi} from values on GRID (median = the central scenario). lo <= median <= hi by construction."""
    mid = vals[GRID.index(0.0)]
    r = lambda x: round(float(x), nd) + 0.0
    return {"median": r(mid), "lo": r(min(vals)), "hi": r(max(vals))}


def tri(u, lo, mode, hi):
    """Inverse CDF of a triangular distribution: bounded, peaked at the published value."""
    lo, hi = min(lo, hi), max(lo, hi)
    mode = min(max(mode, lo), hi)
    if hi - lo < 1e-12:
        return np.full_like(u, mode, dtype=float)
    fc = (mode - lo) / (hi - lo)
    return np.where(u < fc, lo + np.sqrt(u * (hi - lo) * (mode - lo)),
                    hi - np.sqrt((1 - u) * (hi - lo) * (hi - mode)))


def q3(x, nd=1):
    lo, med, hi = np.percentile(x, Q)
    return {"median": round(float(med), nd), "lo": round(float(lo), nd), "hi": round(float(hi), nd)}


def _combine(fracs):
    """Remaining share of a step after several fractional reductions, with diminishing returns:
    the k-th largest reduction counts for DIMINISHING**k of itself."""
    F = -np.sort(-np.stack(fracs), axis=0)
    w = priors.DIMINISHING ** np.arange(F.shape[0])[:, None]
    return np.prod(1.0 - F * w, axis=0)


class Model:
    def __init__(self, inp: Inputs | None = None, n_draws: int = 2000, seed: int = SEED):
        self.inp = inp or load_inputs()
        self.R, self.seed = n_draws, seed
        self.areas = self.inp.areas
        self.ids = [a["id"] for a in self.areas]
        self.ix = {a: i for i, a in enumerate(self.ids)}
        self.A = len(self.ids)
        self.P = copy.deepcopy(self.inp.params)
        self.notes = list(self.inp.notes)
        self._demography()
        self._posterior_scalars()
        self._estimate()
        self._interventions()

    # ------------------------------------------------------------ people
    def _demography(self):
        inp, ids = self.inp, self.ids
        from . import defaults
        pop = np.array([inp.val("pop_total", a) or np.nan for a in ids], float)
        self.pop_kind = "measured"
        if np.isnan(pop).any():
            fallback = np.array([defaults.POP_THOUSANDS.get(a, 100) * 1000.0 for a in ids])
            self.pop_kind = "assumption" if np.isnan(pop).all() else "mixed"
            pop = np.where(np.isnan(pop), fallback, pop)
            self.notes.append("Population: built-in approximate values used where pop_total is missing.")
        self.pop = pop
        def arr(fn):
            return np.array([fn(a) if fn(a) is not None else np.nan for a in ids], float)

        def fill(v):  # an area without a value gets the average rate of the others
            ok = np.isfinite(v)
            return np.where(ok, v, np.nansum(v) / pop[ok].sum() * pop)

        self.N = self.deaths = None
        g3 = lambda metric: arr(lambda a: (inp.g3(metric, a) or {}).get("value"))
        d = g3("deaths_n") / 5.0
        if np.isfinite(d).sum() >= 0.8 * len(ids):
            per = next((r.get("period") for r in (inp.g3("deaths_n", a) for a in ids) if r), "5 years")
            self.deaths, self.deaths_how = fill(d), (f"measured: lung cancer deaths per year, Finnish Cancer Registry statistics, {per}, "
                                                     "five-year count / 5 (goal3.json)")
            self.deaths_source_url = next((r.get("source_url") for r in (inp.g3("deaths_n", a) for a in ids) if r), None)
        else:
            d = arr(lambda a: inp.mean_recent("lung_deaths_n", a, 5))
            if np.isfinite(d).sum() >= 0.8 * len(ids):
                self.deaths, self.deaths_how = fill(d), "measured: lung cancer deaths per year, mean of the last 5 years (lung_deaths_n)"
            self.deaths_source_url = None
        c5 = arr(lambda a: inp.val("lung_cases_5y_n", a))
        if np.isfinite(c5).sum() >= 0.8 * len(ids):
            per = (inp.get("lung_cases_5y_n", ids[int(np.isfinite(c5).argmax())]) or {}).get("period", "5 years")
            c5 = np.where(np.isfinite(c5), c5, g3("cases_n"))   # e.g. Åland: not in the quality report, in the registry statistics
            self.N, self.N_how = fill(c5 / 5.0), (f"measured: new lung cancers per year, mean of {per} (lung_cases_5y_n / 5; "
                                                  "an area missing there takes the registry statistics count for 2020-2024)")
        nat_inc = float(self.P["national"]["incidence"]["value"])
        nat_dth = float(self.P["national"]["deaths"]["value"])
        fi_cases = inp.val("lung_cases_n", "FI")
        if fi_cases:
            nat_inc = fi_cases
        if self.N is None:
            r = arr(lambda a: inp.val("lung_incidence_per_100k", a))
            p65 = arr(lambda a: inp.val("pop_65plus_pct", a))
            if np.isfinite(r).sum() >= 0.8 * len(ids):
                raw = np.where(np.isfinite(r), r, np.nanmean(r)) * pop
                self.N, self.N_how = nat_inc * raw / raw.sum(), "estimated: national incidence shared out by county rate x population"
            elif self.deaths is not None:
                self.N = nat_inc * self.deaths / self.deaths.sum()
                self.N_how = "estimated: national incidence shared out by each area's lung cancer deaths"
            elif np.isfinite(p65).all():
                self.N, self.N_how = nat_inc * pop * p65 / (pop * p65).sum(), "estimated: national incidence shared out by population aged 65+"
            else:
                self.N = nat_inc * pop / pop.sum()
                self.N_how = "estimated: national incidence shared out by population (no incidence, deaths or 65+ data)"
        if self.deaths is None:
            self.deaths = nat_dth * self.N / self.N.sum()
            self.deaths_how = "estimated: national deaths shared out in proportion to incidence"
        self.w = self.N / self.N.sum()

    def _posterior_scalars(self):
        rng = np.random.default_rng([self.seed, 1])
        R, P = self.R, self.P
        u = rng.random((6, R))
        self.hr = tri(u[0], P["hazard_per_4w"]["lo"], P["hazard_per_4w"]["value"], P["hazard_per_4w"]["hi"])
        e, l = P["survival_5y"]["early"], P["survival_5y"]["late"]
        self.S_early = tri(u[1], e["lo"], e["value"], e["hi"])
        self.S_late = tri(u[2], l["lo"], l["value"], l["hi"])
        c5, sf = P["survival_5y"]["curative"], P["survival_5y"]["shift_from"]
        self.S_cur = tri(u[5], c5["lo"], c5["value"], c5["hi"])       # 5-year survival, curative-intent patients
        self.S_from = tri(u[2], sf["lo"], sf["value"], sf["hi"])      # survival without the shift to stage I
        c = P["curative_share"]
        nat_cur = tri(u[3], c["lo"], c["value"], c["hi"])
        self.cur = np.repeat(nat_cur[:, None], self.A, axis=1)
        self.cur_kind = ["national share (no county value)"] * self.A
        for i, a in enumerate(self.ids):
            v = self.inp.val("lung_curative_intent_pct", a)
            if v is not None and 3 < v < 80:
                # county value, with +-20% relative uncertainty (small numbers)
                self.cur[:, i] = np.clip(v / 100 * (0.8 + 0.4 * u[4]), 0.02, 0.8)
                self.cur_kind[i] = "county value (lung_curative_intent_pct)"
        self.cur_point = np.full(self.A, float(c["value"]))     # central value, used by the scenario evaluator
        for i, a in enumerate(self.ids):
            v = self.inp.val("lung_curative_intent_pct", a)
            if v is not None and 3 < v < 80:
                self.cur_point[i] = v / 100.0

    # ------------------------------------------------------------ county pathway estimate
    def _estimate(self):
        rng = np.random.default_rng([self.seed, 2])
        R, A, inp = self.R, self.A, self.inp
        self._measured_step5()
        nat = np.zeros((R, 5))
        for s, name in enumerate(STEPS):
            p = self.P["steps"][name]
            lo, hi = p["lo"], p["hi"]
            if hi - lo < 1e-9:  # no published interval: assume +-20%
                lo, hi = 0.8 * p["value"], 1.2 * p["value"]
            d = tri(rng.random(R), lo, p["value"], hi)
            nat[:, s] = d * p["value"] / np.median(d)    # keep the published value as the median of the draws
        self.nat = nat
        self.nat_med = np.array([self.P["steps"][s]["value"] for s in STEPS], float)

        mult = np.ones((R, A, 5))
        self.drivers = [[[] for _ in STEPS] for _ in range(A)]
        self.coverage_parts = np.zeros((A, 2))  # available, expected
        self.drivers_used = {s: [] for s in STEPS}
        for s, name in enumerate(STEPS):
            logm = np.zeros((R, A))
            for (ind, step, sign, mean, sd, why) in priors.ELASTICITIES:
                if step != name or (name == "treatment" and self.step5):
                    continue   # step 5 is measured: its indicator priors are not used
                rows = [inp.get(ind, a) for a in self.ids]
                x = np.array([r["value"] if r else np.nan for r in rows], float)
                have = np.isfinite(x)
                self.coverage_parts[:, 1] += 1
                if have.sum() < 8 or np.nanstd(x) < 1e-9:
                    continue  # too few areas to standardise: indicator not used, counts as a gap
                self.coverage_parts[:, 0] += have
                self.drivers_used[name].append(ind)
                mu, sdx = np.nanmean(x), np.nanstd(x)
                z = np.clip((x - mu) / sdx, -priors.Z_CLIP, priors.Z_CLIP)
                beta = rng.normal(sign * mean, sd, R)
                # a missing value is not "average": it is unknown, so it is drawn at random
                zfull = np.where(have[None, :], np.nan_to_num(z)[None, :], rng.standard_normal((R, A)))
                logm += beta[:, None] * zfull
                fi = inp.get(ind, "FI")
                natval = fi["value"] if fi else float(np.nansum(np.where(have, x * self.pop, 0)) / self.pop[have].sum())
                for i in range(A):
                    if rows[i]:
                        r = rows[i]
                        self.drivers[i][s].append({
                            "indicator": ind, "label_en": r.get("label_en") or inp.catalog.get(ind, {}).get("label_en", ind),
                            "value": round(r["value"], 2), "national": round(natval, 2),
                            "national_kind": "measured" if fi else "estimated (population-weighted mean of counties)",
                            "unit": r.get("unit", ""), "period": r.get("period"), "source_id": r.get("source_id"),
                            "kind": r.get("kind", "measured"), "note": r.get("note"),
                            "z": round(float(z[i]), 2), "pushes": "longer" if sign * z[i] > 0 else "shorter",
                            "prior_elasticity_per_sd": sign * mean, "rationale_en": why})
            mult[:, :, s] = np.clip(np.exp(logm), priors.MULT_LO, priors.MULT_HI)

        # measured hospital times replace the estimate for the steps they span
        self.measured = np.zeros((A, 5), bool)
        self.measured_info = {}
        fixed = np.full((R, A, 5), np.nan)
        for m in self.P.get("measured_hospital_times", []):
            if m.get("area_id") not in self.ix or not m.get("steps"):
                continue
            i, st = self.ix[m["area_id"]], [STEPS.index(s) for s in m["steps"]]
            share = nat[:, st] / nat[:, st].sum(1, keepdims=True)
            fixed[:, i, st] = m["days"] * share
            self.measured[i, st] = True
            for s in st:
                self.measured_info[(i, s)] = m

        # step 5 (diagnosis -> treatment start) is measured per collaborative area by the Cancer Registry
        if self.step5:
            for i, a in enumerate(self.ids):
                fixed[:, i, 4] = self.step5["areas"][a]["days"]
                # an area with no collaborative-area figure (Åland) runs on the national medians: an assumption, not a measurement
                self.measured[i, 4] = self.step5["areas"][a]["level"] == "collaborative_area"
                self.step5_assumed = getattr(self, "step5_assumed", set()) | ({i} if not self.measured[i, 4] else set())
                self.drivers[i][4] = self.step5["areas"][a]["drivers"]

        # renormalise so the incidence-weighted mean of counties reproduces the national figure
        days = np.where(np.isnan(fixed), mult * nat[:, None, :], fixed)
        free = np.isnan(fixed[0])
        for _ in range(6):
            for s in range(5):
                wf = self.w * free[:, s]
                target = nat[:, s] - (days[:, :, s] * (self.w * ~free[:, s])).sum(1)
                cur = (days[:, :, s] * wf).sum(1)
                scale = np.where(cur > 0, np.maximum(target, 0.2 * nat[:, s]) / np.maximum(cur, 1e-9), 1.0)
                d = days[:, :, s] * scale[:, None]
                d = np.clip(d, priors.MULT_LO * nat[:, s][:, None], priors.MULT_HI * nat[:, s][:, None])
                days[:, :, s] = np.where(free[:, s][None, :], d, days[:, :, s])
        self.days = days                                   # [R, A, 5] county step medians
        self.total = days.sum(2)                           # [R, A]
        self.med_days = np.median(days, axis=0)            # [A, 5] central value per step, used by the scenario evaluator
        self.coverage = np.where(self.coverage_parts[:, 1] > 0, self.coverage_parts[:, 0] / self.coverage_parts[:, 1], 0)

        # floor: a step cannot be improved below the best Nordic benchmark for that step
        best = min((b["days"] for b in self.P["benchmarks"]), default=None)
        fin = self.nat_med.sum()
        ratio = min(1.0, best / fin) if best else 0.45
        self.floor_ratio = np.full(5, ratio)
        self.floor_how = (f"Patient and primary care steps: not below {ratio:.0%} of the national median "
                          f"(best Nordic total {best:g} days / Finnish {fin:g} days).")
        sf = self.P.get("specialist_floor")
        if sf:
            r2 = min(1.0, sf["days"] / sf["fi_days"])
            self.floor_ratio[2:] = r2
            self.floor_how += (f" Referral, diagnosis and treatment steps: not below {r2:.0%} of the national median (best Nordic "
                               f"standard time referral to treatment {sf['days']:g} days, {sf['programme']}, / Finnish {sf['fi_days']:g} days).")
        self.floor = nat * self.floor_ratio[None, :]

    def _measured_step5(self):
        """Replace the national step 5 with the registry's measured figure and make steps 3+4 the residual of the
        reported specialist interval, so the national total stays at the reported figure."""
        P = self.P
        self.step5 = s5 = measured_mod.step5(self.inp, self.areas)
        st = P["steps"]
        self.total_reported = sum(st[k]["value"] for k in STEPS)
        self.specialist_reported = sum(st[k]["value"] for k in STEPS[2:])
        self.residual_how = None
        if not s5:
            self.notes.append("Registry diagnosis-to-treatment medians not found: step 5 stays estimated.")
            return
        n = s5["national"]
        old34 = st["referral"]["value"] + st["diagnosis"]["value"]
        resid = self.specialist_reported - n["value"]
        yle = "unpublished four-city study reported by Yle, 2026; sample size not stated"
        if resid >= 10:
            f = resid / old34
            for k in ("referral", "diagnosis"):
                o = st[k]
                st[k] = {**o, "value": o["value"] * f, "lo": o["lo"] * f, "hi": o["hi"] * f, "kind": "estimated",
                         "source": (f"Residual, not measured: the reported specialist-care interval ({self.specialist_reported:g} days; {yle}) minus "
                                    f"the Cancer Registry's measured diagnosis-to-treatment time ({n['value']:g} days) leaves {resid:.0f} days "
                                    f"for referral to diagnosis; this step gets {o['value'] * f:.1f} of them (split {st['referral']['value']:g}:"
                                    f"{st['diagnosis']['value']:g} between referral and diagnosis is an assumption).")}
            self.residual_how = (f"National total kept at the reported {self.total_reported:g} days ({yle}). Step 5 is the registry's measured "
                                 f"{n['value']:g} days; steps 3 and 4 share the residual {self.specialist_reported:g} - {n['value']:g} = {resid:.0f} days.")
        else:
            self.residual_how = (f"The registry's measured diagnosis-to-treatment time ({n['value']:g} days) leaves under 10 days of the reported "
                                 f"specialist interval ({self.specialist_reported:g} days; {yle}) for referral and diagnosis, which is implausible. "
                                 f"Steps 3 and 4 keep their earlier estimates, so the national total is "
                                 f"{self.total_reported - self.specialist_reported + old34 + n['value']:g} days against the reported {self.total_reported:g}.")
        st["treatment"] = {"value": n["value"], "lo": n["lo"], "hi": n["hi"], "kind": "measured", "measured_level": "national",
                           "url": n["source_url"], "page": n["page"], "read_by": n["read_by"], "period": n["period"],
                           "source": (f"Measured: Finnish Cancer Registry, median days from diagnosis to first treatment for patients treated "
                                      f"within 6 months, {n['period']}: surgery {n['rows']['surgery']['value']:g}, radiotherapy "
                                      f"{n['rows']['radiotherapy']['value']:g}, drug therapy {n['rows']['drug_therapy']['value']:g}; "
                                      f"{n['value']:g} is their mean weighted by the national treatment mix.")}
        self.notes.append(self.residual_how)

    # ------------------------------------------------------------ interventions
    def _interventions(self):
        self.iv, self.eff = {}, {}
        for iv in self.inp.interventions:
            j = iv["id"]
            self.iv[j] = iv
            rng = np.random.default_rng([self.seed, zlib.crc32(j.encode())])
            self.eff[j] = tri(rng.random(self.R), iv["lo"], iv["value"], iv["hi"])
            if iv["mechanism"] == "demand" and j in priors.DEMAND_NOMINAL:
                v, lo, hi = priors.DEMAND_NOMINAL[j]     # effect once slots are free: assumption, see priors.py
                self.eff[j] = tri(rng.random(self.R), lo, v, hi)
                iv["paired_effect_assumption"] = {"metric": "relative_days", "value": v, "lo": lo, "hi": hi, "kind": "assumption"}
            ap = priors.APPLIES.get(j, {})
            iv["share_all"], iv["share_cur"] = ap.get("all", 1.0), ap.get("curative", 1.0)
            iv["steps_ix"] = [STEPS.index(s) for s in iv["steps"]]
            if iv["metric"] == "curative_share_pp":
                iv["steps_ix"] = []
            # a demand-side intervention needs free slots at the next capacity-limited step
            st = iv["steps_ix"]
            iv["bottleneck_ix"] = STEPS.index("referral") if st and max(st) <= STEPS.index("referral") and STEPS.index("referral") in st \
                else STEPS.index("diagnosis")
        self.capacity_ids = {s: [j for j, iv in self.iv.items() if iv["mechanism"] == "capacity" and s in iv["steps_ix"]]
                             for s in QUEUE_IX}
        P = self.P
        ca = (P.get("curative_access") or {}).get("deaths_avoided_per_extra_curative_patient") or {}
        d = priors.DEATHS_PER_EXTRA_CURATIVE
        self.conv = (float(ca.get("value", d[0])), float(ca.get("lo", d[1])), float(ca.get("hi", d[2])))
        self.conv_node = ca
        sc = P.get("screening") or {}
        pp, bb = sc.get("participants_per_100k_residents") or {}, sc.get("baseline_lung_deaths_per_1000_person_years") or {}
        d1, d2 = priors.SCREEN_PARTICIPANTS_PER_100K, priors.SCREEN_BASELINE_DEATHS_PER_1000PY
        self.screen_part = (float(pp.get("value", d1[0])), float(pp.get("lo", d1[1])), float(pp.get("hi", d1[2])))
        self.screen_base = (float(bb.get("value", d2[0])), float(bb.get("lo", d2[1])), float(bb.get("hi", d2[2])))
        self.km = np.array([self.inp.val("km_to_university_hospital", a) or np.nan for a in self.ids], float)
        self.headroom = [None] * self.A        # set by set_care_paths(): measured shortfall per county
        self.flagged = [False] * self.A

    # ------------------------------------------------------------ v3: who gets treated to cure
    def set_care_paths(self, paths):
        """Attach the measured care path: each county's shortfall in curative-intent patients (the ceiling for any
        modelled gain) and whether its record carries a recording flag."""
        self.care_paths = paths
        for i, a in enumerate(self.ids):
            cp = paths.get(a) or {}
            self.headroom[i] = cp.get("headroom")
            self.flagged[i] = any(f.get("stage_id") in priors.RECORDING_FLAG_STAGES and f.get("strength") != "note"
                                  for f in cp.get("artefact_flags") or [])

    def applicability(self, j, area_i):
        """Share of a curative-access measure's effect that applies in this county (0-1) and why."""
        if j in priors.NEEDS_REMOTE_UNIVERSITY_TEAM and self.ids[area_i] in priors.UNIVERSITY_SERVED:
            return 0.0, "the county's own hospital is the university hospital, so its team already decides"
        if j in priors.DISTANCE_SCALED:
            lo, hi = priors.DISTANCE_SCALED[j]
            km = self.km[area_i]
            if not np.isfinite(km):
                return 0.0, "distance to the university hospital is not known"
            f = float(np.clip((km - lo) / (hi - lo), 0.0, 1.0))
            return f, f"{km:.0f} km to the university hospital (scaled 0 at {lo:g} km, full at {hi:g} km)"
        return 1.0, None

    def effect_at(self, j, t):
        """Effect of measure j at scenario t (see GRID)."""
        iv = self.iv[j]
        v, lo, hi = iv["value"], iv["lo"], iv["hi"]
        if iv["mechanism"] == "demand" and j in priors.DEMAND_NOMINAL:
            v, lo, hi = priors.DEMAND_NOMINAL[j]
        if iv["metric"] == "mortality_rr":      # a lower rate ratio is the favourable end
            lo, hi = hi, lo
        return at(v, lo, hi, t)

    def reachable(self, area_i):
        """Patients a year the access measures can add at most in this county: a share of the measured shortfall to the
        best quarter of counties, split into a surgery part and a radiotherapy part. None = no shortfall or no data."""
        h = self.headroom[area_i]
        if not h or not h.get("total_per_year") or h["total_per_year"] <= 0:
            return None
        k = priors.REACHABLE_SHARE_OF_SHORTFALL
        return {"total": k * h["total_per_year"], "surgery": k * h["surgery_per_year"], "radiotherapy": k * h["radiotherapy_per_year"]}

    def curative_gain(self, area_i, ids, t=0.0):
        """Extra patients a year treated with curative intent. Each measure alone adds effect/100 x patients x applicability.
        Together they share the reachable shortfall: a measure reaches its share of the patients still missing, so two
        measures never count the same patient twice and the total never passes the reachable shortfall."""
        H = self.reachable(area_i)
        if H is None:
            return 0.0
        n = self.N[area_i]
        keep = {"surgery": 1.0, "radiotherapy": 1.0, "any": 1.0}
        for j in ids:
            iv = self.iv.get(j)
            if not iv or iv["metric"] != "curative_share_pp":
                continue
            g = max(self.effect_at(j, t), 0.0) / 100.0 * n * self.applicability(j, area_i)[0]
            mod = iv.get("modality") if iv.get("modality") in ("surgery", "radiotherapy") else "any"
            pool = H["total"] if mod == "any" else H[mod]
            keep[mod] *= 1.0 - (min(g / pool, 1.0) if pool > 0 else 0.0)
        gs, gr = H["surgery"] * (1 - keep["surgery"]), H["radiotherapy"] * (1 - keep["radiotherapy"])
        return float(gs + gr + (H["total"] - gs - gr) * (1 - keep["any"]))

    def curative_alone(self, j, area_i, t=0.0):
        """What measure j would add on its own, before the shortfall ceiling."""
        iv = self.iv[j]
        if iv["metric"] != "curative_share_pp":
            return 0.0
        return max(self.effect_at(j, t), 0.0) / 100.0 * self.N[area_i] * self.applicability(j, area_i)[0]

    def screening_deaths(self, j, area_i, t=0.0):
        """Deaths avoided a year by screening = people screened x their lung cancer death rate without screening x (1 - RR).
        The people screened are the same people the cost pays for."""
        pop = self.pop.sum() if area_i is None else self.pop[area_i]
        part = at(*self.screen_part, t) * pop / 1e5
        return float(part * at(*self.screen_base, t) / 1000.0 * np.clip(1 - self.effect_at(j, t), 0, 1))

    def evaluate(self, area_i, ids, t=0.0):
        """One county, one set of measures, one scenario: extra curative-intent patients and deaths avoided a year.
        Deterministic (central step durations), so the same set always gives the same number everywhere it is shown."""
        ids = tuple(j for j in dict.fromkeys(ids) if j in self.iv)
        P = self.P
        med = self.med_days[area_i][None, :]
        eff = {j: np.array([self.effect_at(j, t)]) for j in ids}
        floor = (self.nat_med * self.floor_ratio)[None, :]
        if any(self.iv[j]["metric"] in ("days", "relative_days") and self.iv[j]["steps_ix"] for j in ids):
            rem = self.remaining(ids, med, None, "all", eff=eff, floor=floor)
            rem_cur = self.remaining(ids, med, None, "cur", eff=eff, floor=floor) \
                if any(self.iv[j]["share_all"] != self.iv[j]["share_cur"] for j in ids) else rem
        else:
            rem = rem_cur = np.ones((1, 5))
        w = float(((med * (1 - rem_cur)) @ DELAY_W)[0])
        h = P["hazard_per_4w"]
        hr, S = at(h["value"], h["lo"], h["hi"], t), P["survival_5y"]["curative"]["value"]
        d_delay = float(self.N[area_i] * self.cur_point[area_i] * (S ** (hr ** (-w / 28.0)) - S))
        shift = max(P["survival_5y"]["early"]["value"] - P["survival_5y"]["shift_from"]["value"], 0.0)
        other = []
        for j in ids:
            iv = self.iv[j]
            if iv["metric"] == "stage_shift_pp":
                other.append(self.N[area_i] * max(self.effect_at(j, t), 0.0) / 100 * shift * priors.STAGE_SHIFT_DISCOUNT)
            elif iv["metric"] == "mortality_rr":
                if j in priors.SCREENING_BY_PARTICIPANTS:
                    other.append(self.screening_deaths(j, area_i, t))
                else:
                    other.append(self.deaths[area_i] * self.reach(j, t) * float(np.clip(1 - self.effect_at(j, t), 0, 1)))
        other.sort(reverse=True)
        d_other = float(sum(x * priors.DIMINISHING ** k for k, x in enumerate(other)))
        cur = self.curative_gain(area_i, ids, t)
        d_cur = cur * at(*self.conv, t)
        deaths = min(d_delay + d_other + d_cur, priors.MAX_SHARE_OF_DEATHS * self.deaths[area_i])
        return {"curative": cur, "deaths": float(deaths), "d_delay": d_delay, "d_other": d_other, "d_curative": d_cur,
                "days_saved": float((med * (1 - rem)).sum())}

    def cost(self, j, area_i):
        """(setup EUR, running EUR/year, annualised EUR/year) for intervention j in area index area_i (None = whole country)."""
        c = self.iv[j]["cost"]
        sw = c["scales_with"]
        idx = range(self.A) if area_i is None else [area_i]
        if sw == "per_100k_pop":
            k = sum(self.pop[i] for i in idx) / 1e5
        elif sw == "per_patient":
            k = sum(self.N[i] for i in idx)
        elif sw == "national":
            k = 1.0
        else:
            k = float(len(list(idx)))
        # running cost scales as stated; set-up is a fixed one-off per county (per the cost basis texts)
        setup, run = c["eur_setup"] * (1.0 if sw == "national" else float(len(list(idx)))), c["eur_per_year"] * k
        return setup, run, setup / priors.ANNUALISE_YEARS + run

    def reach(self, j, t=0.0):
        r = priors.REACH.get(j)
        if not r:
            return float(self.iv[j].get("effect", {}).get("reach") or priors.MORTALITY_RR_REACH)
        return float(at(r[0], r[2], r[3], t)) if len(r) >= 4 else float(r[0])

    def is_national(self, j):
        """True if a county cannot decide this measure alone: it is never bought from a county budget."""
        iv = self.iv[j]
        return iv.get("owner_level") == "national" or iv["cost"]["scales_with"] == "national" or iv.get("level") == "national"

    def remaining(self, ids, med, idx, who="all", eff=None, floor=None):
        """Share of each step's duration left after the interventions. [R, 5].
        who="all": average patient; who="cur": patients treated with curative intent."""
        R = med.shape[0]
        per_step = {s: [] for s in range(5)}
        for j in ids:
            iv = self.iv[j]
            st = iv["steps_ix"]
            if iv["metric"] not in ("days", "relative_days") or not st:
                continue
            e = eff[j] if eff is not None else self.eff[j][idx]
            if iv["metric"] == "days":   # days are shared over the steps the intervention spans
                f = e / med[:, st].sum(1)
            else:
                f = e
            f = np.clip(f, -0.3, 0.9)
            for s in st:
                per_step[s].append((iv["mechanism"], f, iv["bottleneck_ix"], iv["share_all"] if who == "all" else iv["share_cur"]))
        # queue: how much of the standing backlog do the capacity interventions clear?
        unlock = np.zeros((R, 5))
        for s, share in QUEUE_IX.items():
            caps = [np.clip(f, 0, None) for mech, f, _, _ in per_step[s] if mech == "capacity"]
            if caps:
                unlock[:, s] = np.minimum(1 - _combine(caps), share) / share
        rem = np.ones((R, 5))
        for s in range(5):
            F = []
            for mech, f, b, reach in per_step[s]:
                if mech == "demand":      # earlier flagging only helps once slots are free
                    f = f * unlock[:, b]
                elif mech == "capacity" and s in QUEUE_IX:   # capacity cannot remove handling time
                    f = np.minimum(f, QUEUE_IX[s])
                F.append(f * reach)
            if F:
                comb = _combine(F)
                fl = np.minimum((self.floor[idx, s] if floor is None else floor[:, s]) / med[:, s], 1.0)
                rem[:, s] = np.where(comb < 1, np.maximum(comb, fl), comb)
        return rem

    def run(self, area_i, ids, n_runs=None, n_pat=None, seed=None, fast=False):
        """Simulate one area's annual cohort with and without the interventions (same random patients)."""
        ids = tuple(sorted(set(j for j in ids if j in self.iv)))
        seed = self.seed if seed is None else int(seed)
        R = min(n_runs or self.R, self.R)
        idx = np.arange(R) if seed == self.seed else np.random.default_rng([seed, 7]).choice(self.R, R, replace=False)
        med = self.days[idx, area_i, :]
        if fast:    # optimiser ranking: one median patient per run instead of a cohort
            P, D = 1, med[:, None, :]
        else:
            P = n_pat or int(min(max(self.N[area_i], 30), 150))
            rng = np.random.default_rng([seed, 11, area_i])
            D = med[:, None, :] * np.exp(SIGMA * rng.standard_normal((R, P, 5)))   # patient step durations
        rem = self.remaining(ids, med, idx)
        partial = any(self.iv[j]["share_all"] != self.iv[j]["share_cur"] for j in ids)
        rem_cur = self.remaining(ids, med, idx, "cur") if partial else rem
        saved = D * (1 - rem[:, None, :])
        w = (D * (1 - rem_cur[:, None, :])) @ DELAY_W
        hr, S = self.hr[idx][:, None], self.S_cur[idx][:, None]
        gain = S ** (hr ** (-w / 28.0)) - S                 # survival gain of a curative-intent patient
        d_delay = self.N[area_i] * self.cur[idx, area_i] * gain.mean(1)
        other = []
        for j in ids:
            iv, e = self.iv[j], self.eff[j][idx]
            if iv["metric"] == "stage_shift_pp":
                other.append(self.N[area_i] * np.abs(e) / 100 * np.clip(self.S_early[idx] - self.S_from[idx], 0, None) * priors.STAGE_SHIFT_DISCOUNT)
            elif iv["metric"] == "mortality_rr":
                if j in priors.SCREENING_BY_PARTICIPANTS:
                    other.append(self.pop[area_i] / 1e5 * self.screen_part[0] * self.screen_base[0] / 1000.0 * np.clip(1 - e, 0, 1))
                else:
                    other.append(self.deaths[area_i] * self.reach(j) * np.clip(1 - e, 0, 1))
        d_other = 0.0
        if other:
            O = -np.sort(-np.stack(other), axis=0)
            d_other = (O * (priors.DIMINISHING ** np.arange(O.shape[0]))[:, None]).sum(0)
        deaths = np.minimum(d_delay + d_other, priors.MAX_SHARE_OF_DEATHS * self.deaths[area_i])
        return {"idx": idx, "med": med, "scen": med * rem, "days_saved": (med * (1 - rem)).sum(1),
                "deaths": deaths, "d_delay": d_delay, "d_other": np.broadcast_to(d_other, deaths.shape),
                "n_runs": R, "n_pat": P, "mean_days_saved_pat": saved.sum(2).mean(1)}

    # ------------------------------------------------------------ text
    def step_method(self, area_i, s):
        name = STEPS[s]
        p = self.P["steps"][name]
        if s == 4 and self.step5:
            a = self.step5["areas"][self.ids[area_i]]
            r, mix = a["rows"], a["mix"]
            where = (f"the {measured_mod.YTA_EN.get(a['yta'], a['yta'])} collaborative area" if a["level"] == "collaborative_area"
                     else "Finland as a whole")
            if a["level"] != "collaborative_area":
                return ("Not measured for this area: the registry publishes no diagnosis-to-treatment time for it. The national medians "
                        f"(surgery {r['surgery']['value']:g}, radiotherapy {r['radiotherapy']['value']:g}, drug therapy "
                        f"{r['drug_therapy']['value']:g} days, {measured_mod.DELAY_PERIOD}) are used as an assumption so that the clock has "
                        "a value; it says nothing about this area.")
            return (f"Measured for the collaborative area, not the county: Finnish Cancer Registry median days from diagnosis to first treatment in {where}, "
                    f"{measured_mod.DELAY_PERIOD} (patients treated within 6 months): surgery {r['surgery']['value']:g}, radiotherapy "
                    f"{r['radiotherapy']['value']:g}, drug therapy {r['drug_therapy']['value']:g}. Combined with the {a['mix_level']} treatment "
                    f"mix (surgery {mix['surgery']:g}%, radiotherapy {mix['radiotherapy']:g}%, drug therapy {mix['drug_therapy']:g}% of patients) "
                    f"= {a['days']:g} days. The medians are measured for the collaborative area, not the county; the weighting is arithmetic. "
                    "No interval is published per area." + (" " + a["note"] if a["note"] else ""))
        if self.measured[area_i, s]:
            m = self.measured_info[(area_i, s)]
            span = " + ".join(m["steps"])
            return (f"Measured: {m.get('hospital', 'hospital')} reports {m['days']:g} days for {m.get('what_en', span)} "
                    f"({m.get('period', 'period not stated')}). That interval covers the steps {span}; it is split between them in the "
                    "national proportions (the split is our assumption, the sum is measured).")
        used = [d["indicator"] for d in self.drivers[area_i][s]]
        allk = self.drivers_used[name]
        base = (f"National median for this step ({p['value']:.1f} days; {p.get('kind', 'measured')}) multiplied by a county factor. ")
        if s in (2, 3) and self.residual_how and self.step5:
            base += ("The national figure is a residual (reported specialist interval minus the measured diagnosis-to-treatment time), "
                     "not a measurement. ")
        if not allk:
            return base + ("No county indicator for this step is available yet, so the county factor is 1 and the interval only "
                           "reflects uncertainty in the national figure.")
        return base + (f"The factor is exp(sum of elasticity x standardised indicator) over {len(used)} of {len(allk)} indicators "
                       f"available for this county ({', '.join(used) or 'none'}). The elasticities are assumed priors, not fitted: "
                       "Finland publishes no county-level step durations to fit against. Missing indicators are drawn at random. "
                       f"Factor kept within {priors.MULT_LO}-{priors.MULT_HI} and rescaled so counties average to the national "
                       f"figure. 80% interval from {self.R} Monte Carlo draws.")

    def area_steps(self, area_i):
        out = []
        for s, name in enumerate(STEPS):
            out.append({"id": name, "label_en": STEP_LABEL[name], "days": q3(self.days[:, area_i, s]),
                        "national_days": round(float(self.nat_med[s]), 1),
                        "kind": "measured" if self.measured[area_i, s] else "estimated", "level": "county",
                        "method_en": self.step_method(area_i, s), "drivers": self.drivers[area_i][s]})
            if s == 4 and self.step5:
                a = self.step5["areas"][self.ids[area_i]]
                ok = a["level"] == "collaborative_area"
                out[-1].update(kind="measured" if ok else "assumption", level=a["level"],
                               measured_level=a["level"] if ok else None, collaborative_area=a["yta"] if ok else None,
                               period=measured_mod.DELAY_PERIOD,
                               level_note_en=("The medians are measured for the collaborative area and treatment type; counties in one "
                                              "collaborative area differ only through their treatment mix." if ok else
                                              "No figure is published for this area; the national medians stand in as an assumption."))
        return out

    def worst_step(self, area_i):
        med = np.median(self.days[:, area_i, :], axis=0)
        return STEPS[int(np.argmax(med - self.nat_med))]
