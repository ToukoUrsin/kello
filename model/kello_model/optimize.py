"""Budget optimiser v3: what closes the gap between diagnosis and curative treatment.

Greedy by benefit per euro on one of three objectives (`curative`, `deaths`, `gap`), re-evaluated after every pick.
All numbers come from Model.evaluate(), a deterministic scenario evaluator, so the card, the plan total, the note and
simulate() show the same number for the same set of measures. Each action's numbers are what it adds to the measures
bought before it (marginal, in purchase order): they add up to the plan total, and point and interval are the same
quantity, so a point estimate always lies inside its own interval.
"""
from __future__ import annotations

from . import priors
from .engine import GRID, RANGE_EN, Model, at, span
from .inputs import STEPS

FRONTIER = [100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000]
OBJECTIVES = ("curative", "deaths", "gap")
MID = GRID.index(0.0)
BUDGET_BASIS = ("Budget and costs are per year: running cost plus set-up cost spread over "
                f"{priors.ANNUALISE_YEARS} years.")
HANNA_NOTE = ("The lower bound is below zero and is shown as it is: the lung-specific estimate of how delay affects mortality is not "
              "statistically significant (Hanna et al., BMJ 2020: hazard ratio 1.06 per 4 weeks of delay to lung surgery, 95% CI 0.93-1.19), "
              "so 'no benefit' cannot be ruled out for deaths avoided through days saved.")
OBJECTIVE_EN = {
    "curative": "extra patients a year treated with curative intent",
    "deaths": "deaths avoided a year (within five years, per yearly cohort of patients)",
    "gap": "extra patients a year treated with curative intent, counted only in counties below the national share and only up to it",
}
ZERO = {"curative": 0.0, "deaths": 0.0, "d_delay": 0.0, "d_other": 0.0, "d_curative": 0.0, "days_saved": 0.0}


def _eur(x):
    return f"EUR {x:,.0f}"


