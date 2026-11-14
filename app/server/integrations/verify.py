"""Live web check of one measure for one county: a search-and-read loop whose answer changes the plan.

The question is specific and has two halves:

  B. in use  - "Is <measure> already running in <county> (or its university hospital area)?"
               -> yes | partly | planned | no_evidence
  A. effect  - "Does recent evidence support the size of effect we assume?"
               -> supports | weaker | contradicts | not_found

Oxylabs `/v1/search` finds pages (round 1 is run by code, in Finnish, with the terms a local page
uses), Oxylabs `/v1/scrape` reads them, the model (Claude, or Gemini when Claude is not there:
llm.py) names what is still unanswered and searches again: at most 3 rounds, about 75 s.

What the answer does to the plan (`plan_effect`):
  exclude - a page says it is already running here: take it out, its money goes to the next measure
  flag    - part of it exists, or it is decided but not running, or evidence contradicts the effect:
            keep the money but look before paying
  keep    - no public sign of it: the measure stays; the result says what was searched and where

    check_measure(intervention, area_id, on_event=None) -> result (kept under cache/verify/)
    verify_claim(question, context="", area_id=None, on_event=None) -> result
    latest(area_id) -> [stored results for that county]
    stored(intervention_id, area_id) -> the stored result or None

Rules applied in code after the model answers: a quote that is not literally in the text of a page
read in this run is dropped; a half with no surviving quote becomes not_found / no_evidence; an
"in use" quote must come from a page that names the county or its university hospital area (a
national page can support "partly" or "planned", never "yes").

When Oxylabs or both models fail or time out, the last good result for the same (measure, county)
is returned with `from_cache: true` and its own `checked_at`, so the button never ends in an error.

Env: JUNCTION_OXYLABS_API_KEY; ANTHROPIC_API_KEY (Claude; ANTHROPIC_BASE_URL if you use a gateway) and/or
GEMINI_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import agent, counties, llm, oxylabs

MODEL = agent.MODEL
BUDGET_S = 75.0
MAX_ROUNDS = 3
SCHEMA = 4  # stored results older than this are run again by prerun.py
STORE = Path(os.environ.get("KELLO_VERIFY_STORE") or Path(__file__).resolve().parents[1] / "cache" / "verify")

_ASKS = {
    "days": "shorten the time from first symptom to treatment start for lung cancer patients, and by how many days",
    "relative_days": "shorten the time from first symptom to treatment start for lung cancer patients, and by how much",
    "stage_shift_pp": "lead to lung cancer being found at an earlier stage, and by how much",
    "mortality_rr": "reduce deaths among the people it reaches, and by how much",
    "curative_share_pp": "raise the share of lung cancer patients who get curative-intent treatment, and by how much",
}
_VERDICT = {"supports": "supported", "weaker": "mixed", "contradicts": "contradicted", "not_found": "not_found"}
_IN_USE = ("yes", "partly", "planned", "no_evidence")

# What a Finnish page calls each measure. Search hints only: nothing here is shown as a fact.
_TERMS = {
    "cpp_pathway": ["keuhkosyövän hoitopolku", "keuhkosyövän hoitoketju", "hoitoonpääsy määräajat keuhkosyöpä", "varatut tutkimusajat syöpäepäily"],
    "same_day_cxr_ct": ["keuhkokuva lausunto samana päivänä", "thorax-röntgen päivystyslausunto", "keuhkokuvan jälkeen suoraan TT"],
    "gp_direct_ct": ["terveyskeskuslääkäri suora lähete keuhkojen TT", "matala-annos-TT lähete perusterveydenhuolto", "keuhkosyöpäepäily lähete kuvantaminen"],
    "ai_cxr_triage_alone": ["tekoäly keuhkokuva", "tekoäly thorax-röntgen käyttöön", "tekoäly radiologia"],
    "ebus_capacity": ["EBUS", "keuhkoputkien ultraäänitähystys", "bronkoskopia jono"],
    "reflex_molecular": ["refleksitestaus keuhkosyöpä", "NGS keuhkosyöpä patologia", "molekyylipatologia EGFR ALK"],
    "liquid_biopsy_first": ["nestebiopsia keuhkosyöpä", "ctDNA verinäyte EGFR", "plasman EGFR-mutaatiotutkimus"],
    "nurse_navigator": ["syöpähoitaja koordinaattori", "hoitokoordinaattori keuhkosyöpä", "keuhkosyöpähoitaja", "syöpäkoordinaattori"],
    "ldct_screening": ["keuhkosyöpäseulonta pilotti", "matala-annos-TT seulonta", "keuhkosyövän seulontapilotti"],
    "symptom_campaign": ["yskä yli kolme viikkoa kampanja", "keuhkosyövän oireet kampanja", "pitkittynyt yskä tutkimuksiin"],
    "nssc_rapid_dx_centre": ["diagnostinen keskus syöpäepäily", "epämääräiset syöpäoireet nopea diagnostiikka", "diagnostiikkakeskus"],
    "gp_capacity_econsult": ["omalääkärimalli", "hoitotakuu 14 vuorokautta lääkärille pääsy", "sähköinen konsultaatio keuhkolääkäri", "e-konsultaatio erikoislääkäri"],
    "video_mdt_stage1_3": ["moniammatillinen kokous keuhkosyöpä", "MDT-kokous etäyhteydellä", "keuhkomeeting videoyhteys", "hoitokokous keuhkosyöpä"],
    "surgeon_second_opinion": ["thoraxkirurgin konsultaatio", "keuhkokirurgi leikkausarvio keuhkosyöpä", "keuhkosyöpäleikkaukset keskittäminen", "leikkauskelpoisuus keuhkosyöpä"],
    "sbrt_pathway": ["stereotaktinen sädehoito keuhkosyöpä", "täsmäsädehoito keuhkosyöpä", "SBRT", "sädehoito keuhkosyöpä lähete"],
    "prehab_fitness_assessment": ["prehabilitaatio", "esikuntoutus syöpäleikkaus", "leikkausta edeltävä kuntoutus", "toimintakyvyn arvio spiroergometria"],
    "travel_accommodation_support": ["potilashotelli", "potilaskoti", "majoitus sädehoidon ajaksi", "matkakorvaus syöpähoito"],
    "recording_audit": ["hoitoilmoitus kirjaaminen syöpä", "syöpärekisteri hoitotietojen ilmoittaminen", "kirjaamisen laatu syöpähoidot", "laaturekisteri keuhkosyöpä"],
    "smoking_cessation_at_diagnosis": ["tupakasta vieroitus keuhkosyöpäpotilas", "tupakkavieroitus", "savuton leikkaus", "vieroitushoitaja"],
}
_PREFERRED = ("the county's own site and decision documents, the university hospital's care-pathway pages, "
              "syoparekisteri.fi, kaypahoito.fi, julkari.fi (THL), fican.fi, kela.fi, duodecimlehti.fi, PubMed/PMC")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------- the quote rule

_MD = re.compile(r"[*_`#>|\\]+")


def _squash(s: str) -> str:
    s = _MD.sub("", s or "")
    s = s.replace(" ", " ").replace("–", "-").replace("—", "-").replace("‑", "-")
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("­", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    q = _squash(quote).strip(' ."\'')
    return len(q) >= 12 and q in _squash(text)


def _around(quote: str, text: str, span: int = 1800) -> str:
    """The page text around a quote (for checking that it is about this county)."""
    sq, st = _squash(quote).strip(' ."\''), _squash(text)
    i = st.find(sq)
    return st[max(0, i - span): i + len(sq) + span] if i >= 0 else ""


# ----------------------------------------------------------------- prompt and answer schema

_SYSTEM = """You check one care-improvement measure for a Finnish wellbeing services county. The reader is the county's director, who is about to spend money on the measure. Your answer changes the plan: "yes" takes the measure out and moves its money to the next one, so a wrong "yes" costs more than an honest "no sign of it".

