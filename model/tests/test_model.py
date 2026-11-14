"""pytest -q  (run from model/). Uses whatever inputs are on disk; falls back to defaults."""
import json
import re
import time

import numpy as np
import pytest

from kello_model import api, priors
from kello_model.engine import GRID, Model
from kello_model.inputs import STEPS, load_inputs
from kello_model.optimize import FRONTIER, OBJECTIVES, Optimizer

LAPLAND, KYMENLAAKSO, SOUTHWEST, VANTAA_KERAVA, ALAND = "21", "10", "05", "04", "91"
COUNTIES = [LAPLAND, KYMENLAAKSO, SOUTHWEST, VANTAA_KERAVA, "19", "08", ALAND]
BUDGETS = [100_000, 1_000_000, 5_000_000]
STAGE_IDS = ["staged", "mdt", "curative", "surgery", "radiotherapy", "drug_therapy", "life_prolonging", "symptomatic_only",
             "no_record", "time_to_treatment", "alive_1y"]
REASONS = {"excluded", "national_decision", "no_shortfall", "not_applicable", "no_effect", "prerequisite", "weak_evidence", "budget", "cap", "poor_value"}


@pytest.fixture(scope="module")
def m():
    return api.get_model()


@pytest.fixture(scope="module")
def opt(m):
    return Optimizer(m)


def _demand(m):
    return [j for j, iv in m.iv.items() if iv["mechanism"] == "demand"]


def _inside(x):
    return x["lo"] - 1e-9 <= x["median"] <= x["hi"] + 1e-9


# ---------------------------------------------------------------- the estimated clock (secondary view)
def test_national_mean_reproduces_baseline(m):
    # incidence-weighted mean of county step medians = national step, in every draw
    # (steps 1-4; step 5 is measured per collaborative area and is not rescaled)
    k = 4 if m.step5 else 5
    assert np.allclose((m.days * m.w[None, :, None]).sum(1)[:, :k], m.nat[:, :k], rtol=0.01)
    total = np.median((m.total * m.w[None, :]).sum(1))
    published = sum(m.P["steps"][s]["value"] for s in STEPS)
    assert abs(total - published) / published < 0.03
    assert abs(published - m.total_reported) < 0.5          # national total stays at the reported 155 days


def test_multipliers_within_band(m):
    ratio = m.days / m.nat[:, None, :]
    free = ~m.measured
    free[:, 4] = False            # step 5 is never scaled: measured per collaborative area, national value where none is published
    assert ratio[:, free].min() >= priors.MULT_LO - 1e-6 and ratio[:, free].max() <= priors.MULT_HI + 1e-6


def test_no_step_below_benchmark_floor(m):
    everything = list(m.iv)
    for a in range(m.A):
        r = m.run(a, everything, 300)
        floor = np.minimum(m.floor[r["idx"]], r["med"])
        assert (r["scen"] >= floor - 1e-6).all()


def test_lungimpact_null(m):
    demand = _demand(m)
    assert demand, "no demand-side (AI triage) intervention in the inputs"
    caps = [j for s in m.capacity_ids for j in m.capacity_ids[s] if s == STEPS.index("diagnosis")]
    assert caps
    helped = 0
    for a in range(m.A):
        alone = m.evaluate(a, demand)
        assert abs(alone["days_saved"]) < 1e-9 and abs(alone["deaths"]) < 1e-9
        cap = m.evaluate(a, caps[:1])
        both = m.evaluate(a, caps[:1] + demand)
        assert both["days_saved"] >= cap["days_saved"] > 0     # equal where the step is already at the benchmark floor
        helped += both["days_saved"] > cap["days_saved"] + 1e-9
    assert helped >= m.A // 2


def test_diminishing_returns_not_additive(m):
    ids = [j for j, iv in m.iv.items() if iv["metric"] in ("days", "relative_days") and iv["mechanism"] != "demand"][:4]
    together = m.evaluate(0, ids)["days_saved"]
    apart = sum(m.evaluate(0, [j])["days_saved"] for j in ids)
    assert together < apart
    # access measures share the reachable part of the measured shortfall
    a = m.ix[LAPLAND]
    acc = [j for j, iv in m.iv.items() if iv["metric"] == "curative_share_pp"]
    assert m.evaluate(a, acc)["curative"] < sum(m.evaluate(a, [j])["curative"] for j in acc)
    assert m.evaluate(a, acc, 1.0)["curative"] <= m.reachable(a)["total"] + 1e-9


