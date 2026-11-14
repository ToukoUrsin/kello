"""County plan: one page a county director can forward.

The numbers (summary strip, target, the table of funded actions, national items, what to measure, the pilot ask) are
written by code from the optimiser answer that the county page shows (providers.optimize: same rows, same order,
same rounding). Claude writes only the three short passages around them, and a second Claude call reviews those
against the source material.

Claude (set ANTHROPIC_API_KEY; ANTHROPIC_BASE_URL if you use a gateway).
Results are cached on disk under app/server/cache/.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import math
import json
import logging
import os
import re
from pathlib import Path
from typing import AsyncIterator

import anthropic

import providers
from providers import eur_en, eur_fi, num_fi

log = logging.getLogger("kello.plan")

MODEL = "claude-opus-5-5"
CACHE = Path(__file__).resolve().parent / "cache"
CACHE.mkdir(exist_ok=True)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CITE = re.compile(r"\[\^([^\]\s]+)\]")

PLAN_VERSION = "v3-care-path-4"

# Section headings, in the order they appear on the page. gap, money and limits are written by Claude.
SECTIONS = {
    "en": {"gap": "The gap", "target": "The target", "actions": "Funded actions",
           "national": "Needs a national decision (outside this budget)", "measure": "What to measure from Monday",
           "money": "What more money buys, and what it cannot", "pilot": "Pilot ask", "limits": "Limits"},
    "fi": {"gap": "Ero", "target": "Tavoite", "actions": "Rahoitettavat toimet",
           "national": "Vaatii kansallisen päätöksen (ei sisälly tähän budjettiin)", "measure": "Mitä mitataan maanantaista alkaen",
           "money": "Mitä lisärahalla saa ja mitä ei", "pilot": "Pilottiehdotus", "limits": "Rajoitteet"},
}
WRITTEN = ("gap", "money", "limits")

WRITER_SYSTEM = """You write three short passages of a one-page plan for the director of a Finnish wellbeing services county \
(hyvinvointialue). The plan is about one thing: where the county loses lung cancer patients between diagnosis and treatment that aims \
to cure, and what closes that gap. The summary line, the target, the table of funded actions and the list of what to measure are \
written by code from the same numbers; you write only the words around them. The reader is not a statistician and has two minutes.

You are given SOURCE MATERIAL as JSON. It is the only thing you may draw on.

Output exactly these three sections in Markdown, with exactly these headings, and nothing else (no title, no other headings):

## {gap}
At most 90 words, one paragraph.
- Begin with OPENING exactly as given, character for character, including its citation marker. If OPENING is null, begin by saying in \
plain words what "care_note" says (too few patients to compare).
- If "no_shortfall" is true: say plainly that there is no shortfall, name what the county does more of than Finland as a whole from \
"above_national", and say what this plan is for instead (from plan.objective_note). Never write that an arithmetic "gives 0.0 patients".
- Otherwise, from "missing": how many patients a year are missing from treatment that aims to cure compared with the best quarter of \
counties, with its range; then how the shortfall against Finland as a whole splits (so many fewer operated, so many fewer given \
radiotherapy that aims to cure).
- If "wait_contrast" is given, say it in two short sentences of this kind: patients in the county's collaborative area do not wait \
longer from diagnosis to treatment than in Finland as a whole (give both day counts and say they are for the collaborative area); \
fewer are treated to cure.
- If expected.verdict is "below_expected", add that the share is also lower than the age of the county's residents would predict \
(give the expected share). If "recording_flags" is not empty, add one sentence that part of the gap may be treatment that was given \
but not recorded.

## {money}
At most 75 words, one paragraph. Say what the unspent part of the budget cannot buy and why (plan.saturation_note; if the plan is not \
saturated, say what is left and that it is less than the next measure costs). Say what would add more: the measures that need a national \
decision, by name, and, when plan.objective is not "deaths", ranking by deaths avoided instead. End with one sentence from "goal3": how \
many people die of lung cancer a year in the area and how many of those deaths this plan is modelled to avoid.

## {limits}
Exactly three bullet points, each at most 28 words:
- what kind of numbers the effects are (limits.effects), in plain words;
- what the county shares are not adjusted for (expected.not_adjusted_for) and that county figures cannot show cause;
- the recording caveat if "recording_flags" is not empty; otherwise that the estimated symptom-to-treatment clock is not used in this \
plan because a check against measured outcomes did not confirm it (limits.clock_check).

Rules that protect the reader:
- Plain words. Write "treated to cure" or "treatment that aims to cure" (Finnish: "parantavaan pyrkivä hoito"); never "curative-intent" \
and never "curative" alone. No rho, p values, z scores, confidence levels, "Spearman", "regression" or "quasi-binomial". \
Say "range", not "interval".
- Copy numbers exactly as they appear in the material. Do not compute new figures. Do not mention days saved or the estimated clock \
anywhere except the third bullet of the last section.
- Every sentence that states a number or a factual claim ends with one or more citation markers of the form [^source_id], using only ids \
from the SOURCES registry. Measured care-path values cite their "cite" id; anything from "plan", "missing.vs_*" ranges computed by the \
model, "expected" or "limits" cites [^model]; lung cancer deaths cite [^deaths].
- County-level figures cannot show cause. Do not write "because" or "due to" about why a county differs. A county inside the range that \
chance allows does not "fall behind". No statements about individual patients.
- Use the area name given in "name". Write in {language}.{language_note} No preamble, no closing remarks."""

FI_NOTE = (" In Finnish use a decimal comma and a space before the percent sign (18,5 %), write euros as \"211 500 €\", and inflect the "
           "area name as normal Finnish requires.")

REVIEWER_SYSTEM = """You are the reviewer of three short passages of a one-page county health plan. You receive the DRAFT and the exact \
SOURCE MATERIAL it was written from. Your job is to protect the reader from unsupported statements.

Go through the draft sentence by sentence (list items count as sentences):
- The first sentences of the first section are given text (OPENING in the material). Keep them unchanged.
- If a number, a comparison or a factual claim in the sentence is not present in the source material, or contradicts it, remove the sentence. \
If only one clause is unsupported and the rest stands, you may cut that clause instead; report it as removed.
- If a sentence carries a number or factual claim but no [^source_id] marker, or cites an id that is not in the SOURCES registry, remove it \
unless the supporting id is obvious from the material, in which case add the correct marker and keep it.
- If a sentence presents an estimate or an assumption as if it were measured, states cause from county-level data, or says a county \
"falls behind" when it is inside the range chance allows, rewrite it minimally so it is right, and report it under "flagged".
- If a sentence uses "curative-intent", rho, a p value or another statistical term a county director would not know, rewrite it in plain \
words and report it under "flagged".
- Change nothing else. Keep the three headings, their order, the language and the wording of everything that passes. Do not add new claims.