You work only from pages you fetch with the tools in this conversation. What you remember is not evidence and must not appear in the answer; search snippets are not evidence either.

The two questions, in order of importance
B. IN USE HERE: is this measure already running in this county, or in the university hospital area that treats its patients?
A. EFFECT: does recent evidence support the size of effect our model assumes?

How to work
- Search round 1 has been run for you. Read three to five of its results in one turn, never one page at a time: a single page often turns out to be thin or slow, and each turn costs several seconds. In the same turn read the evidence page we already hold for A, if one is listed.
- The university hospital's lung cancer care-pathway page ("keuhkosyöpäpotilaan hoitopolku") usually says who decides what, where surgery and radiotherapy are given and which meetings every patient passes. Read it early: it answers B for most treatment measures, for the whole area including this county.
- After each round, name what is still unanswered and search again for exactly that with different words: another Finnish term from the task, the hospital instead of the county, "hanke", "pilotti", "aluehallitus päätös", a year. Do not repeat a query. Stop when both questions are answered or when the budget note says so.
- Prefer these sources: {preferred}. Skip pages that only sell something.

Answering B (in_use_here)
- yes: a page describes the core of the measure as a running service that this county's patients get, in the county or at the university hospital that treats them. The page must say it, not merely make it likely.
- partly: a page shows a real piece of the measure running, so that the director should pay for less than the whole measure (for example a patient hotel exists, but nothing says transport is organised or that a named contact books it; or the treatment is offered, but nothing says every eligible patient is referred). Say in missing_en which piece no page shows. The piece must be something the measure adds: ordinary care that every hospital gives (a lung function test before surgery, a doctor who can refer) is not a piece of it. If your advice would be to keep the line as it is, the answer is no_evidence and the local facts go into quotes as "context".
- planned: a page says it is decided, funded, being piloted or being prepared there, and is not running yet.
- no_evidence: none of these. A missing web page does not prove the measure is absent, so write "no public sign of it", never "not in use".
- in_use_scope says how local the page is: county, collaborative_area (the university hospital area), national (a Finnish national service or programme that covers every county, such as Kela reimbursements; it can support partly or planned, not yes), or none.
- A local fact that bears on the measure but shows none of the above (for example where the county's patients get radiotherapy) goes into quotes with about "context".

Answering A (effect_check)
- supports: pages you read report an effect of the same direction and at least the assumed size, in a comparable setting. weaker: the direction is supported, but the size is smaller, not measured, indirect, or from a different setting. contradicts: they report no effect or harm. not_found: no page you read reports on it.
- supported_en says in one short sentence what the pages do support, with the number and who published it; not_supported_en says what they do not show. Never write the word "mixed".

The finish tool
- quotes: every statement needs a quote copied character for character from a page you read with the read tool: 15 to 300 characters, one continuous passage, original language, no ellipsis, no translation, no joining of separate sentences. At least one per question you answered; put the single best "in_use" quote first. Quotes that are not literally in the page are discarded automatically and the question they supported is reported as not found, so copy exactly. Quote a sentence that says the thing: a menu item, a heading, a table cell or a line of a list of services does not show that something runs or is decided.
- advice: what the director should do with this line of the plan. take_out: it already runs here (in_use_here is yes). narrow: pay only for the piece that is missing (partly). check_first: ask a named body before paying, because it is decided, being prepared or probably covered (planned, or partly). keep: nothing found changes the line.
- plan_effect_reason_en: one sentence the director can act on, beginning with the action ("Take this line out", "Narrow this line to ...", "Ask <body> first whether ...", "Keep this line"), then why. Plain words, no jargon, name the body whose page says it. It must agree with advice and with in_use_here.
- summary_en: two or three plain English sentences. Numbers and dates as the pages state them, the publishing body named for each fact. B first.
- unanswered_en: what you looked for and did not find, in one sentence; empty if nothing is open."""

FINISH_TOOL = {
    "name": "finish",
    "description": "Give the final answer. Call it once, when both questions are answered or the budget is spent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "in_use_here": {"type": "string", "enum": list(_IN_USE)},
            "in_use_scope": {"type": "string", "enum": ["county", "collaborative_area", "national", "none"]},
            "in_use_summary_en": {"type": "string", "description": "One sentence: what exactly is running or planned, where and since when, as the page says; or that no public sign of it was found."},
            "missing_en": {"type": "string", "description": "For partly: the piece of the measure that no page shows, in one short sentence. Else empty."},
            "effect_check": {"type": "string", "enum": ["supports", "weaker", "contradicts", "not_found"]},
            "effect_summary_en": {"type": "string", "description": "One sentence: what the pages say about the effect, with the number."},
            "supported_en": {"type": "string", "description": "What the evidence read does support, in one short sentence with the number and the publisher. Empty if nothing."},
            "not_supported_en": {"type": "string", "description": "What the evidence read does not show (for example the exact size we assume), in one short sentence. Empty if nothing."},
            "advice": {"type": "string", "enum": ["take_out", "narrow", "check_first", "keep"],
                       "description": "What the director should do with this line of the plan."},
            "plan_effect_reason_en": {"type": "string", "description": "One sentence for the county director, beginning with the action, then why."},
            "quotes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL of the page as you passed it to read."},
                        "quote": {"type": "string"},
                        "about": {"type": "string", "enum": ["in_use", "effect", "context"]},
                    },
                    "required": ["url", "quote", "about"],
                    "additionalProperties": False,
                },
            },
            "summary_en": {"type": "string"},
            "unanswered_en": {"type": "string"},
        },
        "required": ["in_use_here", "in_use_scope", "effect_check", "quotes", "advice", "plan_effect_reason_en", "summary_en"],
        "additionalProperties": False,
    },
}


def _place(h: dict | None) -> str:
    if not h:
        return ("Place: Finland as a whole (no single county). For question B, look for national or regional use in Finland.")
    return (
        f"County: {h['name_fi']} ({h['name_en']}). Names a local page would use: {h['brand']}, {h['short_fi'] or h['name_fi']}; "
        f"main city {h['city']}; hospitals: {', '.join(h['hospitals'])}. Its site is probably {h['site']} (a guess; check by searching).\n"
        f"University hospital area: {h['uni_hospital']} in {h['uni_city']}"
        + (f" (its pages are on {' or '.join(h['uni_sites'])})" if h.get("uni_sites") else "") + "."
    )


def _where(h: dict | None, scope: str) -> str:
    if not h:
        return "Finland"
    name = h.get("short_en") or h["name_en"]
    if scope == "collaborative_area":
        return f"the {h['uni_short']} university hospital area, which treats {name}'s patients"
    if scope == "national":
        return f"Finland as a whole, {name} included"
    return name


def opening_searches(intervention_id: str | None, name_fi: str, h: dict | None) -> list[dict]:
    """Round 1, written by code: the pathway page of the university hospital and the measure's own
    Finnish terms with the names a local page uses."""
    terms = _TERMS.get(intervention_id or "") or [name_fi or "keuhkosyöpä hoito"]
    t = lambda i: terms[i] if i < len(terms) else terms[0]  # noqa: E731
    if not h:
        return [{"query": f"{t(0)} Suomi", "why": "the measure in Finland"},
                {"query": f"{t(1)} hyvinvointialue", "why": "the measure in a county"},
                {"query": f"{t(2)} yliopistollinen sairaala", "why": "the measure at a university hospital"}]
    uni = h["uni_short"] or h["brand"]
    own = h["hospitals"][0]
    qs = [{"query": f"{uni} keuhkosyöpäpotilaan hoitopolku", "why": "the university hospital's lung cancer pathway page"},
          {"query": f"{h['brand']} {t(0)}", "why": "the measure on the county's own pages"},
          {"query": f"{uni} {t(1)}", "why": "the measure at the university hospital"}]
    if own.lower().split()[0] != uni.lower():
        qs.append({"query": f"{own} {t(2) if len(terms) > 2 else t(0)}", "why": "the measure at the county hospital"})
    else:
        qs.append({"query": f"{h['short_fi'] or h['brand']} {t(2)} keuhkosyöpä", "why": "the measure under another Finnish name"})
    return qs


# ----------------------------------------------------------------- the check

def verify_claim(question: str, context: str = "", *, area_id: str | None = None, on_event=None,
                 focus: str = "", budget_s: float = BUDGET_S, max_rounds: int = MAX_ROUNDS,
                 intervention_id: str | None = None, name_fi: str = "", zero_effect: bool = False) -> dict:
    """Run the loop on one two-part question. Never raises for web or model trouble: returns
    verdict "not_found" with an `error` field instead."""
    t0 = time.time()
    h = counties.hints(area_id)
    base = {
        "schema": SCHEMA, "question": question, "area_id": area_id or "FI", "verdict": "not_found", "effect_check": "not_found",
        "effect_summary_en": "", "supported_en": "", "not_supported_en": "", "in_use_here": "no_evidence", "in_use_scope": "none",
        "in_use_quote": None, "in_use_source": None, "in_use_summary_en": "", "missing_en": "", "summary_en": "",
        "unanswered_en": "", "sources": [], "trace": [], "rounds": 0, "searches": 0, "pages_read": [], "quotes_dropped": 0,
        "model": llm.default_model(), "models": [], "search_backend": "oxylabs-web-api", "budget_s": budget_s,
        "zero_effect": bool(zero_effect), "from_cache": False, "checked_at": _now(),
    }
    try:
        if not oxylabs.has_credentials():
            raise oxylabs.OxylabsAuthError("JUNCTION_OXYLABS_API_KEY is not set; live search is unavailable")
        if not llm.any_ready():
            raise llm.NoModel("no model is connected: Claude is not reachable and GEMINI_API_KEY is not set")
        terms = _TERMS.get(intervention_id or "") or []
        task = (f"{question}\n\n{_place(h)}\n\n{context or ''}\n"
                + (f"Finnish terms a page may use for this measure: {'; '.join(terms)}.\n" if terms else "")
                + f"\nToday: {_now()[:10]}. Budget: {int(budget_s)} seconds in total and at most {max_rounds} search rounds "
                  "(round 1 is already done), so work in parallel.")
        local = " ".join((h["local_terms"] + h["yta_terms"] + h["hospitals"]) if h else ["Suomi", "Finland"])

        def review(draft: dict, pages: dict) -> str | None:
            got = _settle(draft, pages, h)
            if got["in_use_here"] == "no_evidence":
                where = f"{h['brand']} / {h['hospitals'][0]} / {h['uni_hospital']}" if h else "Finland"
                return (f"question B: no page read so far says the measure, or a piece of it, is running or planned in {where}. "
                        "Try another Finnish term from the task, the university hospital's pathway page, or a decision document.")
            if got["effect_check"] == "not_found":
                return "question A: no page read so far reports on the effect."
            return None

        run = agent.run(_SYSTEM.replace("{preferred}", _PREFERRED), task, FINISH_TOOL, focus_terms=f"{focus} {' '.join(terms)} {local}",
                        max_rounds=max_rounds, budget_s=budget_s, on_event=on_event, review=review,
                        opening=opening_searches(intervention_id, name_fi, h))
        base.update(trace=run["trace"], rounds=run["rounds"], searches=run["searches"], stopped=run["stopped"],
                    model=run["model"], models=run["models"])
        seen = set()
        for p in run["pages"].values():
            if id(p) in seen:
                continue
            seen.add(id(p))
            base["pages_read"].append({"url": p["url"], "title": p["title"], "chars": p["chars"], "kind": p.get("kind"),
                                       "from_cache": bool(p.get("from_cache")), "fetched_at": p["fetched_at"],
                                       "published": p.get("published"), "js_render": p.get("status") == "ok_js"})
        ans = run["answer"]
        if ans is None:
            raise RuntimeError("the time budget ran out before an answer was written")
        base.update(_settle(ans, run["pages"], h))
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        base["summary_en"] = base["summary_en"] or "Could not complete the live check."
    base["seconds"] = round(time.time() - t0, 1)
    base["checked_at"] = _now()
    return present(base)


def _settle(ans: dict, pages: dict, h: dict | None) -> dict:
    """Apply the quote rule and the "is it really about this county" rule to the model's answer."""
    sources, dropped, notes = [], 0, []
    for q in ans.get("quotes") or []:
        quote = str(q.get("quote") or "").strip()
        about = q.get("about") if q.get("about") in ("effect", "in_use", "context") else "effect"
        p = agent.quote_page(pages, str(q.get("url") or ""), quote, quote_in_text)
        if p is None:
            dropped += 1
            continue
        if any(s["url"] == p["url"] and s["quote"] == quote for s in sources):
            continue
        src = {"url": p["url"], "title": p["title"], "quote": quote, "about": about, "published": p.get("published") or None,
               "fetched_at": p["fetched_at"], "from_cache": bool(p.get("from_cache"))}
        if about in ("in_use", "context") and h:
            host = urlsplit(p["url"]).netloc.lower().removeprefix("www.")
            near = _around(quote, p["text"]) + " " + p["title"].lower()
            loc = counties.mentions(near, h["local_terms"]) or ([h["site"]] if host.endswith(h["site"]) else [])
            yta = counties.mentions(near, h["yta_terms"]) or [s for s in (h.get("uni_sites") or []) if host.endswith(s)]
            # acronyms are case-sensitive and _around() lowercases: look for them in the page text itself
            if not loc and not yta:
                i = p["text"].find(quote[:40])
                raw = p["text"][max(0, i - 1800): i + len(quote) + 1800] if i >= 0 else ""
                loc = counties.mentions(raw, h["local_terms"])
                yta = counties.mentions(raw, h["yta_terms"])
            src["local"] = "county" if loc else ("collaborative_area" if yta else ("national" if host.endswith(".fi") else None))
        sources.append(src)

    effect = ans.get("effect_check") if ans.get("effect_check") in _VERDICT else "not_found"
    if effect != "not_found" and not any(s["about"] == "effect" for s in sources):
        effect = "not_found"
        notes.append("No verbatim quote about the effect survived the check, so the effect is reported as not found.")

    claimed = ans.get("in_use_here") if ans.get("in_use_here") in _IN_USE else "no_evidence"
    advice = ans.get("advice") if ans.get("advice") in ("take_out", "narrow", "check_first", "keep") else None
    if claimed == "partly" and advice == "keep":
        claimed = "no_evidence"  # the model itself says the whole measure is still needed: what it found is context
    in_use = claimed
    scope = ans.get("in_use_scope") if ans.get("in_use_scope") in ("county", "collaborative_area", "national", "none") else "none"
    use_q = [s for s in sources if s["about"] == "in_use"]
    pick = None
    if in_use != "no_evidence":
        if not use_q:
            in_use, scope = "no_evidence", "none"
            notes.append("No verbatim quote about local use survived the check, so local use is reported as no public sign of it.")
        elif h:
            local_q = [s for s in use_q if s.get("local") in ("county", "collaborative_area")]
            nat_q = [s for s in use_q if s.get("local") == "national"]
            if local_q:
                pick = local_q[0]  # the model lists its best quote first
                scope = pick["local"]
            elif nat_q and scope == "national":
                pick = nat_q[0]
                if in_use == "yes":
                    in_use = "partly"
                    notes.append("The page quoted is national and does not name this county, so the answer is lowered from yes to partly.")
            else:
                in_use, scope = "no_evidence", "none"
                notes.append(f"The page quoted for use does not name {h['name_en']} or its university hospital area near the quote, "
                             "so local use is reported as no public sign of it.")
        else:
            pick = use_q[0]
    if in_use == "no_evidence":
        pick = None
    for s in sources:
        s.pop("local", None)
        if in_use == "no_evidence" and s["about"] == "in_use":
            s["about"] = "context"  # a local fact that was read, not a sign that the measure runs

    summary = str(ans.get("summary_en") or "").strip()
    if notes:
        summary = (summary + " " if summary else "") + "Check: " + " ".join(notes)
    if not sources and summary:
        summary = "No verbatim evidence survived the quote check. Unchecked draft answer: " + summary
    txt = lambda k: str(ans.get(k) or "").strip()  # noqa: E731
    return {
        "verdict": _VERDICT[effect], "effect_check": effect, "effect_summary_en": txt("effect_summary_en"),
        "supported_en": txt("supported_en") if effect != "not_found" else "", "not_supported_en": txt("not_supported_en"),
        "in_use_here": in_use, "in_use_scope": scope,
        "in_use_quote": pick["quote"] if pick else None,
        "in_use_source": {"url": pick["url"], "title": pick["title"], "published": pick.get("published"),
                          "fetched_at": pick.get("fetched_at")} if pick else None,
        "in_use_summary_en": txt("in_use_summary_en"), "missing_en": txt("missing_en") if in_use == "partly" else "",
        "advice": advice,
        # the model's own sentence is kept only when the code did not change its answer
        "model_reason_en": txt("plan_effect_reason_en") if in_use == claimed and effect == ans.get("effect_check")
                           and _fits(advice, in_use) else "",
        "summary_en": summary, "unanswered_en": txt("unanswered_en"),
        "sources": sources, "quotes_dropped": dropped,
    }


def _fits(advice: str | None, in_use: str) -> bool:
    """The model's advice agrees with the settled answer (else its sentence is replaced by a plain one)."""
    if advice is None:
        return True
    return {"yes": advice == "take_out", "partly": advice in ("narrow", "check_first"),
            "planned": advice in ("check_first", "narrow"), "no_evidence": advice == "keep"}[in_use]


# ----------------------------------------------------------------- what the result means for the plan

_ENDPOINT_WHY = {
    "POST /v1/search": "finds the pages: Finnish queries run from Finland, so county, hospital and registry pages rank first",
    "POST /v1/scrape": "reads each page: plain fetch first, JavaScript render when the page comes back as navigation only, "
                       "PDFs as text; journal records go through Europe PMC",
}


def _host(u: str) -> str:
    return urlsplit(u or "").netloc.lower().removeprefix("www.")


def _sentence(s: str) -> str:
    s = " ".join(str(s or "").split())
    return s if not s or s[-1] in ".!?" else s + "."


def searched(trace: list, pages_read: list) -> tuple[str, list[str]]:
    """("Searched 5 queries (...) and read 7 pages on a.fi, b.fi.", [queries]) from a run's trace."""
    trace = [t for t in trace or [] if isinstance(t, dict)]
    queries = [str(t.get("input")) for t in trace if "search" in str(t.get("tool")) and not t.get("error")]
    read_hosts = list(dict.fromkeys(_host(str(t.get("url") or t.get("input"))) for t in trace
                                    if "scrape" in str(t.get("tool")) and not t.get("error")))
    if not read_hosts:
        read_hosts = list(dict.fromkeys(_host(p.get("url", "")) for p in pages_read or []))
    n_read = sum(1 for t in trace if "scrape" in str(t.get("tool")) and not t.get("error")) or len(pages_read or [])
    if not (queries or read_hosts):
        return "", queries
    text = (f"Searched {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}"
            + (" (" + "; ".join(f'"{q}"' for q in queries[:4]) + (", ..." if len(queries) > 4 else "") + ")" if queries else "")
            + f" and read {n_read} page{'' if n_read == 1 else 's'}"
            + (" on " + ", ".join(read_hosts[:6]) if read_hosts else "") + ".")
    return text, queries


def endpoints_used(trace: list) -> list[dict]:
    """One row per Oxylabs endpoint a run called: how often, how often it failed, and why it is used."""
    trace = [t for t in trace or [] if isinstance(t, dict)]
    used = []
    for ep in ("POST /v1/search", "POST /v1/scrape"):
        tool = "search" if ep.endswith("search") else "scrape"
        calls = [t for t in trace if tool in str(t.get("tool"))]
        if calls:
            row = {"endpoint": ep, "api": "Oxylabs Web API", "calls": len(calls), "failed": sum(1 for t in calls if t.get("error")),
                   "why_en": _ENDPOINT_WHY[ep]}
            if tool == "scrape":
                row["js_render"] = sum(1 for t in calls if t.get("js_render"))
                row["from_cache"] = sum(1 for t in calls if t.get("from_cache"))
            used.append(row)
    return used


def present(res: dict) -> dict:
    """Add the fields the page shows, from the result itself (also for results stored by older code):
    plan_effect, plan_effect_reason_en, verdict_en, endpoints_used, searched_en. Idempotent."""
    res = dict(res)
    h = counties.hints(res.get("area_id"))
    use = res.get("in_use_here") if res.get("in_use_here") in _IN_USE else "no_evidence"
    eff = res.get("effect_check") if res.get("effect_check") in _VERDICT else "not_found"
    scope = res.get("in_use_scope") or "none"
    where = _where(h, scope if use != "no_evidence" else "county")
    name = (h.get("short_en") or h["name_en"]) if h else "Finland"
    src_host = _host((res.get("in_use_source") or {}).get("url") or "")
    trace = [t for t in res.get("trace") or [] if isinstance(t, dict)]

    # --- what was searched and where, and through which endpoints
    res["searched_en"], queries = searched(trace, res.get("pages_read") or [])
    res["queries"] = queries
    n_read = sum(1 for t in trace if "scrape" in str(t.get("tool")) and not t.get("error")) or len(res.get("pages_read") or [])
    res["endpoints_used"] = endpoints_used(trace)

    # --- plan effect
    if use == "yes":
        effect = "exclude"
    elif use in ("partly", "planned") or eff == "contradicts":
        effect = "flag"
    else:
        effect = "keep"
    reason = _sentence(res.get("model_reason_en") or "")
    if not reason or res.get("error"):
        says = f" ({src_host})" if src_host else ""
        if effect == "exclude":
            reason = f"Already running in {where}{says}: take it out of the plan and its money goes to the next measure."
        elif use == "partly":
            miss = _sentence(res.get("missing_en") or "")
            reason = (f"Part of this is already in place in {where}{says}: pay only for the missing piece"
                      + (f". Not shown on any page: {miss}" if miss else "."))
        elif use == "planned":
            reason = f"{where[0].upper() + where[1:]} has decided or is preparing this{says}: check with them before paying for it twice."
        elif effect == "flag":
            reason = "Evidence read in this check reports no effect: ask for a small pilot with a measured result before funding it at scale."
        elif res.get("error"):
            reason = "The check did not finish, so the measure stays in the plan unchecked."
        else:
            reason = (f"No public page says this is running in {name}"
                      + (f" after {len(queries)} search{'' if len(queries) == 1 else 'es'} and {n_read} page{'' if n_read == 1 else 's'} read" if queries else "") + ". That does not prove it is absent, so it stays in the plan and the hospital is asked.")
    res["plan_effect"] = effect
    res["plan_effect_reason_en"] = reason
    # One answer per action: the advice word always agrees with what the check does to the plan.
    adv = res.get("advice")
    res["advice"] = ("take_out" if effect == "exclude" else "keep" if effect == "keep"
                     else adv if adv in ("narrow", "check_first") else "check_first")
    res["evidence_n"] = local_evidence(res)

    # --- the verdict in plain words (never the bare word "mixed")
    zero = bool(res.get("zero_effect"))
    use_en = {
        "yes": f"Already running in {where}.",
        "partly": f"Partly in place in {where}." + (f" Missing: {_sentence(res.get('missing_en'))}" if res.get("missing_en") else ""),
        "planned": f"Decided or being prepared in {where}, not running yet.",
        "no_evidence": f"No public page says it is running in {name}; that is not proof it is absent.",
    }[use]
    sup, nsup = _sentence(res.get("supported_en") or ""), _sentence(res.get("not_supported_en") or "")
    if eff == "supports":
        eff_en = ("The problem it fixes is documented." if zero else "Recent evidence supports the size of effect we assume.") \
                 + (f" {sup}" if sup else "")
    elif eff == "weaker":
        eff_en = ("The problem it fixes is documented only in part." if zero
                  else "Evidence supports that it works, but not the size of effect we assume.")
        if sup or nsup:
            eff_en += (f" Supported: {sup}" if sup else "") + (f" Not supported: {nsup}" if nsup else "")
        elif res.get("effect_summary_en"):
            eff_en += " " + _sentence(res["effect_summary_en"])
    elif eff == "contradicts":
        eff_en = "Evidence read in this check reports no effect." + (f" {_sentence(res.get('effect_summary_en'))}" if res.get("effect_summary_en") else "")
    else:
        eff_en = ("No page read in this check documents the problem it fixes." if zero
                  else "No page read in this check reports the size of the effect.")
    res["verdict_en"] = f"{use_en} {eff_en}"
    res["in_use_label_en"] = {"yes": "Already running here", "partly": "Partly in place", "planned": "Planned, not running yet",
                              "no_evidence": "No public sign of it"}[use]
    res["effect_label_en"] = {
        "supports": "Problem documented" if zero else "Effect size supported",
        "weaker": "Problem partly documented" if zero else "Works, size not shown",
        "contradicts": "No effect reported", "not_found": "Nothing found on the effect"}[eff]
    if res.get("error"):  # nothing was checked: say so instead of "no sign of it"
        err = str(res["error"])
        why = ("Live search is not connected on this server." if "OxylabsAuth" in err
               else "No model answered." if "NoModel" in err
               else "It ran out of time before an answer was written." if "time budget" in err
               else "The search or the model failed.")
        res["verdict_en"] = f"The live check could not finish, so this measure is unchecked. {why} Try again in a minute."
        res["in_use_label_en"] = res["effect_label_en"] = "Not checked"
    res.setdefault("from_cache", False)
    if use in ("partly", "planned", "yes") and not res.get("missing_short_en"):
        res["missing_short_en"] = missing_short(res.get("missing_en"))
    return res


def missing_short(missing: str | None) -> str | None:
    """A few words for a pin, cut from the check's own "what is missing" sentence: its first clause, without the
    "No page shows" opening. The stored checks carry a shorter phrase written once from the same sentence
    (integrations/missing_short.py); this is what a fresh live check gets."""
    s = re.sub(r"\s+", " ", missing or "").strip().rstrip(".")
    if not s:
        return None
    s = re.sub(r"^(?:I found )?no (?:public )?(?:page|source|site)s? (?:read )?(?:shows?|says?|describes?|mentions?|confirms?|states?)\s*(?:that\s+)?", "", s, flags=re.I)
    s = re.split(r",| or that | or any | before | - ", s, maxsplit=1)[0].strip()
    words = s.split()
    return (" ".join(words[:12]) + ("…" if len(words) > 12 else "")) or None


def question_for(iv: dict, area_id: str | None) -> tuple[str, str, str]:
    """(question, context, focus terms) for one intervention and county."""
    h = counties.hints(area_id)
    eff = iv.get("effect") or {}
    where = h["name_en"] if h else "Finland"
    area = f" (or in the {h['uni_short']} university hospital area that treats its patients)" if h and h.get("uni_short") else ""
    zero = _zero_effect(iv)
    a_q = ("A. Our model assumes no direct effect on patients for this measure. Instead: does a source you read document the "
           "problem it fixes?" if zero else
           f"A. Does recent evidence support the size of effect we assume: does this measure {_ASKS.get(eff.get('metric'), _ASKS['relative_days'])}?")
    question = (f"B. Is this measure already running in {where}{area}?\n{a_q}\n"
                f"Measure: {iv.get('name_en')}. {iv.get('what_en') or ''}").strip()
    ev = "\n".join(f"- {e.get('claim')} ({e.get('url')})" for e in (iv.get("evidence") or [])[:3])
    assumed = {k: eff.get(k) for k in ("metric", "value", "lo", "hi", "kind") if eff.get(k) is not None}
    context = (
        f"Finnish name of the measure: {iv.get('name_fi')}.\n"
        f"Effect our model assumes: {json.dumps(assumed)}. Basis: {str(eff.get('basis') or 'not stated')[:500]}\n"
        f"Evidence we already hold (read one of these for A instead of searching for it again):\n{ev or '- none'}\n"
        f"Prerequisite: {iv.get('prerequisite_en') or 'none'}."
    )
    focus = f"{iv.get('name_fi') or ''} {iv.get('name_en') or ''} keuhkosyöpä lung cancer"
    return question, context, focus


def _zero_effect(iv: dict) -> bool:
    eff = iv.get("effect") or {}
    return eff.get("value") in (0, 0.0) and eff.get("hi") in (0, 0.0, None)


# ----------------------------------------------------------------- the store (last good result per measure and county)

def _file(intervention_id: str, area_id: str | None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", intervention_id)[:80]
    return STORE / f"{safe}__{re.sub(r'[^A-Za-z0-9]', '', area_id or 'FI') or 'FI'}.json"


def stored(intervention_id: str, area_id: str | None = None) -> dict | None:
    """The last good result for this measure and county, as stored; None if there is none."""
    try:
        return json.loads(_file(str(intervention_id), area_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_fresh(intervention_id: str, area_id: str | None = None, max_age_s: float = 86400.0) -> bool:
    """A stored result of the current schema that is younger than max_age_s."""
    old = stored(intervention_id, area_id)
    if not old or old.get("schema") != SCHEMA:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(old["checked_at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return False
    return age < max_age_s


def failure_en(err: str | None) -> str:
    """Why a live run did not answer, in plain words (no exception names, no endpoints)."""
    e = str(err or "")
    if "OxylabsAuth" in e or "no_search" in e:
        return "the web search is not connected on this copy"
    if "NoModel" in e or "401" in e or "403" in e:
        return "no language model answered"
    if re.search(r"429|rate|overload|529|busy", e, re.I):
        return "the search or the model was busy"
    if "time budget" in e or "did not finish within" in e or "imeout" in e:
        return "it ran out of time before an answer was written"
    if "restarted" in e:
        return "the server restarted during the run"
    return "the search or the model failed"


def from_store(intervention_id: str, area_id: str | None, live_error: str | None = None) -> dict | None:
    """The stored result marked as such: `from_cache: true`, its own `checked_at`, and why the live run did not answer."""
    old = stored(intervention_id, area_id)
    if not old:
        return None
    old = present(old)
    old["from_cache"] = True
    for k in ("previous", "live_candidate", "stability", "live_trace"):
        old.pop(k, None)
    if live_error:
        old["live_error"] = live_error
        old["live_error_en"] = failure_en(live_error)
        old["live_tried_at"] = _now()
        old["live_outcome"] = "failed"
    return old


def _names_area(src: dict, h: dict, res: dict) -> bool:
    """The page of this quote names the county or its university hospital area (judged from what a result keeps:
    the site, the title, the quote, and the scope the quote rule gave the in-use quote)."""
    if res.get("in_use_quote") and src.get("quote") == res.get("in_use_quote") \
            and res.get("in_use_scope") in ("county", "collaborative_area"):
        return True
    host = _host(src.get("url") or "")
    if h.get("site") and host.endswith(h["site"]) or any(host.endswith(x) for x in h.get("uni_sites") or []):
        return True
    near = f"{src.get('title') or ''} {src.get('quote') or ''}"
    return bool(counties.mentions(near, h["local_terms"]) or counties.mentions(near, h["yta_terms"]))


def local_evidence(res: dict | None) -> int:
    """How much a check found, as one number: verbatim quotes (every quote kept passed the quote rule) on pages that
    name the county or its university hospital area. A live run replaces the stored answer only when it is at least
    as large. Used the same way for every model, so a weaker run cannot overwrite a stronger stored one."""
    if not isinstance(res, dict) or res.get("error"):
        return 0
    h = counties.hints(res.get("area_id"))
    seen = set()
    for s in res.get("sources") or []:
        if isinstance(s, dict) and s.get("quote") and (h is None or _names_area(s, h, res)):
            seen.add((s.get("url"), s.get("quote")))
    return len(seen)


def _view(res: dict | None) -> dict | None:
    if not isinstance(res, dict):
        return None
    out = {k: res.get(k) for k in ("verdict", "effect_check", "in_use_here", "plan_effect", "advice", "checked_at", "model")}
    out["evidence_n"] = local_evidence(res)
    return out


def check_measure(iv: dict, area_id: str | None = None, on_event=None, budget_s: float = BUDGET_S) -> dict:
    """The app's check: one intervention (a row of interventions.json), one county.

    One answer per action: the stored result is what every screen shows. A live run replaces it only when it found
    at least as much evidence (local_evidence: verbatim quotes on pages that name the county or its university
    hospital area). `live_outcome` says what happened: "first" (nothing was stored), "replaced", "kept" (the run
    found less; the stored answer is returned unchanged, with `live_candidate` summarising the run) or "failed"
    (the run did not finish; the stored answer is returned with `live_error_en`)."""
    iid = str(iv.get("id"))
    question, context, focus = question_for(iv, area_id)
    res = verify_claim(question, context, area_id=area_id, on_event=on_event, focus=focus, budget_s=budget_s,
                       intervention_id=iid, name_fi=str(iv.get("name_fi") or ""), zero_effect=_zero_effect(iv))
    old = stored(iid, area_id)  # read after the run: the store can change while it is searching
    h = counties.hints(area_id)
    res.update(intervention_id=iv.get("id"), intervention_name_en=iv.get("name_en"),
               area_name_en=h["name_en"] if h else "Finland")
    if "error" in res:
        kept = from_store(iid, area_id, res["error"])
        return kept if kept is not None else res
    res = present(res)
    for k in ("previous", "live_candidate", "stability"):
        res.pop(k, None)
    if old:
        old = present(old)
        # On the public site one visitor's run must not change what every other screen and visitor sees:
        # the stored answer stays, and this run is shown next to it.
        pinned = bool(os.environ.get("KELLO_VERIFY_PIN"))
        if pinned or local_evidence(res) < local_evidence(old):
            for k in ("previous", "live_candidate", "stability", "live_trace", "live_pinned"):
                old.pop(k, None)
            old.update(live_outcome="kept", live_candidate=_view(res), live_trace=res.get("trace") or [],
                       live_seconds=res.get("seconds"))
            if pinned and local_evidence(res) >= local_evidence(old):
                old["live_pinned"] = True
            return old
        res["previous"] = _view(old)
        res["live_outcome"] = "replaced"
    else:
        res["live_outcome"] = "first"
    try:
        STORE.mkdir(parents=True, exist_ok=True)
        f = _file(iid, area_id)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)
    except OSError:
        pass
    return res


def latest(area_id: str | None = None) -> list[dict]:
    """Stored checks for one county ("FI" or None: the national ones), newest first."""
    want = re.sub(r"[^A-Za-z0-9]", "", area_id or "FI") or "FI"
    out = []
    for f in STORE.glob(f"*__{want}.json"):
        try:
            r = present(json.loads(f.read_text(encoding="utf-8")))
            for k in ("previous", "live_candidate", "stability", "live_trace", "live_outcome", "live_pinned"):
                r.pop(k, None)  # the stored answer as it stands; what a live run changed is shown only after that run
            out.append(r)
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r.get("checked_at") or "", reverse=True)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m integrations.verify")
    ap.add_argument("intervention_id", help="an id from data/evidence/interventions.json")
    ap.add_argument("area_id", nargs="?", help="county id such as 21; omit for Finland")
    ap.add_argument("--out", help="also write the JSON here")
    ap.add_argument("--quiet", action="store_true", help="do not print the steps while running")
    a = ap.parse_args(argv)
    ivs = json.loads((counties.ROOT / "data" / "evidence" / "interventions.json").read_text(encoding="utf-8"))
    ivs = ivs.get("interventions") if isinstance(ivs, dict) else ivs
    iv = next((i for i in ivs if i["id"] == a.intervention_id), None)
    if iv is None:
        print("unknown intervention; ids: " + ", ".join(i["id"] for i in ivs), file=sys.stderr)
        return 2

    def show(e: dict) -> None:
        if e.get("status") == "done" and not a.quiet:
            print(f'  [{e["step"]:>2}] r{e["round"]} {e["tool"]:<19} {str(e["input"])[:70]:<70} -> {e["result_en"][:110]} ({e["ms"]} ms)',
                  file=sys.stderr, flush=True)

    res = check_measure(iv, a.area_id, on_event=show)
    js = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(js + "\n", encoding="utf-8")
    print(js)
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