def test_step5_is_measured_per_collaborative_area(m):
    assert m.step5, "registry diagnosis-to-treatment rows missing"
    assert 36 <= m.P["steps"]["treatment"]["value"] <= 38 and m.P["steps"]["treatment"]["kind"] == "measured"
    assert m.P["steps"]["referral"]["value"] + m.P["steps"]["diagnosis"]["value"] >= 10      # residual stays plausible
    ar = api.area("19")
    st = ar["steps"][4]
    assert st["id"] == "treatment" and st["kind"] == "measured" and st["measured_level"] == "collaborative_area"
    assert st["level"] == "collaborative_area"
    assert st["days"]["lo"] == st["days"]["median"] == st["days"]["hi"]
    assert len(st["drivers"]) == 3 and all(d["source_url"] and d["page"] and d["read_by"] for d in st["drivers"])
    vals = [d["value"] for d in st["drivers"]]
    assert min(vals) - 1e-6 <= st["days"]["median"] <= max(vals) + 1e-6
    assert all(s["kind"] == "estimated" and s["level"] == "county" for s in ar["steps"][:4])
    fi = api.area("FI")["steps"]
    assert fi[4]["kind"] == "measured" and abs(sum(s["days"]["median"] for s in fi) - 155) < 2


def test_step_kinds_are_honest():
    nat = {s["id"]: s for s in api.overview()["national"]["steps"]}
    assert nat["primary"]["kind"] == "reported"            # 41 days is a figure a report states, not a measurement we can open
    assert nat["patient"]["kind"] == "estimated" and nat["treatment"]["kind"] == "measured"
    # Åland has no collaborative-area value: the step is the national value, marked as an assumption, never as measured
    al = api.area(ALAND)
    st = al["steps"][4]
    assert st["kind"] == "assumption" and st["level"] == "national" and st.get("measured_level") != "collaborative_area"
    assert "national" in st["method_en"]
    assert al["measured"]["dx_to_treatment_days"] is None
    assert "Secondary" in al["clock_note_en"]


# ---------------------------------------------------------------- measured care path
def test_care_path_stages_have_source_and_quote(m):
    seen = 0
    for aid in m.ids + ["FI"]:
        cp = api.care_path(aid)
        assert cp["area_id"] == aid and cp["period"]
        ids = [s["id"] for s in cp["stages"]]
        assert ids == [x for x in STAGE_IDS if x in ids]              # contract order, only stages the data has
        for s in cp["stages"]:
            assert s["kind"] in ("measured", "estimated") and s["source_url"].startswith("http") and s["quote"], (aid, s["id"])
            assert s["level"] in ("county", "collaborative_area", "national")
            assert s["direction"] in ("higher_better", "lower_better", "context")
            if aid != "FI":
                assert s["outside_limits"] in ("none", "95", "99.8")
            if s.get("lo") is not None:
                assert s["lo"] <= s["value"] <= s["hi"], (aid, s["id"])
            seen += 1
    assert seen > 150
    assert api.care_path(ALAND)["stages"] == [] and api.care_path(ALAND)["main_leak"] is None     # never filled
    assert api.area(LAPLAND)["care_path"] == api.care_path(LAPLAND)