Return the corrected Markdown, the list of removed sentences with a short reason each (in English), and the list of flagged edits. \
If nothing needed changing, return empty lists."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "removed": {"type": "array", "items": {"type": "object", "properties": {"sentence": {"type": "string"}, "reason": {"type": "string"}},
                                               "required": ["sentence", "reason"], "additionalProperties": False}},
        "flagged": {"type": "array", "items": {"type": "object", "properties": {"sentence": {"type": "string"}, "reason": {"type": "string"}},
                                               "required": ["sentence", "reason"], "additionalProperties": False}},
    },
    "required": ["markdown", "removed", "flagged"],
    "additionalProperties": False,
}


def _client() -> anthropic.AsyncAnthropic | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    base_url = os.environ.get("KELLO_CLAUDE_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    return anthropic.AsyncAnthropic(base_url=base_url, api_key=key, max_retries=1)


# ---------------------------------------------------------------- formatting, one style per language

class F:
    """Numbers and fixed phrases in the plan's language."""

    def __init__(self, lang: str):
        self.fi = lang == "fi"

    def n(self, x, d: int = 1) -> str:
        if x is None:
            return "–"
        return num_fi(x, d) if self.fi else f"{float(x):.{d}f}".replace("-", "−")

    def pct(self, x) -> str:
        return f"{self.n(x)} %" if self.fi else f"{self.n(x)}%"

    def eur(self, x) -> str:
        return eur_fi(x) if self.fi else eur_en(x)

    def rng(self, lo, hi) -> str:
        if lo is not None and float(lo) < 0:  # "−0.3–8.4" reads as a typo
            return f"{self.n(lo)} {self.t('to', '…')} {self.n(hi)}"
        return f"{self.n(lo)}–{self.n(hi)}"

    def t(self, en: str, fi: str) -> str:
        return fi if self.fi else en


def _cell(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "/").strip()


def _unit(kpi: dict) -> str:
    u = kpi.get("unit")
    if u:
        return str(u)
    ind = str(kpi.get("indicator") or "")
    return "%" if ind.endswith("_pct") else "days" if ind.endswith("_days") else ""


def _kpi_text(kpi: dict, f: F, lang: str) -> str:
    """'Share of patients operated: 9.8% → 11.0% by 2028', or what to do when nothing is published."""
    label = kpi.get(f"label_{lang}") or kpi.get("label_en") or kpi.get("indicator") or ""
    unit, year = _unit(kpi), kpi.get("by_year")

    b, t = kpi.get("baseline"), kpi.get("target")
    whole = all(float(v) == int(float(v)) for v in (b, t) if v is not None)

    def val(v):
        s = f.n(v, 0) if whole else f.n(v)
        if unit == "%":
            return f"{s}\u00a0%" if f.fi else f"{s}%"
        return f"{s} {f.t('days', 'päivää')}" if unit == "days" else s

    by = f.t(f"by {year}", f"vuoteen {year} mennessä") if year else ""
    if b is not None and t is not None:
        return f"{label}: {val(b)} → {val(t)} {by}".strip()
    if t is not None:
        return f"{label}: {f.t('not published today', 'ei julkaista nyt')} → {val(t)} {by}".strip()
    return f"{label}: {f.t('not published today; record and publish it', 'ei julkaista nyt; kirjataan ja julkaistaan')} {by}".strip()


def _effect(c: dict, metric: str, f: F) -> str:
    key = "deaths_avoided_per_year" if metric == "deaths" else "extra_curative_patients_per_year"
    iv = c.get(key) or {}
    shown = (c.get("shown") or {}).get(metric, iv.get("median"))
    if not iv or f.n(iv.get("lo")) == f.n(iv.get("hi")) == f.n(shown):
        return f.n(shown)
    return f"{f.n(shown)} ({f.rng(iv.get('lo'), iv.get('hi'))})"


# ---------------------------------------------------------------- material: what the page is built from

def resolve(area_id: str, budget_eur: float, objective: str | None, exclude: list[str] | None = None) -> tuple[dict, bool]:
    """The optimiser answer the plan is written from. An objective that buys nothing here falls back to the area's default,
    so the plan is never empty. Returns (answer, fell_back)."""
    opt = providers.optimize(area_id, budget_eur, objective or None, exclude)
    if objective and not opt.get("chosen"):
        alt = providers.optimize(area_id, budget_eur, None, exclude)
        if alt.get("chosen"):
            return alt, True
    return opt, False


def build_material(area_id: str, budget_eur: float, lang: str, objective: str | None = None, exclude: list[str] | None = None) -> dict:
    budget_eur = float(budget_eur)  # 1000000 and 1000000.0 must give the same stored page (the number is part of the cache key)
    f = F(lang)
    area = providers.area(area_id)
    opt, fell_back = resolve(area_id, budget_eur, objective, exclude)
    ivs, iv_fx = providers.interventions()
    by_id = {iv["id"]: iv for iv in ivs}
    meta = area.get("area") or {}
    cp = area.get("care_path") or {}
    totals = opt.get("totals") or {}
    ui = opt.get("ui") or {}
    metric = ui.get("metric") or ("deaths" if opt.get("objective") == "deaths" else "extra")
    name = (("Suomi" if area_id == "FI" else meta.get("name_fi") or meta.get("short_fi")) if lang == "fi"
            else ("Finland" if area_id == "FI" else meta.get("short_en"))) or area_id
    registry = area.get("sources") or {}

    src: dict[str, dict] = {"model": {
        "title": f.t("Kello model: the optimiser and its stated assumptions (estimated; see Sources & method)",
                     "Kellon malli: optimointi ja sen kirjatut oletukset (arvio; ks. Lähteet ja menetelmä)"), "url": None, "kind": "estimated"}}

    def fi_pub(p):
        if lang != "fi" or not isinstance(p, str):
            return p
        for rx, to in _FI_PUBLISHER:
            p = rx.sub(to, p)
        return p

    stages = []
    for s in cp.get("stages") or []:
        sid = f"care_{s['id']}"
        rec = next((v for v in registry.values() if isinstance(v, dict) and v.get("url") == s.get("source_url")), {})
        label = s.get(f"label_{lang}") or s.get("label_en")
        reader = str(s.get("read_by") or "").split(":")[0].capitalize()
        bits = [f.t("measured", "mitattu"), str(s.get("period") or "").replace("-", "–") if re.fullmatch(r"\d{4}-\d{4}", str(s.get("period") or "")) else s.get("period")]
        if s.get("level") == "collaborative_area":
            bits.append(f.t("published for the collaborative area", "julkaistu yhteistyöalueelle"))
        if reader:
            bits.append(f.t(f"read by {reader}", f"lukenut {reader}"))
        page = f.t(f", p. {s['page']}", f", s. {s['page']}") if s.get("page") not in (None, "") else ""
        src[sid] = {"title": f"{label} ({'; '.join(str(b) for b in bits if b)}). {rec.get('title') or f.t('Finnish Cancer Registry lung cancer report', 'Suomen Syöpärekisterin keuhkosyöpäraportti')}{page}",
                    "publisher": fi_pub(rec.get("publisher")), "url": s.get("source_url"), "retrieved_at": rec.get("retrieved_at"), "kind": s.get("kind")}
        stages.append({"id": s["id"], "label": label, "value": s.get("value"), "unit": s.get("unit"), "national": s.get("national"),
                       "best": s.get("best"), "best_area": s.get("best_area_en"), "lo": s.get("lo"), "hi": s.get("hi"),
                       "outside_limits": s.get("outside_limits"), "side": s.get("side"), "direction": s.get("direction"),
                       "period": s.get("period"), "level": s.get("level"), "cite": sid})
    by_stage = {s["id"]: s for s in stages}
    g3 = opt.get("goal3_link") or {}
    mvi = area.get("mortality_vs_incidence") or {}
    src["deaths"] = {"title": f.t(f"Lung cancer deaths and age-standardised mortality by area, {mvi.get('period') or '2020-2024'} (measured). Finnish Cancer Registry statistics",
                                  f"Keuhkosyöpäkuolemat ja ikävakioitu kuolleisuus alueittain, {mvi.get('period') or '2020-2024'} (mitattu). Suomen Syöpärekisterin tilastot"),
                     "publisher": f.t("Finnish Cancer Registry", "Suomen Syöpärekisteri"), "url": g3.get("lung_deaths_source_url") or mvi.get("source_url"), "kind": "measured"}
    if g3.get("survival_source_url"):
        src["nordcan"] = {"title": f.t("Five-year survival of lung cancer patients in the Nordic countries (measured)",
                                       "Keuhkosyöpäpotilaiden viiden vuoden elossaolo Pohjoismaissa (mitattu)"),
                          "publisher": "NORDCAN, IARC", "url": g3.get("survival_source_url"), "kind": "measured"}

    def ev_id(iid: str) -> str | None:
        """Footnote for an action: its first opened evidence source."""
        evs = (by_id.get(iid) or {}).get("evidence") or []
        pick = next((n for n, ev in enumerate(evs, 1) if ev.get("verified")), 1 if evs else None)
        if pick is None:
            return None
        ev, eid = evs[pick - 1], f"ev_{iid}_{pick}"
        src[eid] = {"title": ev.get("claim"), "url": ev.get("url"), "year": ev.get("year"), "design": ev.get("design"),
                    "verified": ev.get("verified"), "kind": "evidence"}
        return eid

    chosen = [{**c, "ev": ev_id(c["intervention_id"])} for c in opt.get("chosen") or []]
    national = [{**c, "ev": ev_id(c["intervention_id"])} for c in opt.get("needs_national_decision") or []]

    leak = cp.get("main_leak") or {}
    cur = by_stage.get("curative")
    opening = None
    if leak.get(f"sentence_{lang}") or leak.get("sentence_en"):
        opening = f"{leak.get(f'sentence_{lang}') or leak.get('sentence_en')} [^care_{leak.get('stage_id') or 'curative'}]"
    mp = cp.get("missing_patients") or {}
    tq = mp.get("top_quartile") or {}
    exp = cp.get("expected") or {}
    flags = [fl.get(f"text_{lang}") or fl.get("text_en") for fl in cp.get("artefact_flags") or [] if fl.get("stage_id") in ("no_record", "drug_therapy")]
    short = float(totals.get("shortfall_vs_national_per_year") or 0)
    below = bool(cur and cur.get("side") == "below" and cur.get("outside_limits") not in (None, "none"))
    ttt = by_stage.get("time_to_treatment")
    wait = None
    if area_id != "FI" and below and ttt and ttt.get("value") is not None and ttt.get("national") is not None and ttt["value"] <= ttt["national"]:
        wait = {"days_from_diagnosis_to_treatment": ttt["value"], "finland": ttt["national"], "published_for": "the collaborative area, not the county",
                "collaborative_area": meta.get("yta_name_fi") if lang == "fi" else f"the {meta.get('yta')} collaborative area", "cite": ttt["cite"]}
    above = [s["label"] for s in stages if s.get("outside_limits") not in (None, "none") and s["id"] not in ("mdt", "time_to_treatment")
             and ((s.get("direction") == "higher_better" and s.get("side") == "above") or (s.get("direction") == "lower_better" and s.get("side") == "below"))]
    cc = area.get("consistency_check") if isinstance(area.get("consistency_check"), dict) else {}
    reasons: dict[str, dict] = {}
    for n in opt.get("not_chosen") or []:
        r = reasons.setdefault(n.get("reason_code") or "other", {"measures": 0, "example": n.get("reason_en")})
        r["measures"] += 1

    mat = {
        "language": lang, "scope": area_id, "name": name, "budget_eur": budget_eur, "objective": opt.get("objective"), "metric": metric,
        "OPENING": opening, "no_shortfall": bool(area_id != "FI" and cp.get("stages") and short == 0 and not (tq.get("per_year") or 0) > 0),
        "too_few": not cp.get("stages"), "care_note": cp.get("note_en"),
        "stages": [{k: v for k, v in s.items() if k not in ("best", "best_area", "direction")} for s in stages
                   if s["id"] in ("curative", "surgery", "no_record", "time_to_treatment")], "above_national": above,
        "missing": None if not mp else {
            "vs_finland": {"patients_per_year": mp.get("per_year"), "lo": mp.get("lo"), "hi": mp.get("hi"), "reference_pct": mp.get("reference_pct"),
                           "split": [{"what": {"surgery": "operated", "radiotherapy": "radiotherapy that aims to cure"}.get(m.get("id"), m.get("id")),
                                      "patients_per_year": m.get("per_year")} for m in mp.get("by_modality") or []]},
            "vs_best_quarter_of_counties": {"patients_per_year": tq.get("per_year"), "lo": tq.get("lo"), "hi": tq.get("hi"), "reference_pct": tq.get("reference_pct")},
            "counties_below_finland_beyond_chance": mp.get("counties_below_limits_en"), "kind": "arithmetic on measured shares, not a causal estimate",
            "cite": "care_curative [^model]"},
        "expected": None if not exp else {"observed_pct": exp.get("observed_pct"), "expected_pct": exp.get("expected_pct"), "verdict": exp.get("verdict"),
                                          "adjusted_for": exp.get("adjusted_for"), "not_adjusted_for": exp.get("not_adjusted_for"), "cite": "model"},
        "wait_contrast": wait, "recording_flags": flags,
        "plan": {"summary": (ui.get("strip") or {}).get(f"text_{lang}"), "spent_eur": totals.get("eur"), "left_eur": totals.get("eur_left"),
                 "saturated": opt.get("saturated"), "saturation_note": opt.get("saturation_note_en"), "objective": opt.get("objective"),
                 "objective_note": opt.get("objective_note_en"), "objective_in_words": opt.get("objective_en"),
                 "funded": [{"name": c.get(f"name_{lang}") or c.get("name_en"), "eur": c.get("eur")} for c in chosen],
                 "needs_national_decision": [c.get(f"name_{lang}") or c.get("name_en") for c in national],
                 "not_bought": reasons},
        "goal3": {"lung_cancer_deaths_per_year_here": g3.get("lung_deaths_per_year"),
                  "deaths_this_plan_is_modelled_to_avoid_per_year": (totals.get("shown") or {}).get("deaths"),
                  "range": [(totals.get("deaths_avoided_per_year") or {}).get("lo"), (totals.get("deaths_avoided_per_year") or {}).get("hi")],
                  "share_of_those_deaths_pct": g3.get("deaths_avoided_share_pct"), "note": g3.get("note_en"), "cite": "deaths [^model]"},
        "limits": {"effects": totals.get("interval_en"), "no_trial": next((r for r in opt.get("rules_en") or [] if "no trial" in r), None),
                   "deaths": totals.get("deaths_basis_en"), "clock_check": cc.get("summary_en"), "clock_note": area.get("clock_note_en")},
        "SOURCES": {k: {"title": v.get("title")} for k, v in src.items() if not k.startswith("ev_")},
    }
    # Not for the writer: what the code-built sections and the footnotes need.
    mat["_"] = {"opt": opt, "chosen": chosen, "national": national, "src": src, "meta": meta, "cp": cp, "by_stage": by_stage, "fell_back": fell_back,
                "fixture": bool(area.get("fixture") or opt.get("fixture") or iv_fx)}
    return mat


# ---------------------------------------------------------------- the code-built parts

def title(mat: dict) -> str:
    f = F(mat["language"])
    t = (mat["_"]["opt"].get("totals") or {})
    shown = t.get("shown") or {}
    name, spent = mat["name"], f.eur(t.get("eur") or 0)
    if mat["metric"] == "deaths":
        return f.t(f"{name}: {spent} a year, about {f.n(shown.get('deaths'))} lung cancer deaths avoided a year (modelled)",
                   f"{name}: {spent} vuodessa, arviolta {f.n(shown.get('deaths'))} keuhkosyöpäkuolemaa vähemmän vuodessa (mallinnettu)")
    return f.t(f"{name}: {f.n(shown.get('extra'))} more lung cancer patients a year treated to cure, for {spent} a year",
               f"{name}: {f.n(shown.get('extra'))} keuhkosyöpäpotilasta lisää parantavaan hoitoon vuodessa, {spent} vuodessa")


def _by_year(rows: list[dict]) -> int | None:
    ys = [c["kpi"]["by_year"] for c in rows if isinstance(c.get("kpi"), dict) and c["kpi"].get("by_year")]
    return max(ys) if ys else None


def target_section(mat: dict) -> str:
    f = F(mat["language"])
    opt, chosen = mat["_"]["opt"], mat["_"]["chosen"]
    t = opt.get("totals") or {}
    shown, year = t.get("shown") or {}, _by_year(chosen)
    if mat["metric"] == "deaths":
        iv = t.get("deaths_avoided_per_year") or {}
        s = f.t(f"This plan is ranked by deaths avoided: about {f.n(shown.get('deaths'))} a year (range {f.rng(iv.get('lo'), iv.get('hi'))}), for {f.eur(t.get('eur'))} a year. [^model] "
                "Deaths avoided are modelled from stated assumptions, not observed. [^model]",
                f"Suunnitelma on järjestetty vältettyjen kuolemien mukaan: arviolta {f.n(shown.get('deaths'))} vuodessa (vaihteluväli {f.rng(iv.get('lo'), iv.get('hi'))}), "
                f"kustannus {f.eur(t.get('eur'))} vuodessa. [^model] Vältetyt kuolemat on mallinnettu kirjatuista oletuksista, niitä ei ole havaittu. [^model]")
        if float(iv.get("lo") or 0) < 0:
            s += f.t(" The low end is below zero: how much delay adds to lung cancer deaths is not statistically certain, so no benefit cannot be ruled out. [^model]",
                     " Vaihteluvälin alaraja on alle nollan: viiveen vaikutus keuhkosyöpäkuolleisuuteen ei ole tilastollisesti varma, joten hyödyttömyyttä ei voi sulkea pois. [^model]")
        return s
    iv = t.get("extra_curative_patients_per_year") or {}
    now, after = t.get("curative_share_now_pct"), t.get("curative_share_after_pct")
    per = t.get("eur_per_extra_curative_patient")
    by_en, by_fi = (f" by {year}", f" vuoteen {year} mennessä") if year else ("", "")
    if now is not None and after is not None:
        s = f.t(f"Raise the share of lung cancer patients treated to cure from {f.pct(now)} to {f.pct(after)}{by_en}: {f.n(shown.get('extra'))} more patients a year "
                f"(range {f.rng(iv.get('lo'), iv.get('hi'))}), for {f.eur(t.get('eur'))} a year" + (f", about {f.eur(per)} per extra patient" if per else "") + ". [^care_curative][^model]",
                f"Parantavaan pyrkivää hoitoa saavien keuhkosyöpäpotilaiden osuus nostetaan {f.n(now)} %:sta {f.n(after)} %:iin{by_fi}: {f.n(shown.get('extra'))} potilasta lisää vuodessa "
                f"(vaihteluväli {f.rng(iv.get('lo'), iv.get('hi'))}), kustannus {f.eur(t.get('eur'))} vuodessa" + (f" eli noin {f.eur(per)} lisäpotilasta kohti" if per else "") + ". [^care_curative][^model]")
    else:
        s = f.t(f"{f.n(shown.get('extra'))} more patients a year treated to cure (range {f.rng(iv.get('lo'), iv.get('hi'))}), for {f.eur(t.get('eur'))} a year. [^model]",
                f"{f.n(shown.get('extra'))} potilasta lisää parantavaan hoitoon vuodessa (vaihteluväli {f.rng(iv.get('lo'), iv.get('hi'))}), kustannus {f.eur(t.get('eur'))} vuodessa. [^model]")
    pct, short = t.get("gap_closed_pct"), float(t.get("shortfall_vs_national_per_year") or 0)
    if pct is not None and short > 0:
        s += f.t(f" That closes {round(float(pct))}% of the measured shortfall against Finland as a whole ({f.n(short)} patients a year). [^model]",
                 f" Se kuroo umpeen {round(float(pct))} % mitatusta erosta koko maahan ({f.n(short)} potilasta vuodessa). [^model]")
    return s


def actions_section(mat: dict) -> str:
    """The table of funded actions. Rows, order and rounding come from the optimiser answer; the total row is its totals."""
    lang = mat["language"]
    f = F(lang)
    opt, chosen = mat["_"]["opt"], mat["_"]["chosen"]
    ui, t, metric = opt.get("ui") or {}, opt.get("totals") or {}, mat["metric"]
    key = "deaths_avoided_per_year" if metric == "deaths" else "extra_curative_patients_per_year"
    eff_h = (f.t("Deaths avoided a year (range)", "Vältettyjä kuolemia vuodessa (vaihteluväli)") if metric == "deaths"
             else f.t("More patients treated to cure a year (range)", "Potilaita lisää parantavaan hoitoon vuodessa (vaihteluväli)"))
    tot_iv = t.get(key) or {}
    total = f"**{f.n((t.get('shown') or {}).get(metric))} ({f.rng(tot_iv.get('lo'), tot_iv.get('hi'))})**"
    lines: list[str] = []
    if mat["scope"] == "FI":
        lines += [f"| # | {f.t('County', 'Alue')} | {f.t('Funded measures', 'Rahoitettavat toimet')} | {f.t('Cost a year', 'Kustannus vuodessa')} | {eff_h.split(' (')[0]} |",
                  "|---|---|---|---|---|"]
        for b in ui.get("by_county") or []:
            names = "; ".join(_cell(m.get(f"name_{lang}") or m.get("name_en")) for m in b["measures"])
            lines.append(f"| {b['n']} | **{_cell(b.get('area_fi') if lang == 'fi' else b.get('area_en'))}** | {names} | {f.eur(b['eur'])} | {f.n(b['deaths' if metric == 'deaths' else 'extra'])} |")
        lines.append(f"| | **{f.t('Total', 'Yhteensä')}** | | **{f.eur(t.get('eur'))}** | {total} |")
        lines.append("")
        lines.append(f.t("Each county's own plan lists the owner, the first step and the measure for every action. [^model]",
                         "Kunkin alueen omassa suunnitelmassa on jokaisen toimen vastuutaho, ensimmäinen askel ja mittari. [^model]"))
    else:
        lines += [f"| # | {f.t('Action and owner', 'Toimi ja vastuutaho')} | {f.t('Cost a year', 'Kustannus vuodessa')} | {eff_h} | "
                  f"{f.t('First step this week', 'Ensimmäinen askel tällä viikolla')} | {f.t('Measure: today → target', 'Mittari: nyt → tavoite')} |", "|---|---|---|---|---|---|"]
        heads = {"step_zero": ui.get(f"step_zero_title_{lang}") or ui.get("step_zero_title_en")}
        heads.update({g["id"]: g.get(f"title_{lang}") or g.get("title_en") for g in ui.get("groups") or []})
        seen = None
        for c in chosen:
            if c.get("group") != seen:
                seen = c.get("group")
                lines.append(f"| | **{_cell(heads.get(seen) or '')}** | | | | |")
            ev = f"[^{c['ev']}]" if c.get("ev") else ""
            lines.append(f"| {c.get('n', '')} | **{_cell(c.get(f'name_{lang}') or c.get('name_en'))}**{ev}. {_cell(c.get(f'owner_{lang}') or c.get('owner_en'))} | {f.eur(c.get('eur'))} | "
                         f"{_effect(c, metric, f)} | {_cell(c.get(f'first_step_{lang}') or c.get('first_step_en'))} | {_cell(_kpi_text(c.get('kpi') or {}, f, lang))} |")
        lines.append(f"| | **{f.t('Total', 'Yhteensä')}** | **{f.eur(t.get('eur'))}** | {total} | | |")
        lines.append("")
        if metric == "extra":
            lines.append(f.t("No trial has measured these effects; the low end of every range is zero. The ranges do not add up to the range of the total, "
                             "because the measures share one ceiling. Costs are assumptions. [^model]",
                             "Näitä vaikutuksia ei ole mitattu yhdessäkään tutkimuksessa; jokaisen vaihteluvälin alaraja on nolla. Vaihteluvälit eivät summaudu "
                             "kokonaisvälin suuruisiksi, koska toimilla on yhteinen yläraja. Kustannukset ovat oletuksia. [^model]"))
        else:
            lines.append(f.t("Effects are modelled from published studies and stated assumptions, not observed here. Costs are assumptions. [^model]",
                             "Vaikutukset on mallinnettu julkaistuista tutkimuksista ja kirjatuista oletuksista; niitä ei ole havaittu täällä. Kustannukset ovat oletuksia. [^model]"))
    return "\n".join(lines)


def national_section(mat: dict) -> str:
    lang = mat["language"]
    f = F(lang)
    out = []
    for c in mat["_"]["national"]:
        iv = c.get("deaths_avoided_per_year") or {}
        ev = f"[^{c['ev']}]" if c.get("ev") else ""
        where = "" if mat["scope"] != "FI" or c.get("area_id") in (None, "FI") else f" ({c.get('area_en')})"
        out.append(f.t(
            f"- **{c.get('name_en')}**{where}{ev}: {c.get('owner_en')}. {f.eur(c.get('eur'))} a year; modelled to avoid {f.n((c.get('shown') or {}).get('deaths'))} deaths a year "
            f"({f.rng(iv.get('lo'), iv.get('hi'))}). Not counted in this budget. {c.get('first_step_en') or ''} [^model]",
            f"- **{c.get('name_fi') or c.get('name_en')}**{where}{ev}: {c.get('owner_fi') or c.get('owner_en')}. {f.eur(c.get('eur'))} vuodessa; arviolta "
            f"{f.n((c.get('shown') or {}).get('deaths'))} kuolemaa vähemmän vuodessa ({f.rng(iv.get('lo'), iv.get('hi'))}). Ei sisälly tähän budjettiin. "
            f"{c.get('first_step_fi') or c.get('first_step_en') or ''} [^model]"))
    return "\n".join(out)


def measure_section(mat: dict) -> str:
    lang = mat["language"]
    f = F(lang)
    opt, chosen, by_stage = mat["_"]["opt"], mat["_"]["chosen"], mat["_"]["by_stage"]
    t = opt.get("totals") or {}
    out, done = [], set()
    now, after, year = t.get("curative_share_now_pct"), t.get("curative_share_after_pct"), _by_year(chosen)
    cur = by_stage.get("curative")
    if mat["metric"] == "extra" and now is not None and after is not None and year:
        period = str((cur or {}).get("period") or "").replace("-", "–")
        out.append(f.t(f"- Share of patients treated to cure: {f.pct(now)} ({period}, measured) → {f.pct(after)} by {year}. [^care_curative][^model]",
                       f"- Parantavaan pyrkivää hoitoa saavien osuus: {f.pct(now)} ({period}, mitattu) → {f.pct(after)} vuoteen {year} mennessä. [^care_curative][^model]"))
        done.add("curative_intent_pct")
    for c in ([] if mat["scope"] == "FI" else chosen):
        k = c.get("kpi") or {}
        ind = k.get("indicator")
        if not ind or ind in done:
            continue
        done.add(ind)
        cite = f"[^care_{c['targets_stage']}]" if k.get("baseline") is not None and c.get("targets_stage") in by_stage else ""
        out.append(f"- {_kpi_text(k, f, lang)}. {cite}[^model]")
    if cur and cur.get("period"):
        period = str(cur["period"]).replace("-", "–")
        out.append(f.t(f"- The registry's public figures cover {period}; count these each month from the county's own records. [^care_curative]",
                       f"- Syöpärekisterin julkiset luvut kattavat vuodet {period}; näitä seurataan kuukausittain alueen omista tiedoista. [^care_curative]"))
    return "\n".join(out)


def middle(mat: dict) -> dict[str, str]:
    """Every code-built section, keyed by section id (empty ones left out)."""
    lang = mat["language"]
    ui = mat["_"]["opt"].get("ui") or {}
    parts = {"target": target_section(mat), "actions": actions_section(mat), "national": national_section(mat), "measure": measure_section(mat)}
    pilot = (ui.get("pilot") or {}).get(f"text_{lang}")
    if pilot:
        parts["pilot"] = f"{pilot} [^model]"
    return {k: v for k, v in parts.items() if v.strip()}


def split_sections(md: str, lang: str) -> dict[str, str]:
    """The writer's three passages, by section id. Unknown headings are dropped."""
    names = {re.sub(r"\W+", "", v).lower(): k for k, v in SECTIONS[lang].items() if k in WRITTEN}
    out: dict[str, list[str]] = {}
    cur = None
    for line in md.splitlines():
        if line.startswith("## "):
            cur = names.get(re.sub(r"\W+", "", CITE.sub("", line[3:])).lower())
            if cur:
                out[cur] = []
        elif line.startswith("# "):
            cur = None
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items() if "\n".join(v).strip()}


