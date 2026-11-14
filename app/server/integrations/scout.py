"""County scout: "what is this county doing about lung cancer care right now?"

The same search-and-read loop as the live check (agent.py), pointed at the county's own site, its
decision documents and local news, with Finnish queries. Returns up to 6 dated findings, each
with a verbatim quote from a page read in this run and, when it fits, the Kello measure or
care-path stage it relates to.

    scout(area_id, on_event=None) -> {area_id, findings:[{date, what_en, what_fi, quote, url, title,
                                      relates_to, scope}], summary_en, not_found_en, trace, rounds, ...}
    latest(area_id) -> the stored result or None

Rules applied in code: a finding whose quote is not literally in the page is dropped; so is one
whose page does not name the county or its university hospital area; a date whose year is not
printed on the page is set to null.

The model is Claude, or Gemini when Claude is not there (llm.py); the trace says which one answered.
When Oxylabs or both models fail or time out, the last good result for the county is returned with
`from_cache: true` and its own `checked_at`.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import agent, counties, llm, oxylabs
from .verify import quote_in_text

BUDGET_S = 90.0
MAX_ROUNDS = 3
MAX_FINDINGS = 6
STORE = Path(__file__).resolve().parents[1] / "cache" / "scout"
STAGES = {
    "staged": "stage recorded at diagnosis", "mdt": "multidisciplinary team meeting recorded",
    "curative": "curative-intent treatment", "surgery": "surgery", "radiotherapy": "radiotherapy",
    "drug_therapy": "drug therapy", "life_prolonging": "life-prolonging treatment",
    "symptomatic_only": "symptomatic care only", "no_record": "no treatment record",
    "time_to_treatment": "days from diagnosis to treatment start", "alive_1y": "alive one year after diagnosis",
}

_SYSTEM = """You scout what one Finnish wellbeing services county is doing about lung cancer care right now, for a decision-maker who is planning what to fund there. They want to know what is already running, decided or being prepared, so that they do not pay for it twice.

You work only from pages you fetch with the tools in this conversation. What you remember is not evidence; search snippets are not evidence either.

What counts as a finding: something this county, its hospital or its university hospital area does, decided, started, measured or plans that touches lung cancer care: referral and diagnosis (imaging, bronchoscopy, pathology, molecular tests), care pathways and waiting times, the multidisciplinary meeting, surgery, radiotherapy, drug therapy, nurse coordinators, screening pilots, smoking cessation, staffing or equipment for any of these, reorganisation of where patients are treated, published waiting-time or quality figures. General patient information ("what is lung cancer") is not a finding.

How to work
- First turn: four searches at once, in Finnish, each from a different angle: the county's own site (its short name plus keuhkosyöpä), its hospital or the university hospital plus hoitopolku or hoitoonpääsy, decision documents (aluehallitus, aluevaltuusto, hanke, investointi plus syöpä), and local news of this year or last year.
- Next turn: read four or five of the most promising results together, never one at a time. Prefer the county's own pages, decision documents and dated news over national pages.
- After each round, name the kind of finding you still lack (a decision, a number, a date, a plan) and search for exactly that with different words. Do not repeat a query. Stop when you have six good findings or the budget note says so.