def test_care_path_leak_and_missing_patients():
    cp = api.care_path(LAPLAND)
    cur = next(s for s in cp["stages"] if s["id"] == "curative")
    assert cur["value"] == 18.5 and cur["n"] == 710 and cur["outside_limits"] == "99.8"
    ml = cp["main_leak"]
    assert ml["stage_id"] == "curative" and "Lapland" in ml["sentence_en"] and ml["sentence_fi"] and ml["patients_per_year"] > 0
    mp = cp["missing_patients"]
    assert mp["vs"] == "national" and mp["lo"] <= mp["per_year"] <= mp["hi"]
    assert abs(sum(x["per_year"] for x in mp["by_modality"]) - mp["per_year"]) < 0.15
    assert abs(mp["per_year"] - cp["patients_per_year"] * (cur["national"] - cur["value"]) / 100) < 0.15
    ex = cp["expected"]
    assert ex["adjusted_for"] and len(ex["not_adjusted_for"]) >= 3 and ex["lo"] <= ex["ratio"] <= ex["hi"]
    assert abs(ex["ratio"] - ex["observed_pct"] / ex["expected_pct"]) < 0.011
    assert "ecological" in ex["method_en"]
    # the best county has no leak to close; a county with a recording gap says so
    vk = api.care_path(VANTAA_KERAVA)
    assert vk["missing_patients"]["per_year"] == 0
    sw = api.care_path(SOUTHWEST)
    assert {f["stage_id"] for f in sw["artefact_flags"]} >= {"no_record"} and all(f["text_en"] and f["text_fi"] for f in sw["artefact_flags"])
    fi = api.care_path("FI")
    assert fi["main_leak"]["sentence_en"] and fi["main_leak"]["sentence_fi"]


def test_measured_blocks():
    ov = api.overview()
    keys = {"curative_intent_pct", "no_treatment_record_pct", "one_year_survival_pct", "surgery_pct", "lung_incidence_per_100k",
            "lung_incidence_asr", "lung_mortality_asr", "gp_wait_over_7d_pct", "pulm_queue_over_90d_pct", "dx_to_treatment_days"}
    hm = ov["national"]["headline_measured"]
    assert hm and all({"key", "value_low", "area_low", "value_high", "area_high", "national", "unit", "period", "source_url"} <= set(h) for h in hm)
    assert ov["headline"]["main_leak"]["sentence_en"] and ov["headline"]["kind"] == "measured"
    q75 = None
    for a in ov["areas"]:
        assert set(a["measured"]) == keys
        for e in a["measured"].values():
            assert e is None or ({"value", "national", "rank", "period"} <= set(e) and (e.get("source_url") or e.get("source_id")))
        cur, gap = a["measured"]["curative_intent_pct"], a["curative_gap_patients_per_year"]
        if cur:
            q75 = a["curative_gap"]["top_quartile_share_pct"]
            assert gap >= 0 and abs(gap - max(0, a["patients_per_year"] * (q75 - cur["value"]) / 100)) < 0.15
            assert "not a causal" in a["curative_gap_note_en"]
            assert a["care"]["curative_share_pct"] == cur["value"]
        assert a["lung_mortality_asr"] and a["mortality_vs_incidence"]["sentence_en"]
    ar = api.area("06")
    g = ar["measured_gaps"]
    assert g and all({"indicator", "value", "national", "best", "best_area", "worst", "rank", "direction", "note_en"} <= set(x) for x in g)
    sd = [x["sd_from_national"] for x in g if not x["context_only"]]
    assert sd == sorted(sd, reverse=True)
    cc = ar["consistency_check"]
    assert len(cc["results"]) == 3 and "not a validation" in cc["summary_en"]
    assert all(r["rho"] is None or -1 <= r["rho"] <= 1 for r in cc["results"])


def test_registry_mortality_replaces_deaths_per_100k_65plus():
    for out in (api.overview(), api.area(LAPLAND), api.area("FI"), api.optimize(LAPLAND, 1_000_000), api.simulate(LAPLAND, ["cpp_pathway"])):
        s = json.dumps(out)
        assert "per_100k_65plus" not in s and "per 100,000 residents aged 65+" not in s
    assert all("lung_deaths_per_100k" not in a and a["lung_mortality_asr"] is not None for a in api.overview()["areas"])
    mv = api.area(LAPLAND)["mortality_vs_incidence"]
    assert mv["verdict"] == "tracks_incidence" and "incidence" in mv["sentence_en"] and mv["kind"] == "measured"
    e = api.area(LAPLAND)["measured"]["lung_mortality_asr"]
    assert e["value"] > e["national"] and "syoparekisteri" in (e.get("source_url") or "")