def fallback_sections(mat: dict) -> dict[str, str]:
    """Used for a passage the writer did not deliver: the model's own sentences, nothing new."""
    f = F(mat["language"])
    p = mat["plan"]
    gap = mat.get("OPENING") or f"{mat.get('care_note') or ''} [^model]"
    money = f"{p.get('saturation_note') or ''} [^model]"
    limits = "\n".join([
        f.t("- The effects are assumptions with a stated range; no trial has measured them here. [^model]",
            "- Vaikutukset ovat oletuksia, joille on annettu vaihteluväli; niitä ei ole mitattu tutkimuksissa täällä. [^model]"),
        f.t("- County shares are not adjusted for stage at diagnosis or other illness, and county figures cannot show cause. [^model]",
            "- Alueiden osuuksia ei ole vakioitu levinneisyyden tai muiden sairauksien mukaan, eivätkä aluetason luvut osoita syytä. [^model]"),
        f.t("- Part of a gap can be treatment that was given but not recorded. [^model]",
            "- Osa erosta voi olla annettua mutta kirjaamatta jäänyttä hoitoa. [^model]")])
    return {"gap": gap.strip(), "money": money.strip(), "limits": limits}


def assemble(mat: dict, written: dict[str, str]) -> str:
    lang = mat["language"]
    s = SECTIONS[lang]
    ui = mat["_"]["opt"].get("ui") or {}
    mid, fb = middle(mat), fallback_sections(mat)
    parts = [f"# {title(mat)}", f"> {(ui.get('strip') or {}).get(f'text_{lang}') or ''}"]
    for key in ("gap", "target", "actions", "national", "measure", "money", "pilot", "limits"):
        body = (written.get(key) or fb.get(key)) if key in WRITTEN else mid.get(key)
        if body:
            parts += [f"## {s[key]}", body]
    return "\n\n".join(parts)