class Optimizer:
    def __init__(self, model: Model):
        self.m = model
        self.ecache, self.ccache = {}, {}

    # ------------------------------------------------------------ values
    def ev(self, a, st, t=0.0):
        """Model.evaluate for area index a and a set of measures (cached)."""
        if not st:
            return ZERO
        key = (a, st, t)
        r = self.ecache.get(key)
        if r is None:
            r = self.ecache[key] = self.m.evaluate(a, sorted(st), t)
        return r

    def shortfall(self, a):
        """Patients a year between this county's curative share and the national share (measured; 0 if at or above)."""
        h = self.m.headroom[a]
        return float(h["vs_national_per_year"]) if h else 0.0

    def value(self, a, st, objective, t=0.0):
        e = self.ev(a, st, t)
        if objective == "deaths":
            return e["deaths"]
        if objective == "gap":
            return min(e["curative"], self.shortfall(a))
        return e["curative"]

    def cost(self, j, a):
        c = self.ccache.get((j, a))
        if c is None:
            c = self.ccache[(j, a)] = self.m.cost(j, a)
        return c

    def conf(self, j):
        """Confidence in the effect the plan relies on. For a demand-side measure the evidence file's confidence
        is about the null result alone; its effect when paired with capacity is our assumption, so: low."""
        return "low" if self.m.iv[j]["mechanism"] == "demand" else self.m.iv[j]["confidence"]

    def shortens(self, j):
        iv = self.m.iv[j]
        return iv["metric"] in ("days", "relative_days") and bool(iv["steps_ix"])

    # ------------------------------------------------------------ greedy
    def candidates(self, areas, national_ok, exclude):
        m, out = self.m, []
        for j in m.iv:
            if j in exclude:
                continue
            if m.is_national(j):
                if national_ok:
                    out.append((j, None))
            else:
                out += [(j, a) for a in areas]
        return out

    def greedy(self, areas, budget, objective, national_ok, exclude=frozenset()):
        m = self.m
        state = {a: frozenset() for a in areas}
        spent, picks, done = 0.0, [], set()
        # rule: the recording audit comes first where the care path carries a recording flag
        aud = priors.RECORDING_AUDIT_ID
        if aud in m.iv and aud not in exclude:
            for a in areas:
                c = self.cost(aud, a)[2]
                # under the gap objective a county at or above the national share has no gap for the audit to explain
                if objective == "gap" and self.shortfall(a) <= 0:
                    continue
                if m.flagged[a] and spent + c <= budget + 1e-6:
                    state[a] = state[a] | {aud}
                    spent += c
                    done.add((aud, a))
                    picks.append((aud, a, c, (a,), True))
        cands = self.candidates(areas, national_ok, exclude)
        weight = {j: (priors.LOW_CONFIDENCE_WEIGHT if self.conf(j) == "low" else 1.0) for j in m.iv}
        gcache = {}

        def gain(j, t_):
            key = (j, t_, state[t_])
            g = gcache.get(key)
            if g is None:
                g = gcache[key] = self.value(t_, state[t_] | {j}, objective) - self.value(t_, state[t_], objective)
            return g

        def worth(j, targets, cost):
            """Value-for-money stop rule: central cost per death avoided must not exceed the threshold."""
            d = sum(self.ev(t_, state[t_] | {j})["deaths"] - self.ev(t_, state[t_])["deaths"] for t_ in targets)
            return d > 1e-9 and cost / d <= priors.MAX_EUR_PER_DEATH_AVOIDED

        while True:
            best = None
            for c in cands:
                if c in done:
                    continue
                j, a = c
                cost = self.cost(j, a)[2] or 1.0
                if spent + cost > budget + 1e-6:
                    continue
                targets = tuple(areas) if a is None else (a,)
                req = m.iv[j]["requires"]
                if req and any(r in m.iv and r not in state[t_] for r in req for t_ in targets):
                    continue
                g = sum(gain(j, t_) for t_ in targets)
                if g <= 1e-9 or not worth(j, targets, cost):
                    continue
                score = g / cost * weight[j]
                if best is None or score > best[0]:
                    best = (score, c, cost, targets)
            if best is None:
                break
            _, (j, a), cost, targets = best
            for t_ in targets:
                state[t_] = state[t_] | {j}
            done.add((j, a))
            spent += cost
            picks.append((j, a, cost, targets, False))
        # is there anything left that would add to the objective at any price?
        more = []
        for c in cands:
            if c in done:
                continue
            j, a = c
            targets = tuple(areas) if a is None else (a,)
            req = m.iv[j]["requires"]
            if req and any(r in m.iv and r not in state[t_] for r in req for t_ in targets):
                continue
            if sum(gain(j, t_) for t_ in targets) > 1e-9 and worth(j, targets, self.cost(j, a)[2] or 1.0):
                more.append((self.cost(j, a)[2], j, a))
        return {"state": state, "picks": picks, "spent": spent, "more": sorted(more, key=lambda x: x[0]),
                "value": sum(self.value(a, state[a], objective) for a in areas),
                "curative": sum(self.ev(a, state[a])["curative"] for a in areas),
                "deaths": sum(self.ev(a, state[a])["deaths"] for a in areas)}

    # ------------------------------------------------------------ text
    def explain(self, j, a, cur=None, dth=None, where="In this plan"):
        """One plain sentence with the arithmetic behind a measure's number in area index a (None = whole country).
        `cur` / `dth` are the numbers shown on the card ({median, lo, hi}); when they differ from the measure alone, it says why."""
        m, iv = self.m, self.m.iv[j]
        idx = list(range(m.A)) if a is None else [a]
        n, deaths, pop = float(m.N[idx].sum()), float(m.deaths[idx].sum()), float(m.pop[idx].sum())
        alone = [m.evaluate(i, [j], 0.0) for i in idx]
        a_cur, a_dth = sum(x["curative"] for x in alone), sum(x["deaths"] for x in alone)
        conv = m.conv[0]
        tail = ""
        if iv["metric"] == "curative_share_pp":
            if j == priors.RECORDING_AUDIT_ID:
                return ("Adds no treated patients and avoids no deaths; the model counts zero. It is bought first where 'no treatment on "
                        "record' or recorded drug treatment looks like a recording gap, because until the records are checked the county "
                        "cannot tell a care gap from a coding gap.")
            if a is None:
                s = f"Alone it would add {a_cur:.1f} patients a year treated to cure across the counties where it applies."
            else:
                f, why = m.applicability(j, a)
                raw = m.curative_alone(j, a)
                H = m.reachable(a)
                if H is None:
                    return ("Adds nothing here in the model: this county has no measured shortfall in curative-intent treatment against the "
                            "best quarter of counties (or no care path is published for it).")
                if f <= 0:
                    return f"Adds nothing here in the model: {why}."
                s = (f"Alone: {iv['value']:g} percentage point{'' if iv['value'] == 1 else 's'} x {n:.0f} patients a year"
                     + (f" x {f:.2f} ({why})" if f < 1 else "") + f" = {raw:.1f} extra patients a year treated to cure"
                     + f" (bounds {iv['lo']:g}-{iv['hi']:g} points; an assumption, see the evidence).")
                s += (f" The measures share this county's reachable shortfall of {H['total']:.1f} patients a year (half of the measured "
                      "shortfall to the best quarter of counties), so together they add less than their sum.")
            if cur is not None:
                s += f" {where} it adds {cur['median']:.1f} ({cur['lo']:.1f}-{cur['hi']:.1f})."
                if dth is not None:
                    s += (f" Deaths avoided: {cur['median']:.1f} x {conv:g} deaths within five years per extra patient treated to cure "
                          f"(assumption, range {m.conv[1]:g}-{m.conv[2]:g}; not a causal estimate) = {dth['median']:.2f} a year.")
            return s
        if iv["metric"] == "mortality_rr" and j in priors.SCREENING_BY_PARTICIPANTS:
            part = m.screen_part[0] * pop / 1e5
            c = sum(self.cost(j, i)[2] for i in idx) if a is not None else self.cost(j, None)[2]
            a_dth = round(a_dth, 2)
            s = (f"{part:,.0f} people screened a year ({m.screen_part[0]:g} per 100,000 residents: the same people the cost pays for) x "
                 f"{m.screen_base[0]:g} lung cancer deaths per 1,000 of them a year without screening (NELSON control arm) x "
                 f"(1 - {iv['value']:g}) = {a_dth:.2f} deaths avoided a year, once the programme has run for several years. "
                 f"At {_eur(c)} a year that is about {_eur(c / a_dth) if a_dth > 0 else 'n/a'} per death avoided.")
        elif iv["metric"] == "mortality_rr":
            r = priors.REACH.get(j, (m.reach(j), "default share"))
            s = (f"{deaths:.0f} lung cancer deaths a year x {m.reach(j):.1%} among the patients it reaches (assumption: {r[1]}) x "
                 f"(1 - {iv['value']:g}) = {a_dth:.2f} deaths avoided a year. It does not shorten the pathway.")
        elif iv["metric"] == "stage_shift_pp":
            P = m.P["survival_5y"]
            shift = max(P["early"]["value"] - P["shift_from"]["value"], 0.0)
            s = (f"{n:.0f} patients a year x {iv['value']:g} percentage points more found at stage I (average over the year: the effect "
                 f"fades within months of each campaign; bounds {iv['lo']:g}-{iv['hi']:g}) x {shift:.2f} gain in five-year survival x "
                 f"{priors.STAGE_SHIFT_DISCOUNT:g} (lead-time discount) = {a_dth:.2f} deaths avoided a year.")
        else:
            days = sum(x["days_saved"] * m.N[i] for x, i in zip(alone, idx)) / n
            cs = float((m.cur_point[idx] * m.N[idx]).sum() / n)
            if iv["mechanism"] == "demand" and days < 0.05:
                s = ("Alone: 0 days. It flags patients sooner but adds no capacity, so they wait in the same queue (LungIMPACT 2026 "
                     "found the same).")
            else:
                s = (f"Alone: {days:.1f} days saved per patient (central estimate) for {n:.0f} patients a year, of whom {cs:.0%} are "
                     f"treated with curative intent"
                     + (f"; it reaches about {iv['share_cur']:.0%} of those ({priors.APPLIES[j]['why']}; assumption)" if j in priors.APPLIES else "")
                     + f". Each 28 days sooner divides their mortality hazard by {m.P['hazard_per_4w']['value']:g} (Hanna, BMJ 2020; its "
                     f"interval includes no effect) = {a_dth:.2f} deaths avoided a year."
                     + (" Earlier start of life-prolonging drug treatment is a real benefit the model does not count."
                        if j in priors.APPLIES and iv["share_cur"] < iv["share_all"] else ""))
        if dth is not None and abs(dth["median"] - a_dth) > 0.005:
            tail = (f" {where} it adds {dth['median']:.2f} ({dth['lo']:.2f}-{dth['hi']:.2f}), because measures counted before it "
                    "already cover part of the same effect.")
        return s + tail

    def kpi(self, j, a, cur_mid):
        """The measure's KPI with the county's own baseline from the measured care path and a target with a year."""
        m, k = self.m, self.m.iv[j].get("kpi")
        if not k:
            return None
        out = {"indicator": k.get("indicator"), "label_en": k.get("label_en"), "label_fi": k.get("label_fi"), "baseline": None,
               "target": None, "by_year": k.get("by_year"), "unit": None, "target_rule_en": k.get("target_rule_en"),
               "baseline_kind": None, "target_kind": None}
        st = None
        bf = k.get("baseline_from")
        if a is not None and bf and bf.startswith("care_path."):
            cp = getattr(m, "care_paths", {}).get(m.ids[a]) or {}
            st = next((s for s in cp.get("stages") or [] if s["id"] == bf.split(".", 1)[1]), None)
        typ = (k.get("target") or {}).get("type")
        if st:
            lower = st.get("direction") == "lower_better"
            out.update(baseline=st["value"], unit=st.get("unit"), baseline_kind="measured", baseline_level=st.get("level"),
                       baseline_period=st.get("period"), baseline_source_url=st.get("source_url"))
            if typ == "plus_gain":
                out.update(target=round(st["value"] + 100.0 * cur_mid / float(m.N[a]), 1), target_kind="estimated",
                           target_note_en="Baseline plus what the model expects this measure to add in this plan.")
            elif typ == "national" and st.get("national") is not None:
                better = st["value"] <= st["national"] if lower else st["value"] >= st["national"]
                out.update(target=st["value"] if better else st["national"], target_kind="measured reference",
                           target_note_en=("Already at or better than the national value: hold it." if better else
                                           f"The national value ({st['national']:g})."))
            elif typ == "best" and st.get("best") is not None:
                out.update(target=st["best"], target_kind="measured reference", target_note_en="The best county's value.")
        if typ == "fixed":
            out.update(target=(k["target"] or {}).get("value"), target_kind="assumption")
        if typ == "record":
            out["target_note_en"] = f"No county value is published. The target is to record and publish it by {k.get('by_year')}."
        if out["baseline"] is None:
            out["baseline_note_en"] = ("No baseline: this is not published for the county. The first target is to record it."
                                       if not bf else "No baseline: the registry publishes no value for this area.")
        return out

    def entry(self, j, a, cost, cur, dth, rank=None, days=0.0, forced=False, in_budget=True):
        m, iv = self.m, self.m.iv[j]
        cs = self.cost(j, a)
        if dth["lo"] < 0:
            dth = {**dth, "note_en": HANNA_NOTE}
        e = {"intervention_id": j, "name_en": iv.get("name_en", j), "name_fi": iv.get("name_fi"),
             "area_id": "FI" if a is None else m.ids[a],
             "area_en": "Whole country" if a is None else m.areas[a].get("short_en"),
             "rank": rank, "eur": round(cost), "eur_setup": round(cs[0]), "eur_running_per_year": round(cs[1]),
             "cost_kind": iv["cost"].get("kind", "assumption"),
             "owner_level": iv.get("owner_level"), "owner_en": iv.get("owner_en"), "owner_fi": iv.get("owner_fi"),
             "targets_stage": iv.get("targets_stage"),
             "extra_curative_patients_per_year": cur, "deaths_avoided_per_year": dth,
             "eur_per_extra_curative_patient": round(cost / cur["median"]) if cur["median"] > 0.05 else None,
             "eur_per_death_avoided": round(cost / dth["median"]) if dth["median"] > 0.005 else None,
             "confidence": self.conf(j), "first_step_en": iv.get("first_step_en"), "first_step_fi": iv.get("first_step_fi"),
             "kpi": self.kpi(j, a, cur["median"]),
             "days_saved": round(days, 1), "shortens_pathway": self.shortens(j), "in_budget": in_budget,
             "kind": "estimated", "effect_kind": (iv.get("effect") or {}).get("kind"),
             "note_en": self.explain(j, a, cur, dth)}
        if iv["metric"] == "curative_share_pp" and j != priors.RECORDING_AUDIT_ID:
            e["deaths_basis_en"] = (f"Extra patients treated to cure x {m.conv[0]:g} ({m.conv[1]:g}-{m.conv[2]:g}) deaths within five years "
                                    "avoided per patient. kind: assumption, not a causal estimate.")
            e["deaths_kind"] = "assumption"
        if forced:
            e["why_first_en"] = ("Bought first: this county's care path carries a recording flag, so part of its measured gap may be "
                                 "treatment that was given but not recorded.")
        return e

    def describe(self, picks, areas):
        """Chosen actions with numbers that are marginal in purchase order (they add up to the plan total)."""
        m = self.m
        state = {a: frozenset() for a in areas}
        out = []
        for rank, (j, a, cost, targets, forced) in enumerate(picks, 1):
            before = {x: [self.ev(x, state[x], t) for t in GRID] for x in targets}
            for x in targets:
                state[x] = state[x] | {j}
            after = {x: [self.ev(x, state[x], t) for t in GRID] for x in targets}
            cur = span([sum(after[x][k]["curative"] - before[x][k]["curative"] for x in targets) for k in range(len(GRID))], 2)
            dth = span([sum(after[x][k]["deaths"] - before[x][k]["deaths"] for x in targets) for k in range(len(GRID))], 2)
            nt = sum(m.N[x] for x in targets)
            days = sum((after[x][MID]["days_saved"] - before[x][MID]["days_saved"]) * m.N[x] for x in targets) / nt
            out.append(self.entry(j, a, cost, cur, dth, rank, days, forced))
        return out

    def reasons(self, areas, plan, budget, objective, exclude, scope_en):
        """Why each measure is not in the plan (one row per measure bought nowhere in scope)."""
        m, out = self.m, []
        picked = {p[0] for p in plan["picks"]}
        left = budget - plan["spent"]
        county = len(areas) < m.A
        state = plan["state"]
        for j, iv in m.iv.items():
            if j in picked:
                continue
            nat = m.is_national(j)
            costs = [self.cost(j, None)[2]] if nat else [self.cost(j, a)[2] for a in areas]
            cmin = min(costs)
            gains = [self.value(a, state[a] | {j}, objective) - self.value(a, state[a], objective) for a in areas]
            gain = sum(gains) if nat else max(gains)
            lo = min(sum(self.ev(a, state[a] | {j}, t)["deaths"] - self.ev(a, state[a], t)["deaths"] for a in areas) for t in GRID)
            dg = [self.ev(a, state[a] | {j})["deaths"] - self.ev(a, state[a])["deaths"] for a in areas]
            if nat:
                best_cpd = costs[0] / sum(dg) if sum(dg) > 1e-9 else None
            else:      # the county where it would be the best value
                cpd = [c / d for c, d in zip(costs, dg) if d > 1e-9]
                best_cpd = min(cpd) if cpd else None
            missing = [r for r in iv["requires"] if r in m.iv and not any(r in state[a] for a in areas)]
            access = iv["metric"] == "curative_share_pp"
            if j in exclude:
                code, r = "excluded", "Left out at your request."
            elif nat and county:
                code, r = "national_decision", ("Needs a national decision (Ministry of Social Affairs and Health, Palko): a county cannot "
                                                "start it alone, so it is never bought from a county budget. Its numbers are listed "
                                                "under needs_national_decision.")
            elif access and j == priors.RECORDING_AUDIT_ID and objective == "gap" and any(m.flagged[a] for a in areas) \
                    and all(self.shortfall(a) <= 0 for a in areas if m.flagged[a]):
                code, r = "no_shortfall", ("Under the gap objective the audit is bought only below the national share: there it tells "
                                           "a care gap from a recording gap. " + ("This county is" if county else "The flagged counties are")
                                           + " at or above it.")
            elif access and j == priors.RECORDING_AUDIT_ID:
                code, r = "no_effect", ("Not needed first here: the care path carries no recording flag" + ("" if county else " in any county")
                                        + ". It treats no extra patient.") if not any(m.flagged[a] for a in areas) else \
                    ("budget", f"Budget: it needs {_eur(cmin)} a year.")
            elif access and all(m.reachable(a) is None for a in areas):
                code, r = "no_shortfall", (f"No measured shortfall to close: {scope_en} is at or above the curative share of the best "
                                           "quarter of counties, or no care path is published for it.")
            elif access and all(m.applicability(j, a)[0] <= 0 or m.reachable(a) is None for a in areas):
                why = next((m.applicability(j, a)[1] for a in areas if m.applicability(j, a)[0] <= 0), "it does not apply")
                code, r = "not_applicable", f"Does not apply here: {why}."
            elif access and objective == "gap" and all(self.shortfall(a) <= 0 or m.applicability(j, a)[0] <= 0 for a in areas):
                code, r = "no_shortfall", ("Under the gap objective a patient counts only in a county below the national share; "
                                           "where this measure applies, the county is at or above it.")
            elif access and gain <= 1e-9:
                code, r = "cap", ("Adds nothing more: the measures already bought use up the reachable part of the county's measured shortfall.")
            elif not access and objective in ("curative", "gap"):
                what = "shortens the pathway" if self.shortens(j) else "acts before diagnosis (who gets cancer, or at what stage it is found)"
                code, r = "no_effect", (f"Does not change who gets treated to cure after diagnosis: it {what}. It is counted under the "
                                        "deaths objective.")
            elif gain <= 1e-9:
                code = "no_effect"
                if iv["mechanism"] == "demand":
                    cap = "CT" if any(s <= STEPS.index("diagnosis") for s in iv["steps_ix"]) else STEPS[iv["bottleneck_ix"]]
                    r = (f"No effect without added {cap} capacity: in the LungIMPACT trial (2026) faster AI reads did not shorten "
                         "time to diagnosis. In the model the flagged patient waits in the same queue.")
                else:
                    r = "No effect in the model: the step it targets is already at the best Nordic benchmark, or other measures cover it."
            elif not missing and best_cpd is not None and best_cpd > priors.MAX_EUR_PER_DEATH_AVOIDED:
                code, r = "poor_value", (f"Poor value: added to this plan it would cost about {_eur(best_cpd)} a year per death avoided a "
                                         f"year, above the plan's limit of {_eur(priors.MAX_EUR_PER_DEATH_AVOIDED)} (an assumption; see rules_en).")
            elif missing:
                code, r = "prerequisite", f"Prerequisite missing: {', '.join(m.iv[x].get('name_en', x) for x in missing)} is not in the plan."
            elif cmin > budget:
                code, r = "budget", f"Budget: it costs about {_eur(cmin)} a year, more than the whole budget."
            elif self.conf(j) == "low" and lo <= 0:
                code = "weak_evidence"
                r = (f"Weak evidence: confidence is low and the lower bound of what it adds is {lo:.2f} deaths avoided a year (at or below "
                     "zero), so it ranks at half its modelled value and lost to better-evidenced options.")
            elif cmin > left:
                code, r = "budget", f"Budget: it needs {_eur(cmin)} a year and {_eur(left)} is left after better-value picks."
            else:
                code, r = "budget", "Budget: less benefit per euro than the chosen options, and the money ran out first."
            out.append({"intervention_id": j, "name_en": iv.get("name_en", j), "reason_code": code, "reason_en": r,
                        "confidence": self.conf(j), "owner_level": iv.get("owner_level"),
                        **({"deaths_avoided_lower_bound": round(lo, 2)} if code == "weak_evidence" else {})})
        return out

    def rules(self, objective, exclude, county):
        m = self.m
        k = priors.REACHABLE_SHARE_OF_SHORTFALL
        r = [
            BUDGET_BASIS + " Costs are assumptions unless the action says otherwise.",
            f"Objective '{objective}': the plan maximises {OBJECTIVE_EN[objective]}. The other objectives can be chosen: "
            + "; ".join(f"'{o}' = {OBJECTIVE_EN[o]}" for o in OBJECTIVES if o != objective) + ".",
            "Method: buy the measure that adds most to the objective per euro, re-calculate what every other measure would add, and "
            "repeat until nothing more fits the budget or nothing more adds anything.",
            f"Measures with low-confidence evidence are ranked at {priors.LOW_CONFIDENCE_WEIGHT:g} of their modelled value. They can still "
            "be bought; the numbers shown for them are not halved.",
            "A treatment-access measure adds (its effect in percentage points / 100) x the county's patients a year. Every such effect "
            "is an assumption with a lower bound of zero: no trial has measured it.",
            f"Ceiling: in a county these measures together can add at most {k:.0%} of its measured shortfall to the curative share of the "
            "best quarter of counties, split into a surgery part and a radiotherapy part as on the care path. The rest is left for what "
            "they do not touch (stage at diagnosis, other illness, patient choice); no public table splits the shortfall by reason. "
            "A county at or above the best quarter gets no modelled gain.",
            "Video MDT and the surgeon's second opinion count only where the county's own hospital is not a university hospital "
            "(not in Helsinki, the four Uusimaa counties, Southwest Finland, Pirkanmaa, North Savo, North Ostrobothnia; our reading of "
            "the collaborative-area structure). Travel support is scaled by road distance to the university hospital: 0 at 50 km, full "
            "at 200 km.",
            "Where the care path carries a recording flag ('no treatment on record' far above and life-prolonging treatment far below "
            "the national share, or almost no drug treatment recorded), the recording audit is bought first. It adds no patients.",
            "Measures that need a national decision (low-dose CT screening) are never bought from a county budget. They are listed "
            "under needs_national_decision with their own cost and effect, outside the budget.",
            "Screening is counted from the people screened: participants x their lung cancer death rate without screening x the trial "
            "effect. The cost pays for the same participants.",
            f"Deaths avoided through treatment access = extra patients treated to cure x {m.conv[0]:g} ({m.conv[1]:g}-{m.conv[2]:g}) deaths "
            "within five years avoided per patient. This is an assumption, not a causal estimate (see parameters.json, curative_access).",
            "Deaths avoided through days saved use the published hazard ratio per four weeks of delay (Hanna, BMJ 2020), for patients "
            "treated with curative intent only; its interval includes no effect, so a lower bound can be below zero.",
            f"Overlap: of several pre-diagnosis or mortality measures in one county, the k-th largest counts for {priors.DIMINISHING:g}^k of "
            "itself; two measures on the same pathway step do not add up, and no step goes below the best Nordic benchmark.",
            f"No plan may claim more than {priors.MAX_SHARE_OF_DEATHS:.0%} of an area's lung cancer deaths.",
            f"Stop rule: a measure is not bought if, added to the plan, it costs more than {_eur(priors.MAX_EUR_PER_DEATH_AVOIDED)} a year "
            "per death avoided a year at its central estimate. The limit is our assumption (Finland has no official one; it is roughly "
            "EUR 100,000 per life-year if ten life-years are gained). Such measures are listed as poor_value, and money may be left over.",
            "Each action's numbers are what it adds to the actions ranked before it, so they add up to the plan total. "
            + RANGE_EN,
            "Not counted: a symptom campaign or screening would also raise the share treated to cure by finding cancers earlier; "
            "the model counts them only through deaths avoided. Earlier life-prolonging drug treatment is not counted at all.",
            "No budget share is reserved for any kind of measure (the 25% pathway rule of the earlier version is removed).",
        ]
        if exclude:
            r.append("Left out at your request: " + ", ".join(sorted(exclude)) + ".")
        if not county:
            r.append("National scope: each county-level measure is priced and bought county by county; the counties add up to the total.")
        return r

    # ------------------------------------------------------------ main
    def default_objective(self, scope):
        m = self.m
        if scope == "FI":
            return "gap", None
        a = m.ix[scope]
        name = m.areas[a].get("short_en")
        if m.reachable(a) is None:
            why = ("no care path is published for it" if not m.headroom[a] else
                   "it is at or above the curative share of the best quarter of counties, so there is no measured shortfall to close")
            return "deaths", (f"The default objective for a county is extra patients treated to cure. For {name} {why}; the plan ranks "
                              "measures by deaths avoided instead.")
        return "curative", None

    def optimize(self, scope, budget_eur, objective=None, exclude=None, full_runs=None):
        m = self.m
        note = None
        requested = objective
        if objective in (None, "", "default"):
            objective, note = self.default_objective(scope)
        if objective not in OBJECTIVES:
            raise ValueError("objective must be one of " + ", ".join(OBJECTIVES))
        fi = scope == "FI"
        areas = list(range(m.A)) if fi else [m.ix[scope]]
        scope_en = "Finland" if fi else m.areas[areas[0]].get("short_en")
        exclude = frozenset(j for j in (exclude or []) if j in m.iv)
        budget = max(float(budget_eur), 0.0)
        runs = {b: self.greedy(areas, b, objective, fi, exclude) for b in sorted(set(FRONTIER) | {budget})}
        # a larger budget may always fall back on a smaller budget's plan, so benefit never drops
        best, frontier, plan = None, [], None
        for b in sorted(runs):
            if best is None or runs[b]["value"] > best["value"] + 1e-9:
                best = runs[b]
            if b in FRONTIER:
                frontier.append({"budget_eur": b, "extra_curative_patients_per_year": round(best["curative"], 2),
                                 "deaths_avoided_per_year": round(best["deaths"], 2), "eur_spent": round(best["spent"]),
                                 "saturated": not best["more"], "kind": "estimated"})
            if b == budget:
                plan = best
        chosen = self.describe(plan["picks"], areas)
        st = plan["state"]
        cur = span([sum(self.ev(a, st[a], t)["curative"] for a in areas) for t in GRID], 2)
        dth = span([sum(self.ev(a, st[a], t)["deaths"] for a in areas) for t in GRID], 2)
        if dth["lo"] < 0:
            dth["note_en"] = HANNA_NOTE
        nsum = float(m.N[areas].sum())
        days = sum(self.ev(a, st[a])["days_saved"] * m.N[a] for a in areas) / nsum
        # measured shortfall and share
        short = sum(self.shortfall(a) for a in areas)
        closed = sum(min(self.ev(a, st[a])["curative"], self.shortfall(a)) for a in areas)
        if fi:
            fcp = getattr(m, "care_paths", {}).get("FI") or {}
            now = next((s["value"] for s in fcp.get("stages") or [] if s["id"] == "curative"), None)
        else:
            now = (m.headroom[areas[0]] or {}).get("curative_share_pct")
        after = round(now + 100.0 * cur["median"] / nsum, 1) if now is not None else None
        spent = float(sum(c["eur"] for c in chosen))      # the rounded action costs, so the actions add up to the total
        left = budget - spent
        saturated = not plan["more"]
        if saturated:
            sat = (f"{_eur(spent)} a year buys every measure that adds to this objective in {scope_en}. The remaining {_eur(left)} buys "
                   "nothing more in the model: " + (
                       "the access measures are limited by the reachable part of the measured shortfall, not by money. "
                       if objective != "deaths" else "no remaining measure adds deaths avoided at an acceptable cost. ")
                   + ("To see what else the money could do, choose the deaths objective (pathway measures) or look at the measures "
                      "that need a national decision." if objective != "deaths" else "Measures above the value limit are listed as "
                      "poor_value under not_chosen."))
        else:
            c, j, a = plan["more"][0]
            sat = (f"Not saturated: the cheapest measure that would still add something ({m.iv[j].get('name_en', j)}"
                   + ("" if a is None or not fi else f" in {m.areas[a].get('short_en')}") + f") needs {_eur(c)} a year; {_eur(left)} is left.")
        # measures that need a national decision: outside the budget, with their own numbers at this scope
        chosen_ids = {c["intervention_id"] for c in chosen}
        nnd = []
        for j in m.iv:
            if not m.is_national(j) or j in chosen_ids or j in exclude:
                continue
            c = self.cost(j, None)[2] if fi else self.cost(j, areas[0])[2]
            cu = span([sum(m.evaluate(a, [j], t)["curative"] for a in areas) for t in GRID], 2)
            de = span([sum(m.evaluate(a, [j], t)["deaths"] for a in areas) for t in GRID], 2)
            e = self.entry(j, None if fi else areas[0], c, cu, de, in_budget=False)
            e["standalone"] = True
            e["note_en"] += (" Not counted in this budget. Numbers are for this measure alone in " + scope_en + ".")
            nnd.append(e)
        lung_deaths = float(m.deaths[areas].sum())
        g3 = self.goal3(scope_en, lung_deaths, dth, cur, fi)
        return {
            "scope": scope, "scope_en": scope_en, "budget_eur": budget, "objective": objective,
            "objective_requested": requested, "objective_note_en": note, "objectives_available": list(OBJECTIVES),
            "objective_en": OBJECTIVE_EN[objective], "excluded": sorted(exclude),
            "chosen": chosen,
            "totals": {"eur": round(spent), "eur_left": round(left),
                       "extra_curative_patients_per_year": cur, "deaths_avoided_per_year": dth,
                       "curative_share_now_pct": now, "curative_share_after_pct": after,
                       "shortfall_vs_national_per_year": round(short, 1),
                       "gap_closed_pct": round(100.0 * closed / short, 1) if short > 0 else None,
                       "gap_note_en": ("gap_closed_pct = extra patients treated to cure, counted up to each county's measured shortfall "
                                       "against the national share, divided by that shortfall. Arithmetic on a modelled gain and a "
                                       "measured shortfall; None where the county is at or above the national share."),
                       "eur_per_extra_curative_patient": round(spent / cur["median"]) if cur["median"] > 0.05 else None,
                       "eur_per_death_avoided": round(spent / dth["median"]) if dth["median"] > 0.005 else None,
                       "deaths_basis_en": ("Deaths within five years avoided per yearly cohort of patients; modelled, not observed. "
                                           f"The part from treatment access rests on an assumed {m.conv[0]:g} deaths avoided per extra "
                                           "patient treated to cure."),
                       "days_saved_weighted": round(days, 2 if days < 1 else 1),
                       "days_saved_note_en": ("Secondary: average days saved per patient on the estimated clock (central estimate). "
                                              "Not a headline number; access measures save no days."),
                       "patients_per_year": round(nsum), "kind": "estimated", "interval_en": RANGE_EN,
                       "method_en": (f"Greedy on {OBJECTIVE_EN[objective]} per euro, re-evaluated after every pick. " + BUDGET_BASIS
                                     + " Every number is modelled; treatment-access effects are assumptions with a lower bound of zero.")},
            "needs_national_decision": nnd,
            "not_chosen": self.reasons(areas, plan, budget, objective, exclude, scope_en),
            "rules_en": self.rules(objective, exclude, not fi),
            "saturated": saturated, "saturation_note_en": sat, "saturated_at_eur": round(spent) if saturated else None,
            "goal3_link": g3,
            "frontier": frontier,
            "budget_basis_en": BUDGET_BASIS,
        }

    def goal3(self, scope_en, lung_deaths, dth, cur, fi):
        m = self.m
        raw = m.inp.goal3_raw or {}
        st = {s.get("sex"): s for s in raw.get("survival_targets") or [] if s.get("cancer") == "lung"}
        men, women = st.get("male"), st.get("female")
        mt = raw.get("mortality_trend") or {}
        share = round(100.0 * dth["median"] / lung_deaths, 2) if lung_deaths > 0 else None
        note = (f"Lung cancer causes about {lung_deaths:,.0f} deaths a year in {scope_en} (Finnish Cancer Registry, 2020-2024). This plan "
                f"is modelled to avoid {dth['median']:.1f} of them a year ({dth['lo']:.1f}-{dth['hi']:.1f}), about {share:g}%. ")
        if mt.get("target_pct") is not None:
            note += (f"Goal 3 of the cancer strategy asks for {abs(mt['target_pct']):g}% lower cancer mortality"
                     + (f" (all cancers: from {mt['baseline_deaths_n']:,} deaths in {mt['baseline_year']})" if mt.get("baseline_deaths_n") else "")
                     + ", so a plan of this size is a small part of it. ")
        if men and women:
            note += (f"The strategy also wants lung cancer survival at the level of Sweden and Norway: five-year survival is "
                     f"{abs(men['gap_pp']):.1f} points lower for Finnish men and {abs(women['gap_pp']):.1f} for women ({men.get('period')}, NORDCAN). "
                     "The share of patients treated with curative intent is the part of that gap a county can act on after diagnosis; "
                     f"this plan adds {cur['median']:.1f} such patients a year. ")
        note += "Deaths avoided are modelled from stated assumptions, not observed."
        return {"lung_deaths_per_year": round(lung_deaths, 1), "lung_deaths_kind": "measured",
                "lung_deaths_source_url": getattr(m, "deaths_source_url", None),
                "deaths_avoided_per_year": dth["median"], "deaths_avoided_share_pct": share,
                "survival_gap_pp": abs(men["gap_pp"]) if men else None,
                "survival_gap_pp_by_sex": {"men": abs(men["gap_pp"]) if men else None, "women": abs(women["gap_pp"]) if women else None},
                "survival_gap_interval_men": [abs(men["gap_hi"]), abs(men["gap_lo"])] if men else None,
                "strategy_survival_target_pp": men.get("strategy_target_pp") if men else None,
                "survival_source_url": men.get("source_url") if men else None,
                "mortality_target_pct": mt.get("target_pct"), "strategy_quote_fi": mt.get("strategy_quote_fi"),
                "note_en": note, "kind": "estimated"}