# ---------------------------------------------------------------- evidence file
def test_measures_carry_v3_fields(m):
    for j, iv in m.iv.items():
        assert iv["owner_level"] in ("county", "collaborative_area", "national"), j
        assert iv["first_step_en"] and iv["first_step_fi"], j
        k = iv["kpi"]
        assert k["label_en"] and k["by_year"] and k["target_rule_en"], j
        assert "targets_stage" in iv and (iv["targets_stage"] is None or iv["targets_stage"] in STAGE_IDS), j
        assert iv["cost"].get("basis_en") or iv["cost"].get("basis") or iv["cost"].get("kind"), j
    access = [j for j, iv in m.iv.items() if iv["metric"] == "curative_share_pp"]
    assert {"video_mdt_stage1_3", "surgeon_second_opinion", "sbrt_pathway", "prehab_fitness_assessment",
            "travel_accommodation_support", "recording_audit"} <= set(access)
    raw = json.loads((api.MODEL.parent / "evidence" / "interventions.json").read_text())
    raw = {x["id"]: x for x in (raw["interventions"] if isinstance(raw, dict) else raw)}
    for j in access:
        ev = raw[j]["evidence"]
        assert ev and all(e.get("quote") and e.get("url", "").startswith("http") for e in ev), j
        assert any(e.get("verified") for e in ev), j
        if j != "recording_audit":
            assert m.iv[j]["lo"] == 0 and raw[j]["effect"]["kind"] == "assumption", j
    assert "remote_mdt_travel" not in m.iv


def test_ldct_and_campaign_are_fixed(m):
    ld = m.iv["ldct_screening"]
    assert ld["owner_level"] == "national" and m.is_national("ldct_screening")
    a = m.ix[LAPLAND]
    # cost and benefit refer to the same people: participants, not all residents
    part = m.screen_part[0] * m.pop[a] / 1e5
    d = m.evaluate(a, ["ldct_screening"])["deaths"]
    assert abs(d - part * m.screen_base[0] / 1000 * (1 - ld["value"])) < 1e-6
    cost = m.cost("ldct_screening", a)[2]
    assert 200_000 < cost / d < 2_000_000                  # EUR per death avoided in a plausible range, not EUR 6,000
    note = api.simulate(LAPLAND, ["ldct_screening"])["per_intervention"][0]["note_en"]
    assert "people screened" in note and f"{d:.2f} deaths avoided" in note
    sc = m.iv["symptom_campaign"]
    assert sc["confidence"] == "low" and sc["lo"] == 0
    assert "fade" in sc["what_en"].lower()
    s = api.simulate(LAPLAND, ["symptom_campaign"])["per_intervention"][0]
    # the arithmetic in the note gives the number on the card
    nums = re.search(r"([\d.]+) patients a year x ([\d.]+) percentage points.* x ([\d.]+) gain in five-year survival x ([\d.]+) ", s["note_en"])
    n, pp, gain, disc = (float(x) for x in nums.groups())
    assert abs(n * pp / 100 * gain * disc - s["deaths_avoided_per_year"]["median"]) < 0.02
    assert f"= {s['deaths_avoided_per_year']['median']:.2f} deaths avoided" in s["note_en"]