# ---------------------------------------------------------------- cache: the same inputs always give the same page

def _tag(mat: dict) -> str:
    """Changes when the prompts, the page layout or the numbers the page is written from change; nothing else may change
    the stored page. Built from content only (no file paths, no file times), so the same data gives the same key on every machine."""
    body = json.dumps({"writer": {k: v for k, v in mat.items() if k != "_"}, "middle": middle(mat), "title": title(mat)},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((PLAN_VERSION + WRITER_SYSTEM + REVIEWER_SYSTEM + json.dumps(SECTIONS, sort_keys=True) + body).encode()).hexdigest()[:10]


def _objective(objective: str | None) -> str:
    o = re.sub(r"[^a-z]", "", str(objective or "").lower())
    return o or "default"


def _excl(exclude: list[str] | None) -> list[str]:
    return sorted({re.sub(r"[^a-z0-9_]", "", str(x).lower()) for x in exclude or [] if x})


def cache_path(scope: str, budget_eur: float, lang: str, objective: str | None = None, exclude: list[str] | None = None,
               mat: dict | None = None) -> Path:
    """One file per (scope, budget, language, objective the optimiser used, measures left out, hash of the model output)."""
    ex = _excl(exclude)
    mat = mat or build_material(scope, budget_eur, lang, objective, ex)
    without = ("_x-" + hashlib.sha256(",".join(ex).encode()).hexdigest()[:8]) if ex else ""
    return CACHE / f"plan_{scope}_{int(budget_eur)}_{lang}_o-{_objective(mat.get('objective'))}{without}_{_tag(mat)}.json"


def cached_plan(scope: str, budget_eur: float, lang: str, objective: str | None = None, exclude: list[str] | None = None) -> dict | None:
    f = cache_path(scope, budget_eur, lang, objective, exclude)
    if not f.exists():
        return None
    try:
        plan = json.loads(f.read_text())
    except Exception:  # noqa: BLE001
        return None
    plan["cached"] = True
    return plan


def no_writer() -> bool:
    """True on a copy that cannot write a new plan (the hosted demo has no Claude)."""
    return bool(os.environ.get("KELLO_HOSTED")) or _client() is None


def nearest_plan(scope: str, budget_eur: float, lang: str, objective: str | None = None, exclude: list[str] | None = None) -> dict | None:
    """For a copy without a writer: the stored plan of this area and language closest to what was asked, labelled as such.
    Same objective first, then no left-out measures, then the nearest budget."""
    want = _objective(objective) if objective else None
    best = None
    for f in CACHE.glob(f"plan_{scope}_*_{lang}_o-*.json"):
        m = re.fullmatch(rf"plan_{re.escape(scope)}_(\d+)_{lang}_o-([a-z]+)(_x-[0-9a-f]+)?_[0-9a-f]+\.json", f.name)
        if not m:
            continue
        try:
            plan = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if plan.get("version") != PLAN_VERSION or plan.get("generated_by") == "template":
            continue
        b = int(m.group(1))
        key = (0 if (want is None or m.group(2) == want) else 1, 1 if m.group(3) else 0,
               abs(math.log(max(b, 1)) - math.log(max(budget_eur, 1))), -f.stat().st_mtime)
        if best is None or key < best[0]:
            best = (key, plan, b)
    if best is None:
        return None
    plan, b = best[1], best[2]
    plan["cached"] = True
    # the reader switched actions off, but the stored page was written with all of them: say so
    full = bool(exclude) and not plan.get("excluded")
    plan["nearest"] = {"asked_budget_eur": budget_eur, "budget_eur": b, "objective": plan.get("objective"),
                       "label_en": f"This copy cannot write a new plan. Showing the stored plan for {providers.eur_en(b)} a year"
                                   + (", with every action still in it." if full else "."),
                       "label_fi": f"Tämä versio ei voi kirjoittaa uutta suunnitelmaa. Näytetään tallennettu suunnitelma: {providers.eur_fi(b)} vuodessa"
                                   + (", kaikki toimet mukana." if full else ".")}
    return plan


# Official Finnish names of the publishers that appear in footnotes.
_FI_PUBLISHER = [
    (re.compile(r"^Statistics Finland$"), "Tilastokeskus"),
    (re.compile(r"^Finnish Cancer Registry \(Syöpärekisteri\)$|^Finnish Cancer Registry$"), "Suomen Syöpärekisteri"),
    (re.compile(r"^THL Sotkanet; data owner: .*$"), "THL Sotkanet"),
    (re.compile(r"^Finnish [Ii]nstitute for Health and Welfare \(THL\)$"), "Terveyden ja hyvinvoinnin laitos (THL)"),
    (re.compile(r"^Social Insurance Institution of Finland \(Kela\)$"), "Kela"),
]


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-zåäö]+", " ", CITE.sub("", str(text)).lower()).strip()


