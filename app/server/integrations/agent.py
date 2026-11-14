"""A small research agent: the model plans, Oxylabs fetches, the model decides what is still unanswered.

The model is Claude when available and Gemini otherwise (llm.py); every model step in
the trace says which one answered. It gets three tools and runs in a loop until it calls `finish`
or the budget is spent:

    search(query, country, why)  -> Oxylabs POST /v1/search   (live on every run, never cached)
    read(url, focus, why)        -> Oxylabs POST /v1/scrape   (main content, best passages for
                                    `focus`; pages cached on disk for 24 h)
    finish(...)                  -> the task's own answer schema

A "round" is one wave of searches plus the reads that follow it. Tool calls inside one model turn
run in parallel. Every call is recorded in `trace` and reported through `on_event` as it starts
and as it ends, so a UI can show the agent working.

    run(system, task, finish_tool, focus_terms=..., max_rounds=3, budget_s=60, on_event=None)
      -> {answer, trace, pages, rounds, seconds, stopped, searches, reads, model, models}

Trace entry: {step, round, tool ("oxylabs /v1/search" | "oxylabs /v1/scrape" | "claude" | "gemini"),
endpoint, input, url (the page, for reads), why, status, t_s, result_en, ms, ...}.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlsplit

from . import llm, oxylabs, pagetext

MODEL = llm.CLAUDE_MODEL
PASSAGE_CHARS = 4500   # what the model sees of one page per read (the full text stays for quote checks)
MAX_SEARCH_PER_TURN = 4
MAX_READ_PER_TURN = 5
FINISH_RESERVE_S = 16  # time kept back for the final answer
_SKIP = ("facebook.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "instagram.com",
         "reddit.com", "tiktok.com", "pinterest.com")

SEARCH_TOOL = {
    "name": "search",
    "description": (
        "Live web search (Oxylabs POST /v1/search). Returns up to 6 results: title, url, snippet. "
        "Snippets are cut short and can be stale: use them to choose what to read, never as evidence. "
        "One question per query, 3-9 words, no operators except an optional site:domain. Finnish "
        "public bodies answer Finnish queries. Call it several times in one turn to search in parallel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "country": {"type": "string", "description": "Two-letter country the search is run from. Default FI."},
            "why": {"type": "string", "description": "Which open part of the task this search is for, in under 12 words."},
        },
        "required": ["query", "why"],
        "additionalProperties": False,
    },
}
READ_TOOL = {
    "name": "read",
    "description": (
        "Read one web page or PDF (Oxylabs POST /v1/scrape). Returns the real page title and the "
        "passages of the main content that best match `focus` (navigation and cookie banners are "
        "removed; tables and numbers are kept). Read a page again with another `focus` to see other "
        "passages of it; that is free. PubMed and PMC links are read through Europe PMC. Call it "
        "several times in one turn to read pages in parallel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute URL, taken from a search result or from the task."},
            "focus": {"type": "string", "description": "Words to look for on the page, in the page's language (names, measures, units)."},
            "why": {"type": "string", "description": "Which open part of the task this page should answer, in under 12 words."},
        },
        "required": ["url", "focus", "why"],
        "additionalProperties": False,
    },
}


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _norm_url(url: str) -> str:
    u = (url or "").strip().split("#")[0]
    return u.rstrip("/").replace("http://", "https://").replace("://www.", "://")


class Run:
    """State of one agent run: trace, pages read, budget."""

    def __init__(self, focus_terms: str, budget_s: float, max_rounds: int, on_event=None):
        self.t0 = time.time()
        self.budget_s = budget_s
        self.max_rounds = max_rounds
        self.focus_terms = focus_terms
        self.on_event = on_event
        self.trace: list[dict] = []
        self.pages: dict[str, dict] = {}   # normalised url -> page (full text)
        self.rounds = 0
        self.searches = 0
        self.reads = 0
        self._step = 0
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=10)
        self._slow: dict[str, object] = {}  # normalised url -> the fetch that missed its deadline

    def left(self) -> float:
        return self.budget_s - (time.time() - self.t0)

    def _emit(self, entry: dict) -> None:
        if self.on_event:
            try:
                self.on_event(dict(entry))
            except Exception:
                pass

    def begin(self, tool: str, inp: str, **extra) -> dict:
        """`input` is one display string (the query, the URL, or what Claude is asked to do)."""
        with self._lock:
            self._step += 1
            e = {"step": self._step, "round": max(self.rounds, 1), "tool": tool, "input": inp, **extra,
                 "status": "running", "t_s": round(time.time() - self.t0, 1)}
        self._emit(e)
        return e

    def end(self, e: dict, result_en: str, t_start: float, **extra) -> None:
        if e.get("handover"):  # the model changed in the middle of the run: say so in the step itself
            result_en = f'{e["handover"]}. {result_en}'
        e.update(status="done", result_en=result_en, ms=int((time.time() - t_start) * 1000), **extra)
        with self._lock:
            self.trace.append(e)
        self._emit(e)

    def page_for(self, url: str) -> dict | None:
        return self.pages.get(_norm_url(url))

    # ---- tools

    def do_search(self, inp: dict) -> str:
        q = " ".join(str(inp.get("query") or "").split())
        country = (str(inp.get("country") or "FI").strip() or "FI")[:2].upper()
        e = self.begin("oxylabs /v1/search", q, endpoint="POST /v1/search", url=None, country=country, why=str(inp.get("why") or ""))
        t = time.time()
        try:
            hits = oxylabs.search(q, 8, country)
        except oxylabs.OxylabsAuthError:
            self.end(e, "the Oxylabs key was rejected", t, error=True)
            raise
        except Exception as exc:
            self.end(e, f"search failed: {str(exc)[:120]}", t, error=True)
            return f"Search failed: {str(exc)[:200]}. Try a different query."
        hits = [h for h in hits if not any(s in _host(h["url"]) for s in _SKIP)][:6]
        self.searches += 1
        if not hits:
            self.end(e, "0 results", t, results=[])
            return "No results. Try other words (shorter, or the other language)."
        lines = []
        for i, h in enumerate(hits, start=1):
            kind = " [PDF]" if h["url"].lower().split("?")[0].endswith(".pdf") else ""
            lines.append(f"{i}. {h['title'] or '(no title)'}{kind}\n   {h['url']}\n   {h['snippet'][:260]}")
        top = ", ".join(dict.fromkeys(_host(h["url"]) for h in hits[:4]))
        self.end(e, f"{len(hits)} results: {top}", t,
                 results=[{"url": h["url"], "title": h["title"]} for h in hits])
        return "\n".join(lines)

    def do_read(self, inp: dict, deadline_s: float) -> str:
        url = str(inp.get("url") or "").strip()
        focus = str(inp.get("focus") or "")
        e = self.begin("oxylabs /v1/scrape", url, endpoint="POST /v1/scrape", url=url, focus=focus, why=str(inp.get("why") or ""))
        t = time.time()
        if not url.startswith(("http://", "https://")):
            self.end(e, "not an absolute URL", t, error=True)
            return "Not an absolute http(s) URL."
        page = self.page_for(url)
        again = page is not None
        if page is None:
            # a page that timed out earlier in this run is still being fetched: wait for that fetch, briefly
            fut = self._slow.pop(_norm_url(url), None)
            retry = fut is not None
            if fut is None:
                fut = self._pool.submit(oxylabs.scrape, url, None, 45.0, True, max(3.0, deadline_s - 1.0))
            wait_s = min(6.0, deadline_s) if retry else max(3.0, deadline_s)
            done, _ = wait([fut], timeout=wait_s)
            if not done:
                # the scrape keeps running and lands in the 24 h page cache for the next click
                self._slow[_norm_url(url)] = fut
                self.end(e, f"no answer in {int(time.time() - t)} s; skipped" + (" (second try)" if retry else ""), t,
                         error=True, timeout=True)
                return "The page did not answer in time. Do not try this URL again; use another source."
            try:
                page = fut.result()
            except oxylabs.OxylabsAuthError:
                self.end(e, "the Oxylabs key was rejected", t, error=True)
                raise
            except Exception as exc:
                self.end(e, f"read failed: {str(exc)[:120]}", t, error=True)
                return f"Could not read the page: {str(exc)[:200]}"
            if not page["status"].startswith("ok") or not page["text"]:
                why = page["status"].replace("error: ", "")
                if "Value not supported" in why:
                    why = "this site is not supported by the scraper"
                self.end(e, f"could not read: {why[:110]}", t, error=True)
                return f"Could not read the page ({why[:200]}). Use another source."
            self.pages[_norm_url(url)] = page
            self.pages.setdefault(_norm_url(page["url"]), page)
            self.reads += 1
        bp = pagetext.best_passages(page["text"], pagetext.stems(focus + " " + self.focus_terms), PASSAGE_CHARS)
        cached = bool(page.get("from_cache")) or again
        bits = [f'"{page["title"][:70]}"', f'{page["chars"]:,} chars'.replace(",", " ")]
        if page.get("pages"):
            bits.append(f'PDF {page["pages"]} p.')
        if bp["total"] > 1:
            bits.append(f'{bp["kept"]} of {bp["total"]} passages kept')
        if page.get("direct"):
            bits.append("Europe PMC API, direct (the scraper stalled)")
        if cached:
            bits.append("from cache")
        self.end(e, " · ".join(bits), t, title=page["title"], chars=page["chars"], from_cache=cached,
                 kind=page.get("kind"), page_url=page["url"], url=page["url"], published=page.get("published"),
                 js_render=page.get("status") == "ok_js")
        head = f'<page url="{url}" title="{page["title"]}" kind="{page.get("kind", "html")}"'
        if page.get("published"):
            head += f' date_in_page_metadata="{page["published"]}"'
        head += f' fetched_at="{page["fetched_at"]}" chars_total="{page["chars"]}" passages_shown="{bp["kept"]}/{bp["total"]}">'
        more = ""
        # the page the task needs is often one click from the hub page a search returns
        near = pagetext.matching_links(page.get("links") or [], focus, 8)
        if near:
            more = ("\n<links_on_this_page note=\"links whose text or address matches your focus; read one if it is the page you need\">\n"
                    + "\n".join(f'- {l["text"] or "(no text)"}: {l["url"]}' for l in near) + "\n</links_on_this_page>")
        return f"{head}\n{bp['text']}\n</page>{more}"


def run(system: str, task: str, finish_tool: dict, *, focus_terms: str = "", max_rounds: int = 3,
        budget_s: float = 60.0, on_event=None, review=None, opening: list[dict] | None = None) -> dict:
    """Run the loop. Returns {answer (the finish input, or None), trace, pages, rounds, seconds,
    stopped: "finished"|"draft" (an earlier draft answer, the extra round ran out of time)|"budget"|
    "no_answer", searches, reads, model (the one that wrote the answer), models (all that answered)}.
    Raises on a bad Oxylabs key, or llm.NoModel when neither Claude nor Gemini answers."""
    st = Run(focus_terms, budget_s, max_rounds, on_event)
    chat = llm.Session(system, [SEARCH_TOOL, READ_TOOL, finish_tool])
    if opening:
        # Round 1 is the same for every run of this task, so it does not wait for the model: the
        # caller's opening searches run in parallel now and the model starts from their results.
        st.rounds = 1
        futs = [(q, st._pool.submit(st.do_search, q)) for q in opening[:MAX_SEARCH_PER_TURN]]
        shown = []
        try:
            for q, fut in futs:
                try:
                    shown.append(f'<search query="{q.get("query")}">\n{fut.result(timeout=40)}\n</search>')
                except oxylabs.OxylabsAuthError:
                    raise
                except Exception as exc:
                    shown.append(f'<search query="{q.get("query")}">\nSearch failed: {str(exc)[:160]}\n</search>')
        except BaseException:
            st._pool.shutdown(wait=False, cancel_futures=False)
            raise
        task += ("\n\nSearch round 1 has already been run for you; these are its results. Start by reading three to five of "
                 "them in ONE turn (parallel read calls)" + (", together with the evidence page listed above" if "Evidence we already hold" in task else "")
                 + f". {max_rounds - 1} more search round(s) are allowed after that.\n\n" + "\n\n".join(shown))
    chat.user(task)
    answer, stopped, turn, forced, reopened = None, "no_answer", 0, 0, False
    try:
        while turn < 9:
            turn += 1
            left = st.left()
            must_finish = left < FINISH_RESERVE_S + 4 or forced > 0
            e = st.begin(chat.provider, "decide the next step" if turn > 1 else "plan the first searches",
                         endpoint="model", url=None, model=chat.model)
            t = time.time()
            try:
                resp = chat.ask(max(20.0, min(60.0, left + 25.0)))
            except Exception as exc:
                st.end(e, f"no answer from the model: {str(exc)[:160]}", t, error=True)
                raise
            e.update(tool=resp.provider, model=resp.model)
            if resp.note:
                e["handover"] = resp.note
            calls = resp.calls
            for b in calls:  # the model sometimes prefixes a tool name ("review_search", "hero_read")
                if b.name not in ("search", "read", "finish"):
                    low = b.name.lower()
                    alias = "search" if "search" in low else "read" if ("read" in low or "scrape" in low or "fetch" in low) \
                        else "finish" if "finish" in low else None
                    if alias:
                        b.name = alias
            fin = next((b for b in calls if b.name == "finish"), None)
            if fin is not None:
                draft = dict(fin.input or {})
                # `review(draft, pages)` returns what is still open (a sentence) or None. While time and
                # search rounds remain, an answer with an open part is sent back for one more round.
                open_part = None
                if review and st.rounds < st.max_rounds and st.left() > FINISH_RESERVE_S + 12 and not must_finish:
                    try:
                        open_part = review(draft, st.pages)
                    except Exception:
                        open_part = None
                if not open_part:
                    st.end(e, "writes the answer", t)
                    answer, stopped = draft, "finished"
                    break
                answer = draft  # kept in case the next round runs out of time
                st.rounds += 1  # the extra round starts here, whether it opens with a search or a read
                reopened = True
                st.end(e, f"draft answer, still open: {open_part}"[:300], t)
                msg = (f"Not finished yet. Still open: {open_part} You have about {int(st.left() - FINISH_RESERVE_S)} s and "
                       "one more search round, starting now. Search again for exactly that with different words "
                       "(a new search is expected, not only another read), read what you find, then call finish again "
                       "with the complete answer. If it is still not there, say so: that is a valid result.")
                chat.results([(b, msg, False) if b.id == fin.id else (b, "Not run: it was sent together with finish.", True)
                              for b in calls])
                continue
            if not calls:
                if st.searches == 0 and st.reads == 0 and not must_finish and turn <= 2:
                    st.end(e, "wrote a plan without calling a tool", t)
                    chat.user("Do not describe the plan: send the search and read tool calls now.")
                    continue
                st.end(e, "answered without calling finish", t, error=True)
                chat.user("Call the finish tool now with your answer.")
                forced += 1
                if forced > 2:
                    break
                continue
            searches = [b for b in calls if b.name == "search"]
            reads = [b for b in calls if b.name == "read"]
            unknown = sorted({b.name for b in calls if b.name not in ("search", "read")})
            if reopened:  # this turn belongs to the round the review opened
                new_round, reopened = bool(searches) and not must_finish, False
            else:
                new_round = bool(searches) and st.rounds < st.max_rounds and not must_finish
                if new_round or st.rounds == 0:
                    st.rounds += 1
            whys = "; ".join(dict.fromkeys(str(b.input.get("why") or "").strip() for b in calls if b.input.get("why")))
            plan = []
            if searches:
                plan.append(f"{len(searches)} search" + ("es" if len(searches) > 1 else ""))
            if reads:
                plan.append(f"{len(reads)} read" + ("s" if len(reads) > 1 else ""))
            if unknown:
                plan.append("unknown tool " + ", ".join(unknown))
            e["round"] = st.rounds
            st.end(e, (" + ".join(plan) + (": " + whys if whys else ""))[:300], t)

            results: dict[str, tuple[str, bool]] = {}
            jobs = {}
            read_deadline = max(4.0, min(20.0, st.left() - FINISH_RESERVE_S))
            n_s = n_r = 0
            for b in calls:
                if must_finish:
                    results[b.id] = ("The time budget is spent. Call finish now with what you have.", True)
                elif b.name == "search":
                    n_s += 1
                    if searches and not new_round:
                        results[b.id] = (f"All {st.max_rounds} search rounds are used. Read pages you already found, or call finish.", True)
                    elif n_s > MAX_SEARCH_PER_TURN:
                        results[b.id] = (f"At most {MAX_SEARCH_PER_TURN} searches per turn.", True)
                    else:
                        jobs[st._pool.submit(st.do_search, dict(b.input or {}))] = b
                elif b.name == "read":
                    n_r += 1
                    if n_r > MAX_READ_PER_TURN:
                        results[b.id] = (f"At most {MAX_READ_PER_TURN} reads per turn.", True)
                    else:
                        jobs[st._pool.submit(st.do_read, dict(b.input or {}), read_deadline)] = b
                else:
                    results[b.id] = (f"Unknown tool {b.name!r}. The tools are search, read and finish.", True)
            for fut, b in jobs.items():
                try:
                    results[b.id] = (fut.result(timeout=read_deadline + 30), False)
                except oxylabs.OxylabsAuthError:
                    raise
                except Exception as exc:
                    results[b.id] = (f"Tool failed: {str(exc)[:200]}", True)
            if must_finish:
                forced += 1
                if forced > 2:
                    break
            left = st.left()
            rounds_left = st.max_rounds - st.rounds
            if left < FINISH_RESERVE_S + 4:
                note = "Budget: the time is spent. Call finish now; other tool calls will be refused."
                forced = max(forced, 1)
            else:
                note = (f"Budget: about {int(left - FINISH_RESERVE_S)} s of searching and reading left; "
                        f"{rounds_left} more search round{'s' if rounds_left != 1 else ''} allowed "
                        f"(reads of pages you already found are always allowed). ")
                if searches and any(not results[b.id][1] for b in searches):
                    note += ("Next: read three to five of these results in ONE turn (parallel read calls). "
                             "One read per turn wastes the budget.")
                elif rounds_left > 0 and left - FINISH_RESERVE_S > 14:
                    note += ("Next: name the part of the task that is still unanswered. If there is one, send new searches "
                             "for exactly that now, with different words, and do not call finish yet. "
                             "Call finish only when every part is answered.")
                else:
                    note += "Next: read one more page you already found if it is likely to answer an open part, else call finish."
            chat.results([(b, results[b.id][0], results[b.id][1]) for b in calls], note)
        if stopped != "finished":
            stopped = "draft" if answer is not None else ("budget" if st.left() < FINISH_RESERVE_S + 4 else "no_answer")
    finally:
        st._pool.shutdown(wait=False, cancel_futures=False)
    st.trace.sort(key=lambda x: x["step"])
    return {"answer": answer, "trace": st.trace, "pages": st.pages, "rounds": st.rounds,
            "seconds": round(time.time() - st.t0, 1), "stopped": stopped, "searches": st.searches,
            "reads": st.reads, "model": chat.models[-1] if chat.models else chat.model, "models": list(chat.models)}


def quote_page(st_pages: dict[str, dict], url: str, quote: str, quote_in_text) -> dict | None:
    """The page a quote really comes from: the URL the model named if the quote is literally in
    its text, else any other page read in this run that contains it. None when no page does."""
    p = st_pages.get(_norm_url(url))
    if p and quote_in_text(quote, p["text"]):
        return p
    for other in st_pages.values():
        if quote_in_text(quote, other["text"]):
            return other
    return None