# ---------------------------------------------------------------- optimiser
def test_point_inside_interval_everywhere(opt, m):
    n = 0
    for scope in COUNTIES + ["FI"]:
        for b in BUDGETS:
            for obj in (None,) + OBJECTIVES:
                r = opt.optimize(scope, b, obj)
                T = r["totals"]
                assert _inside(T["extra_curative_patients_per_year"]) and _inside(T["deaths_avoided_per_year"]), (scope, b, obj)
                for c in r["chosen"] + r["needs_national_decision"]:
                    cur, dth = c["extra_curative_patients_per_year"], c["deaths_avoided_per_year"]
                    assert _inside(cur) and _inside(dth), (scope, b, obj, c["intervention_id"])
                    # the note states the same number as the card
                    if cur["median"] > 0:
                        assert f"it adds {cur['median']:.1f} ({cur['lo']:.1f}-{cur['hi']:.1f})" in c["note_en"], c["note_en"]
                        assert f"= {dth['median']:.2f} a year" in c["note_en"]
                    elif dth["median"] > 0:
                        assert f"{dth['median']:.2f}" in c["note_en"], (c["intervention_id"], dth, c["note_en"])
                    n += 1
                # the actions add up to the plan total
                assert abs(sum(c["extra_curative_patients_per_year"]["median"] for c in r["chosen"]) - T["extra_curative_patients_per_year"]["median"]) \
                    < 0.011 * max(len(r["chosen"]), 1)
                assert abs(sum(c["deaths_avoided_per_year"]["median"] for c in r["chosen"]) - T["deaths_avoided_per_year"]["median"]) \
                    < 0.011 * max(len(r["chosen"]), 1)
    assert n > 300
    for scope in (LAPLAND, "FI"):
        s = api.simulate(scope, list(m.iv))
        assert _inside(s["extra_curative_patients_per_year"]) and _inside(s["deaths_avoided_per_year"]) and _inside(s["days_saved"])
        for p in s["per_intervention"]:
            assert _inside(p["deaths_avoided_per_year"]) and _inside(p["extra_curative_patients_per_year"]) and _inside(p["days_saved"])
            assert _inside(p["added_in_this_set"]["deaths_avoided_per_year"])


def test_plan_and_simulate_show_the_same_number(opt, m):
    for scope in (LAPLAND, KYMENLAAKSO, VANTAA_KERAVA):
        r = opt.optimize(scope, 1_000_000)
        s = api.simulate(scope, [c["intervention_id"] for c in r["chosen"]])
        for k in ("extra_curative_patients_per_year", "deaths_avoided_per_year"):
            assert {x: s[k][x] for x in ("median", "lo", "hi")} == {x: r["totals"][k][x] for x in ("median", "lo", "hi")}


def test_plans_differ_between_counties(opt):
    plans = {a: opt.optimize(a, 1_000_000) for a in (LAPLAND, KYMENLAAKSO, SOUTHWEST)}
    seq = {a: [c["intervention_id"] for c in p["chosen"]] for a, p in plans.items()}
    assert len({tuple(v) for v in seq.values()}) == 3, seq
    assert all(p["objective"] == "curative" and p["chosen"] for p in plans.values())
    # Southwest Finland has its own university hospital: no video MDT, no remote second opinion, no travel support
    assert not {"video_mdt_stage1_3", "surgeon_second_opinion", "travel_accommodation_support"} & set(seq[SOUTHWEST])
    assert seq[LAPLAND][0] == "recording_audit" and "recording_audit" not in seq[KYMENLAAKSO]
    # KPI baselines are the county's own measured values
    for a, p in plans.items():
        cp = {s["id"]: s for s in api.care_path(a)["stages"]}
        for c in p["chosen"]:
            k = c["kpi"]
            assert k["label_en"] and k["by_year"] >= 2027 and c["first_step_en"]
            stage = api.get_model().iv[c["intervention_id"]]["kpi"]["baseline_from"]
            if stage and stage.split(".", 1)[1] in cp:
                assert k["baseline"] == cp[stage.split(".", 1)[1]]["value"] and k["target"] is not None
    # a county with no measured shortfall falls back to deaths avoided and says so
    vk = opt.optimize(VANTAA_KERAVA, 1_000_000)
    assert vk["objective"] == "deaths" and vk["objective_note_en"] and vk["totals"]["extra_curative_patients_per_year"]["median"] == 0


def test_ldct_never_inside_a_county_budget(opt, m):
    national = {j for j in m.iv if m.is_national(j)}
    assert "ldct_screening" in national
    for scope in m.ids:
        for obj in (None,) + OBJECTIVES:
            r = opt.optimize(scope, 10_000_000, obj)
            assert not national & {c["intervention_id"] for c in r["chosen"]}, (scope, obj)
            assert all(c["owner_level"] != "national" for c in r["chosen"])
            nnd = {c["intervention_id"]: c for c in r["needs_national_decision"]}
            assert "ldct_screening" in nnd and nnd["ldct_screening"]["in_budget"] is False
            assert r["totals"]["eur"] == sum(c["eur"] for c in r["chosen"])
            x = next(x for x in r["not_chosen"] if x["intervention_id"] == "ldct_screening")
            assert x["reason_code"] == "national_decision"