def present(plan: dict) -> dict:
    """What the page shows on top of the stored plan: a plain count of what the reviewer did."""
    plan = dict(plan)
    review = dict(plan.get("review") or {})
    body = _norm(plan.get("markdown") or "")
    removed = [r for r in review.get("removed") or [] if isinstance(r, dict)]
    gone = [r for r in removed if _norm(r.get("sentence") or "") not in body]
    flagged = [r for r in review.get("flagged") or [] if isinstance(r, dict)]
    cite_only = [r for r in flagged if re.search(r"no citation marker\. Added|Added \[\^|^Missing (source|citation) marker", str(r.get("reason") or "").strip())]
    review["summary"] = {"rewritten": len(flagged) - len(cite_only) + len(removed) - len(gone), "removed": len(gone), "citations_added": len(cite_only),
                         "reviewed": review.get("checked_by") not in (None, "review failed") and not str(review.get("checked_by")).startswith("none")}
    plan["review"] = review
    return plan


def extract_claims(markdown: str) -> list[dict]:
    claims = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c for c in line.strip("|").split("|")] if line.startswith("|") else [line]
        for cell in cells:
            for sent in re.split(r"(?<=\])\s+(?=[A-ZÅÄÖ*\d])", cell.strip()):
                ids = list(dict.fromkeys(CITE.findall(sent)))
                if ids:
                    text = re.sub(r"\s+", " ", CITE.sub("", sent)).strip(" ->*").strip()
                    claims.append({"text": text, "source_ids": ids})
    return claims