Answer with the finish tool
- findings: at most six, newest first, each a different fact. `what_en` and `what_fi`: one plain sentence each, saying who does what, with the number or date if the page gives one. `quote`: copied character for character from the page, 15 to 300 characters, one continuous passage, original language, no ellipsis. `url`: the page you read. `date`: the date the page gives for the fact or its publication, as YYYY-MM-DD, YYYY-MM or YYYY; null if the page gives none. `relates_to`: the id of the Kello measure or care-path stage the fact is about, from the list in the task, or "none".
- Findings whose quote is not literally in the page are discarded automatically, as are findings from pages that do not name this county or its university hospital area. Fewer true findings are better than six weak ones.
- summary_en: two or three plain sentences: what the county is visibly doing, and what you looked for and did not find.
- not_found_en: one sentence on what you searched for without result; empty if nothing."""


def _finish_tool(ids: list[str]) -> dict:
    return {
        "name": "finish",
        "description": "Give the findings. Call it once, when you have six good findings or the budget is spent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": ["string", "null"], "description": "YYYY-MM-DD, YYYY-MM or YYYY as the page gives it; null if none."},
                            "what_en": {"type": "string"},
                            "what_fi": {"type": "string"},
                            "quote": {"type": "string"},
                            "url": {"type": "string"},
                            "relates_to": {"type": "string", "enum": ids + ["none"]},
                        },
                        "required": ["date", "what_en", "what_fi", "quote", "url", "relates_to"],
                        "additionalProperties": False,
                    },
                },
                "summary_en": {"type": "string"},
                "not_found_en": {"type": "string"},
            },
            "required": ["findings", "summary_en"],
            "additionalProperties": False,
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _interventions() -> list[dict]:
    try:
        data = json.loads((counties.ROOT / "data" / "evidence" / "interventions.json").read_text(encoding="utf-8"))
        return (data.get("interventions") if isinstance(data, dict) else data) or []
    except (OSError, ValueError):
        return []


def _settle(ans: dict, pages: dict, h: dict, ids: set[str]) -> dict:
    out, dropped = [], {"quote_not_on_page": 0, "not_about_this_county": 0}
    for f in (ans.get("findings") or [])[:10]:
        quote = str(f.get("quote") or "").strip()
        p = agent.quote_page(pages, str(f.get("url") or ""), quote, quote_in_text)
        if p is None:
            dropped["quote_not_on_page"] += 1
            continue
        host = urlsplit(p["url"]).netloc.lower()
        text = p["title"] + "\n" + p["text"]
        loc = counties.mentions(text, h["local_terms"]) or ([h["site"]] if host.endswith(h["site"]) else [])
        yta = counties.mentions(text, h["yta_terms"]) or [s for s in (h.get("uni_sites") or []) if host.endswith(s)]
        if not loc and not yta:
            dropped["not_about_this_county"] += 1
            continue
        date = f.get("date")
        date = str(date).strip() if date else None
        if date:
            m = re.match(r"^(\d{4})(-\d{2}){0,2}$", date)
            if not m or (m.group(1) not in p["text"] and m.group(1) not in str(p.get("published") or "")):
                date = None
        rel = f.get("relates_to")
        if any(x["quote"] == quote for x in out):
            continue
        out.append({
            "date": date, "what_en": str(f.get("what_en") or "").strip(), "what_fi": str(f.get("what_fi") or "").strip(),
            "quote": quote, "url": p["url"], "title": p["title"], "relates_to": rel if rel in ids else None,
            "scope": "county" if loc else "collaborative_area", "fetched_at": p["fetched_at"],
            "from_cache": bool(p.get("from_cache")),
        })
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"findings": out[:MAX_FINDINGS], "findings_dropped": dropped,
            "summary_en": str(ans.get("summary_en") or "").strip(),
            "not_found_en": str(ans.get("not_found_en") or "").strip()}


def scout(area_id: str, on_event=None, budget_s: float = BUDGET_S, max_rounds: int = MAX_ROUNDS) -> dict:
    """Never raises for web or model trouble: returns `findings: []` with an `error` field."""
    t0 = time.time()
    h = counties.hints(area_id)
    if h is None:
        raise ValueError(f"unknown county id {area_id!r} (the scout works per county, not for the whole country)")
    ivs = _interventions()
    ids = [i["id"] for i in ivs] + list(STAGES)
    base = {
        "area_id": area_id, "area_name_en": h["name_en"], "area_name_fi": h["name_fi"],
        "question": f"What is {h['name_en']} doing about lung cancer care right now?",
        "findings": [], "summary_en": "", "not_found_en": "", "trace": [], "rounds": 0, "searches": 0,
        "pages_read": [], "model": llm.default_model(), "models": [], "search_backend": "oxylabs-web-api", "budget_s": budget_s,
        "from_cache": False, "checked_at": _now(),
    }
    try:
        if not oxylabs.has_credentials():
            raise oxylabs.OxylabsAuthError("JUNCTION_OXYLABS_API_KEY is not set; live search is unavailable")
        if not llm.any_ready():
            raise llm.NoModel("no model is connected: Claude is not reachable and GEMINI_API_KEY is not set")
        measures = "\n".join(f"- {i['id']}: {i.get('name_en')}" for i in ivs)
        stages = "\n".join(f"- {k}: {v}" for k, v in STAGES.items())
        task = (
            f"County: {h['name_fi']} ({h['name_en']}). Names a local page would use: {h['brand']}, {h['short_fi'] or h['name_fi']}; "
            f"main city {h['city']}; hospitals: {', '.join(h['hospitals'])}. Its site is probably {h['site']} (a guess; check by searching).\n"
            f"University hospital area: {h['uni_hospital']} in {h['uni_city']}"
            + (f" (its pages are on {' or '.join(h['uni_sites'])})" if h.get("uni_sites") else "") + ".\n\n"
            f"Kello measures (for relates_to):\n{measures}\n\nCare-path stages (for relates_to):\n{stages}\n\n"
            f"Today: {_now()[:10]}. Budget: {int(budget_s)} seconds in total and at most {max_rounds} search rounds, so work in parallel."
        )

        def review(draft: dict, pages: dict) -> str | None:
            got = _settle(draft, pages, h, set(ids))
            n = len(got["findings"])
            if n < 4:
                return (f"only {n} finding(s) would survive the checks (quote literally on the page, page names the county). "
                        "Look for decisions, projects, waiting-time figures or news you have not searched for yet.")
            hosts = {urlsplit(f["url"]).netloc.lower().removeprefix("www.") for f in got["findings"]}
            if len(hosts) == 1:
                return (f"all {n} findings come from one site ({next(iter(hosts))}), so they describe the service as it is, not what "
                        "is changing. Search for a decision, a project, an investment, a waiting-time figure or dated local news "
                        "(aluehallitus, hanke, investointi, uutinen, this year) and read two or three of the results.")
            return None

        focus = "keuhkosyöpä keuhkosyövän syöpä hoitopolku hoitoonpääsy hoitoketju diagnostiikka leikkaus sädehoito seulonta hanke päätös " \
                + " ".join(h["local_terms"] + h["hospitals"])
        run = agent.run(_SYSTEM, task, _finish_tool(ids), focus_terms=focus, max_rounds=max_rounds,
                        budget_s=budget_s, on_event=on_event, review=review)
        base.update(trace=run["trace"], rounds=run["rounds"], searches=run["searches"], stopped=run["stopped"],
                    model=run["model"], models=run["models"])
        seen = set()
        for p in run["pages"].values():
            if id(p) in seen:
                continue
            seen.add(id(p))
            base["pages_read"].append({"url": p["url"], "title": p["title"], "chars": p["chars"], "kind": p.get("kind"),
                                       "from_cache": bool(p.get("from_cache")), "fetched_at": p["fetched_at"]})
        if run["answer"] is None:
            raise RuntimeError("the time budget ran out before an answer was written")
        base.update(_settle(run["answer"], run["pages"], h, set(ids)))
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        base["summary_en"] = base["summary_en"] or "Could not complete the scout."
    base["seconds"] = round(time.time() - t0, 1)
    base["checked_at"] = _now()
    if "error" in base:
        old = from_store(area_id, base["error"])
        if old is not None:
            old["live_trace"] = base["trace"]
            return old
    else:
        try:
            STORE.mkdir(parents=True, exist_ok=True)
            f = STORE / f"{re.sub(r'[^A-Za-z0-9]', '', area_id)}.json"
            # Runs differ (other search results, a slow page): within 24 h a run with fewer findings
            # does not replace a stored run with more.
            old = latest(area_id)
            if not (old and len(old.get("findings") or []) > len(base["findings"]) and time.time() - f.stat().st_mtime < 86400):
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(f)
        except OSError:
            pass
    return present(base)


def present(res: dict) -> dict:
    """Add what the page shows on top of the stored result: which Oxylabs endpoints were used and what was searched."""
    from .verify import endpoints_used, searched

    res = dict(res)
    res["endpoints_used"] = endpoints_used(res.get("trace") or [])
    res["searched_en"], res["queries"] = searched(res.get("trace") or [], res.get("pages_read") or [])
    res.setdefault("from_cache", False)
    return res


def stored(area_id: str) -> dict | None:
    f = STORE / f"{re.sub(r'[^A-Za-z0-9]', '', area_id or '')}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest(area_id: str) -> dict | None:
    """The stored result for the county, with the page's extra fields; None if there is none."""
    old = stored(area_id)
    return present(old) if old else None