def test_national_plan_with_gap_objective(opt, m):
    r = opt.optimize("FI", 5_000_000)
    assert r["objective"] == "gap" and r["chosen"]
    T = r["totals"]
    assert T["extra_curative_patients_per_year"]["median"] > 0 and 0 < T["gap_closed_pct"] <= 100
    assert T["curative_share_after_pct"] > T["curative_share_now_pct"]
    # money goes only to counties below the national share (plus recording audits)
    for c in r["chosen"]:
        if c["intervention_id"] != "recording_audit":
            assert opt.shortfall(m.ix[c["area_id"]]) > 0, c
    g = r["goal3_link"]
    assert g["lung_deaths_per_year"] > 2000 and g["survival_gap_pp"] > 0 and g["note_en"] and 0 <= g["deaths_avoided_share_pct"] < 5
    assert len(r["rules_en"]) >= 12 and not any("25%" in x and "reserved" in x and "removed" not in x for x in r["rules_en"])
    assert "budget_rule_en" not in T


def test_optimiser_respects_budget_and_is_monotone(opt, m):
    for scope in ("FI", m.ids[0], LAPLAND, m.ids[-1]):
        for obj in OBJECTIVES:
            prev = -1.0
            for b in [100_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000]:
                r = opt.optimize(scope, b, obj)
                assert r["totals"]["eur"] <= b + 1
                assert sum(c["eur"] for c in r["chosen"]) <= b + len(r["chosen"])
                key = "deaths_avoided_per_year" if obj == "deaths" else "extra_curative_patients_per_year"
                d = r["totals"][key]["median"]
                assert d >= prev - 0.011
                prev = d
                fr = [f[key] for f in r["frontier"]]
                assert fr == sorted(fr) and len(fr) == len(FRONTIER)
                assert r["saturated"] in (True, False) and r["saturation_note_en"]


def test_saturation_and_exclude(opt, m):
    r = opt.optimize(LAPLAND, 5_000_000)
    assert r["saturated"] and r["totals"]["eur"] < 1_000_000 and "buys nothing more" in r["saturation_note_en"]
    assert r["totals"]["extra_curative_patients_per_year"]["hi"] <= m.reachable(m.ix[LAPLAND])["total"] + 0.01
    small = opt.optimize(LAPLAND, 100_000)
    assert not small["saturated"]
    first = next(c["intervention_id"] for c in r["chosen"] if c["intervention_id"] != "recording_audit")
    x = opt.optimize(LAPLAND, 5_000_000, exclude=[first])
    assert first not in {c["intervention_id"] for c in x["chosen"]} and x["excluded"] == [first]
    assert next(n for n in x["not_chosen"] if n["intervention_id"] == first)["reason_code"] == "excluded"
    assert api.optimize(LAPLAND, 5_000_000, exclude=[first])["excluded"] == [first]


def test_demand_side_never_bought_alone(opt, m):
    for scope in (m.ids[3], LAPLAND):
        r = opt.optimize(scope, 150_000, "deaths")
        picked = [c["intervention_id"] for c in r["chosen"]]
        for j in _demand(m):
            if j in picked:
                assert any(m.iv[c]["mechanism"] == "capacity" for c in picked[:picked.index(j)])


def test_optimiser_reasons_and_ranks(opt, m):
    r = opt.optimize("FI", 1_000_000, "deaths")
    assert r["chosen"] and [c["rank"] for c in r["chosen"]] == list(range(1, len(r["chosen"]) + 1))
    assert r["totals"]["days_saved_weighted"] > 0
    for scope in ("FI", LAPLAND, SOUTHWEST, VANTAA_KERAVA, ALAND):
        for obj in (None,) + OBJECTIVES:
            r = opt.optimize(scope, 150_000, obj)
            assert all(x["reason_code"] in REASONS and x["reason_en"] for x in r["not_chosen"])
            assert not {x["intervention_id"] for x in r["not_chosen"]} & {c["intervention_id"] for c in r["chosen"]}
            for x in r["not_chosen"]:
                if x["reason_code"] == "weak_evidence":
                    assert x["confidence"] == "low" and x["deaths_avoided_lower_bound"] <= 0
    r = opt.optimize(m.ids[3], 150_000, "deaths")       # too little for capacity plus AI triage
    picked = {c["intervention_id"] for c in r["chosen"]}
    for j in _demand(m):
        if j not in picked and not any(m.iv[c]["mechanism"] == "capacity" for c in picked):
            x = next(x for x in r["not_chosen"] if x["intervention_id"] == j)
            assert x["reason_code"] == "no_effect" and "LungIMPACT" in x["reason_en"]