def _finish(mat: dict, written: dict[str, str], review: dict, generated_by: str, extra: dict | None = None) -> dict:
    md = assemble(mat, written)
    used = list(dict.fromkeys(CITE.findall(md)))
    opt = mat["_"]["opt"]
    src = mat["_"]["src"]
    unknown = [i for i in used if i not in src]
    if unknown:
        # A citation to an id that does not exist is taken out of the page rather than shown as a broken footnote.
        for i in unknown:
            md = md.replace(f"[^{i}]", "")
        review = {**review, "unknown_source_ids": unknown}
        used = [i for i in used if i in src]
    out = {
        "version": PLAN_VERSION, "title": title(mat), "markdown": md, "claims": extract_claims(md), "review": review,
        "sources": {k: src[k] for k in used},
        "area_id": mat["scope"], "budget_eur": mat["budget_eur"], "lang": mat["language"],
        "objective": opt.get("objective"), "objective_fell_back": bool(mat["_"]["fell_back"]), "excluded": opt.get("excluded") or [],
        # which table row is which measure, so the page can print today's web check under the action it belongs to
        "actions": [{"n": c.get("n"), "id": c.get("intervention_id"), "name": c.get(f"name_{mat['language']}") or c.get("name_en"),
                     "study_line_en": c.get("study_line_en"), "why_here_en": c.get("why_here_en")} for c in mat["_"]["chosen"]],
        # Deterministic additions remain available on hosted copies even when the
        # surrounding prose is an older cached page.
        "pilot": (opt.get("pilot") or (opt.get("ui") or {}).get("pilot")),
        "action_studies": [{"id": c.get("intervention_id"), "study_line_en": c.get("study_line_en"),
                            "why_here_en": c.get("why_here_en")} for c in mat["_"]["chosen"] if c.get("study_line_en") or c.get("why_here_en")],
        "strip": (opt.get("ui") or {}).get("strip"), "written_sections": [SECTIONS[mat["language"]][k] for k in WRITTEN],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "generated_by": generated_by,
    }
    if mat["_"]["fixture"]:
        out["fixture"] = True
    out.update(extra or {})
    return out