def is_fresh(area_id: str, max_age_s: float = 86400.0) -> bool:
    old = stored(area_id)
    try:
        return bool(old) and (datetime.now(timezone.utc) - datetime.fromisoformat(old["checked_at"])).total_seconds() < max_age_s
    except (KeyError, ValueError, TypeError):
        return False


def from_store(area_id: str, live_error: str | None = None) -> dict | None:
    """The stored result marked as such: `from_cache: true`, its own `checked_at`, and why the live run did not answer."""
    old = latest(area_id)
    if not old:
        return None
    old["from_cache"] = True
    if live_error:
        from .verify import failure_en

        old["live_error"] = live_error
        old["live_error_en"] = failure_en(live_error)
        old["live_tried_at"] = _now()
    return old


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m integrations.scout")
    ap.add_argument("area_id", help="county id such as 21")
    ap.add_argument("--out", help="also write the JSON here")
    a = ap.parse_args(argv)

    def show(e: dict) -> None:
        if e.get("status") == "done":
            print(f'  [{e["step"]:>2}] r{e["round"]} {e["tool"]:<19} {str(e["input"])[:70]:<70} -> {e["result_en"][:110]} ({e["ms"]} ms)',
                  file=sys.stderr, flush=True)

    res = scout(a.area_id, on_event=show)
    js = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(js + "\n", encoding="utf-8")
    print(js)
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