def test_top_three_stable_across_seeds():
    picks = []
    for seed in (20261113, 5, 6):
        mm = Model(load_inputs(), n_draws=2000, seed=seed)
        mm.set_care_paths(api.care_paths()["paths"])
        o = Optimizer(mm)
        picks.append([[c["intervention_id"] for c in o.optimize(a, 1_000_000, obj)["chosen"][:3]]
                      for a in ("06", "14", "19") for obj in ("curative", "deaths")])
    assert picks[0] == picks[1] == picks[2]


def test_negative_lower_bound_kept_and_explained():
    s = api.simulate("05", ["cpp_pathway"])
    d = s["deaths_avoided_split"]["from_days_saved"]
    assert d["lo"] < 0 < d["median"] and "not statistically significant" in d["note_en"]
    # access measures are assumptions with a lower bound of exactly zero, never negative
    a = api.simulate(LAPLAND, ["sbrt_pathway"])
    assert a["extra_curative_patients_per_year"]["lo"] == 0 and a["deaths_avoided_per_year"]["lo"] == 0


# ---------------------------------------------------------------- API
def test_deterministic():
    ids = list(api.get_model().iv)[:3]
    assert api.simulate("05", ids, seed=7) == api.simulate("05", ids, seed=8) == api.simulate("05", ids)
    assert api.optimize("05", 730_000) == api.optimize("05", 730_000)
    assert Model(load_inputs(), 300).days.tobytes() == Model(load_inputs(), 300).days.tobytes()
    assert len(GRID) == 5 and 0.0 in GRID


def test_api_shapes_and_speed():
    ov = api.overview()
    assert len(ov["areas"]) == 23 and {"median", "lo", "hi"} <= set(ov["national"]["total_days"])
    ar = api.area("14")
    assert [s["id"] for s in ar["steps"]] == STEPS
    assert all(s["kind"] in ("estimated", "measured", "reported", "assumption") and s["method_en"] for s in ar["steps"])
    ids = list(api.get_model().iv)
    for area_id in ("14", "FI"):
        t = time.time()
        s = api.simulate(area_id, ids)
        assert time.time() - t < (1.5 if area_id != "FI" else 3.0)      # FI with all 19 measures: 23 counties x 5 scenarios x 38 sets
        assert {"baseline", "scenario", "days_saved", "deaths_avoided_per_year", "extra_curative_patients_per_year", "cost",
                "per_intervention", "n_runs"} <= set(s)
    t = time.time()
    o = api.optimize("14", 750_000)
    assert time.time() - t < 1.5
    assert {"objective", "chosen", "totals", "needs_national_decision", "not_chosen", "rules_en", "saturated", "saturation_note_en",
            "goal3_link", "frontier"} <= set(o)
    for c in o["chosen"]:
        assert {"intervention_id", "area_id", "rank", "eur", "owner_level", "targets_stage", "extra_curative_patients_per_year",
                "deaths_avoided_per_year", "eur_per_extra_curative_patient", "eur_per_death_avoided", "confidence", "first_step_en",
                "kpi"} <= set(c)
    assert {"eur", "extra_curative_patients_per_year", "deaths_avoided_per_year", "curative_share_after_pct", "gap_closed_pct"} <= set(o["totals"])
    assert {"budget_eur", "extra_curative_patients_per_year", "deaths_avoided_per_year"} <= set(o["frontier"][0])
    t = time.time()
    api.optimize("FI", 3_400_000, "gap")
    api.optimize("FI", 3_400_000, "deaths")
    assert time.time() - t < 3.0
    with pytest.raises(ValueError):
        api.optimize("14", 1_000_000, "days")