def template_plan(mat: dict, reason: str) -> dict:
    """When Claude is not reachable: the code-built page with the model's own sentences in place of the written passages. Clearly marked."""
    return _finish(mat, {}, {"removed": [], "flagged": [], "checked_by": "none (template fallback)"}, generated_by="template",
                   extra={"fixture": True, "fixture_reason": reason})


def _attach_deterministic_fields(plan: dict, mat: dict) -> dict:
    """Refresh fields owned by the app even when the prose comes from an old cache.

    Hosted copies deliberately serve stored prose, but the pilot, action evidence and
    county-specific rationale must follow the current deterministic optimiser output.
    """
    out = dict(plan or {})
    opt = mat["_"]["opt"]
    chosen = opt.get("chosen") or []
    out["actions"] = [{"n": c.get("n"), "id": c.get("intervention_id"),
                       "name": c.get(f"name_{mat['language']}") or c.get("name_en"),
                       "study_line_en": c.get("study_line_en"), "why_here_en": c.get("why_here_en")} for c in chosen]
    out["pilot"] = opt.get("pilot") or (opt.get("ui") or {}).get("pilot")
    out["action_studies"] = [{"id": c.get("intervention_id"), "study_line_en": c.get("study_line_en"),
                              "why_here_en": c.get("why_here_en")} for c in chosen
                             if c.get("study_line_en") or c.get("why_here_en")]
    out["strip"] = (opt.get("ui") or {}).get("strip")
    if isinstance(out.get("sources"), dict):
        out["sources"] = {k: mat["_"]["src"].get(k, v) for k, v in out["sources"].items()}
    return out


async def generate(area_id: str, budget_eur: float, lang: str, refresh: bool = False, objective: str | None = None,
                   exclude: list[str] | None = None) -> AsyncIterator[tuple[str, dict]]:
    """Yield (event, payload): status / delta / done / error.

    The same (area, budget, language, objective, left-out measures) returns the stored page until the prompts or the model
    inputs change, or until refresh=True asks for a new one.
    """
    exclude = _excl(exclude)
    mat = await asyncio.to_thread(build_material, area_id, budget_eur, lang, objective, exclude)
    path = cache_path(area_id, budget_eur, lang, objective, exclude, mat)
    if not refresh and path.exists():
        try:
            hit = json.loads(path.read_text())
            hit["cached"] = True
            yield "done", present(_attach_deterministic_fields(hit, mat))
            return
        except Exception:  # noqa: BLE001
            log.warning("stored plan %s unreadable; writing it again", path.name)
    if no_writer():
        near = await asyncio.to_thread(nearest_plan, area_id, budget_eur, lang, objective, exclude)
        hit = near or template_plan(mat, "this copy has no plan writer and no stored plan for this area")
        yield "done", present(_attach_deterministic_fields(hit, mat))
        return
    yield "status", {"stage": "material", "label": "Collecting the county's numbers"}
    client = _client()

    s = SECTIONS[lang]
    mid = middle(mat)
    ui = mat["_"]["opt"].get("ui") or {}
    head = f"# {title(mat)}\n\n> {(ui.get('strip') or {}).get(f'text_{lang}') or ''}\n\n"
    before_money = "".join(f"## {s[k]}\n\n{mid[k]}\n\n" for k in ("target", "actions", "national", "measure") if k in mid)
    before_limits = f"## {s['pilot']}\n\n{mid['pilot']}\n\n" if "pilot" in mid else ""
    system = WRITER_SYSTEM.format(gap=s["gap"], money=s["money"], limits=s["limits"], language="Finnish" if lang == "fi" else "English",
                                  language_note=FI_NOTE if lang == "fi" else "")
    mat_json = json.dumps({k: v for k, v in mat.items() if k != "_"}, ensure_ascii=False, indent=1)
    user = f"SOURCE MATERIAL\n```json\n{mat_json}\n```\n\nWrite the three sections."
    draft = ""
    try:
        yield "status", {"stage": "writing", "label": "Claude is writing the plan"}
        yield "delta", {"text": head}
        kw = dict(model=MODEL, max_tokens=8000, thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                  system=system, messages=[{"role": "user", "content": user}])
        # The writer's sections arrive in page order except that the code-built sections sit between them:
        # hold back a few characters so a heading is seen whole, and slot the code-built text in before it.
        marks = [(f"## {s['money']}", before_money), (f"## {s['limits']}", before_limits)]
        hold = max(len(m) for m, _ in marks)
        sent = 0
        for attempt in (0, 1):
            try:
                mgr = (client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kw) if attempt == 0
                       else client.messages.stream(**kw))
                async with mgr as stream:
                    async for text in stream.text_stream:
                        draft += text
                        while True:
                            if marks:
                                pos = draft.find(marks[0][0], sent)
                                if pos >= 0:
                                    out = draft[sent:pos].rstrip("\n") + "\n\n" + marks[0][1]
                                    sent = pos
                                    marks.pop(0)
                                    yield "delta", {"text": out}
                                    continue
                            upto = len(draft) - (hold if marks else 0)
                            if upto > sent:
                                yield "delta", {"text": draft[sent:upto]}
                                sent = upto
                            break
                    final = await stream.get_final_message()
                break
            except anthropic.BadRequestError as e:
                if attempt == 1 or draft:
                    raise
                log.warning("fallback beta rejected, retrying without: %s", e)
        if sent < len(draft):
            yield "delta", {"text": draft[sent:]}
        if final.stop_reason == "refusal" or not draft.strip():
            raise RuntimeError(f"writer returned no text (stop_reason={final.stop_reason})")

        yield "status", {"stage": "reviewing", "label": "Reviewer is checking every sentence against the sources"}
        rkw = dict(model=MODEL, max_tokens=8000, thinking={"type": "adaptive"},
                   output_config={"effort": "medium", "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
                   system=REVIEWER_SYSTEM,
                   messages=[{"role": "user", "content": f"SOURCE MATERIAL\n```json\n{mat_json}\n```\n\nDRAFT\n```markdown\n{draft}\n```"}])
        try:
            try:
                async with client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **rkw) as rs:
                    rfinal = await rs.get_final_message()
            except anthropic.BadRequestError:
                async with client.messages.stream(**rkw) as rs:
                    rfinal = await rs.get_final_message()
            rj = json.loads("".join(b.text for b in rfinal.content if b.type == "text"))
            checked = split_sections(rj["markdown"], lang)
            review = {"removed": rj.get("removed", []), "flagged": rj.get("flagged", []),
                      "checked_by": f"{MODEL} reviewer pass against the source material"}
        except (json.JSONDecodeError, KeyError) as e:
            checked = {}
            review = {"removed": [], "flagged": [], "checked_by": "review failed", "error": f"reviewer output unreadable: {e}"}
        first = split_sections(draft, lang)
        written = {k: checked.get(k) or first.get(k) for k in WRITTEN if checked.get(k) or first.get(k)}
        missing = [SECTIONS[lang][k] for k in WRITTEN if k not in written]
        if missing:
            review["sections_from_model_text"] = missing
        plan = _finish(mat, written, review, generated_by=MODEL, extra={"draft_markdown": draft})
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
        yield "done", present(plan)
    except anthropic.APIConnectionError as e:
        log.warning("Claude endpoint unreachable: %s", e)
        yield "done", present(template_plan(mat, "the plan writer could not be reached"))
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s: %s", e.status_code, e.message)
        if e.status_code in (429, 503, 529):
            yield "error", {"error": "The plan writer is busy", "detail": "Try again in a minute.", "status": 503}
        else:
            yield "error", {"error": "The plan writer returned an error", "detail": str(e.message)[:300]}
    except Exception as e:  # noqa: BLE001
        log.exception("plan generation failed")
        yield "error", {"error": "Plan generation failed", "detail": str(e)[:300]}
