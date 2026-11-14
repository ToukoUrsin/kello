import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, EndpointUse, friendly, LiveJob, ScoutFinding, ScoutResult, sleep, TraceStep, VerifyResult, when } from "./lib";

/* The live web check and the county scout: an agent searches and reads pages through the Oxylabs Web API and answers
   with verbatim quotes. The steps are shown while they run, with the endpoint and the time each one took. */

/** Words a county director reads, never the raw verdict codes. */
const EFFECT: Record<string, [string, string]> = {
  supports: ["supported", "supported"], supported: ["supported", "supported"],
  weaker: ["weaker", "smaller than we assumed"], mixed: ["weaker", "smaller than we assumed"],
  contradicts: ["contradicted", "contradicted"], contradicted: ["contradicted", "contradicted"],
  not_found: ["not_found", "not found"],
};
export function effectWord(v: VerifyResult): [string, string] | null { const e = EFFECT[v.effect_check ?? v.verdict] ?? null; return e ? [e[0], lower1(v.effect_label_en) ?? e[1]] : v.effect_label_en ? ["not_found", lower1(v.effect_label_en)!] : null; }
const lower1 = (t?: string | null) => (t ? t.charAt(0).toLowerCase() + t.slice(1) : null);
export function inUseWord(v: VerifyResult, areaName: string): [string, string] | null {
  const l = v.in_use_label_en;
  switch (v.in_use_here) {
    case "yes": return ["yes", l ?? `Already in use in ${areaName}`];
    case "partly": return ["partly", l ?? `Partly in place in ${areaName}`];
    case "planned": return ["planned", l ?? `Planned in ${areaName}`];
    case "no_evidence": return ["none", l ?? `No sign of it in ${areaName} on the web today`];
    default: return null;
  }
}
/** A check takes the measure out of the plan only when the server says so; older stored checks carry no such field. */
export const movesOut = (v: VerifyResult) => (v.plan_effect ? v.plan_effect === "exclude" : v.in_use_here === "yes" && v.in_use_scope === "county");
/** What the check asks the reader to do with this line of the plan, as a short label in front of the server's sentence. */
export const ADVICE: Record<string, string> = { take_out: "Take it out", narrow: "Narrow it", check_first: "Ask first", keep: "Keep it" };
export const adviceWord = (v: VerifyResult) => ADVICE[v.advice ?? ""] ?? (v.plan_effect === "exclude" ? ADVICE.take_out : v.plan_effect === "flag" ? ADVICE.check_first : v.plan_effect === "keep" ? ADVICE.keep : null);
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
/** "6 of 6 actions checked against the web today: 2 narrow it, 2 ask first; 2 no public sign" - counts only, from the stored
 *  checks, by the same advice word the cards and the plan table show, so the header always adds up to the rows below it. */
export function checkCount(ids: string[], checks: Record<string, VerifyResult | undefined>, fi = false): string | null {
  const done = ids.map((id) => checks[id]).filter((v): v is VerifyResult => !!v && !!v.checked_at && !!(v.plan_effect || v.in_use_here));
  if (!done.length) return null;
  const today = done.every((v) => sameDay(new Date(v.checked_at), new Date()));
  const word = (v: VerifyResult) => (movesOut(v) ? "take_out" : v.advice === "narrow" ? "narrow" : v.plan_effect === "flag" || v.in_use_here === "partly" || v.in_use_here === "planned" ? "check_first" : "keep");
  const n = (w: string) => done.filter((v) => word(v) === w).length;
  const [out, narrow, ask, none] = [n("take_out"), n("narrow"), n("check_first"), n("keep")];
  const bits = fi
    ? [out ? `${out} jo käytössä, poistettu` : null, narrow ? `${narrow} rajaa` : null, ask ? `${ask} kysy ensin` : null, none ? `${none} ei julkista merkkiä` : null]
    : [out ? `${out} already in place, taken out` : null, narrow ? `${narrow} narrow it` : null, ask ? `${ask} ask first` : null, none ? `${none} not mentioned on any public page` : null];
  return fi ? `${done.length}/${ids.length} toimesta tarkistettu verkosta${today ? " tänään" : ""}: ${bits.filter(Boolean).join("; ")}`
    : `${done.length} of ${ids.length} actions checked against the web${today ? " today" : ""}: ${bits.filter(Boolean).join("; ")}`;
}
/** "Gemini" / "Claude", never a model id. */
export const modelName = (m?: string | null) => (!m ? null : /gemini/i.test(m) ? "Gemini" : /claude|opus|sonnet|haiku/i.test(m) ? "Claude" : null);
export const IN_USE_SHORT: Record<string, string> = { yes: "Already running here", partly: "Partly in place", planned: "Planned, not running yet", no_evidence: "No public page mentions it" };
const gistOf = (x?: { in_use_here?: string | null; advice?: string | null } | null) => [IN_USE_SHORT[x?.in_use_here ?? ""], ADVICE[x?.advice ?? ""]].filter(Boolean).join(" · ") || "No answer";
const dayShort = (iso?: string | null) => { const d = new Date(iso ?? ""); return Number.isNaN(d.getTime()) ? "the stored check" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };

/** What a live run did to the answer, in one place: replaced it (before -> after), kept the stored one, or failed. */
export function LiveOutcome({ v, retry }: { v: VerifyResult; retry?: () => void }) {
  const o = v.live_outcome;
  if (o === "replaced" && v.previous) {
    const was = gistOf(v.previous), now = gistOf(v);
    if (was === now) return <p className="small muted liveout">Same answer as the stored check of {dayShort(v.previous.checked_at)}: <b>{now}</b>. The plan stays as it is.</p>;
    return (
      <div className="vdiff" role="status">
        <div className="was"><span>Stored answer, {dayShort(v.previous.checked_at)}</span><s>{was}</s></div>
        <div className="now changed"><span>This run, {dayShort(v.checked_at)}</span><b>{now}</b><em> the plan follows</em></div>
      </div>
    );
  }
  if (o === "kept" && v.live_pinned) {
    const now = gistOf(v.live_candidate), was = gistOf(v);
    return <p className="small liveout" role="status">{now === was ? <>This run gave the same answer as the stored check of {dayShort(v.checked_at)}: <b>{was}</b>.</> : <>This run read it as <b>{now}</b>. The plan keeps the stored check of {dayShort(v.checked_at)} (<b>{was}</b>) so every screen shows one answer; the hospital settles it in week 1.</>}</p>;
  }
  if (o === "kept") return <p className="small liveout" role="status">This run found less than the stored check of {dayShort(v.checked_at)}, so the answer stays: <b>{ADVICE[v.advice ?? ""] ?? gistOf(v)}</b>.</p>;
  if (o === "failed") return <p className="small liveout readerr" role="status">The live run did not finish ({v.live_error_en ?? "the search or the model failed"}), so this is the stored check of {dayShort(v.checked_at)}.{retry && <> <button className="btn sm" onClick={retry}>Try again</button></>}</p>;
  return null;
}
const SCOPE: Record<string, string> = { county: "named for this county", collaborative_area: "named for the university hospital area, not the county", national: "a national programme that does not name this county" };

const isSearch = (t: TraceStep) => /search/i.test(t.tool ?? "");
const isRead = (t: TraceStep) => /scrape|read|fetch|open/i.test(t.tool ?? "");
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : w.endsWith("ch") ? "es" : "s"}`;
export const host = (u?: string | null) => { try { return new URL(u ?? "").hostname.replace(/^www\./, ""); } catch { return u ?? ""; } };
const text = (x: unknown): string => (typeof x === "string" ? x : x && typeof x === "object" ? String((x as Record<string, unknown>).query ?? (x as Record<string, unknown>).url ?? "") : "");
const secs = (ms?: number) => (ms == null ? "" : ms >= 950 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
const toolName = (t: TraceStep) => (/claude|gemini/i.test(t.tool ?? "") ? modelName(t.model) ?? modelName(t.tool) ?? "Model" : (t.tool ?? "").replace(/^oxylabs/i, "Oxylabs"));
/** What a step does, in plain words, before the endpoint that did it. */
export const stepLabel = (t: TraceStep) => (isSearch(t) ? "Searching Finnish hospital and county sites" : isRead(t) ? "Reading a page" : /claude|gemini/i.test(t.tool ?? "") ? `${modelName(t.model) ?? modelName(t.tool) ?? "The model"} reads what was found` : "");

function Endpoints({ rows }: { rows?: EndpointUse[] | null }) {
  if (!rows?.length) return null;
  return (
    <ul className="endpoints small">
      {rows.map((e, i) => (
        <li key={i}><b className="num">{e.api ? `${e.api} · ` : ""}{e.endpoint}</b> <span className="num muted">{e.calls ?? 0} call{e.calls === 1 ? "" : "s"}{e.failed ? `, ${e.failed} failed` : ""}{e.from_cache ? `, ${e.from_cache} from stored pages` : ""}{e.js_render ? `, ${e.js_render} with JavaScript rendering` : ""}</span>{e.why_en ? <span className="muted"> · {e.why_en}</span> : null}</li>
      ))}
    </ul>
  );
}

/** "3 searches and 5 pages read through the Oxylabs Web API, in 34 s" */
function effort(v: { trace?: TraceStep[] | null; searches?: number | null; pages_read?: unknown[] | null; seconds?: number | null }): string | null {
  const tr = v.trace ?? [];
  const searches = v.searches ?? tr.filter(isSearch).length;
  const reads = tr.length ? tr.filter((t) => isRead(t) && !t.error).length : v.pages_read?.length ?? 0;
  if (!searches && !reads) return null;
  const bits = [searches ? plural(searches, "search") : null, reads ? `${plural(reads, "page")} read` : null].filter(Boolean).join(" and ");
  return `${bits} through the Oxylabs Web API${v.seconds ? `, in ${Math.round(v.seconds)} s` : ""}`;
}

/** One line per step: who did it (Claude, or the Oxylabs endpoint), what, what came back, how long. */
export function Trace({ steps, live = false }: { steps: TraceStep[]; live?: boolean }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => { if (live) end.current?.scrollIntoView({ block: "nearest" }); }, [steps.length, live]);
  if (!steps.length) return live ? <p className="small muted"><span className="spin" />Starting the agent</p> : null;
  return (
    <ol className={"trace" + (live ? " live" : "")}>
      {steps.map((t, i) => {
        const inp = text(t.input);
        const running = t.status === "running";
        return (
          <li key={i} className={(t.error ? "err" : "") + (running ? " run" : "")} ref={i === steps.length - 1 ? end : undefined}>
            <span className="tool num">{stepLabel(t) ? <><b className="slabel">{stepLabel(t)}</b> <span className="muted">{toolName(t)}</span></> : toolName(t)}</span>
            <span className="what">
              {isSearch(t) ? <>“{inp}”</> : isRead(t) ? (/^https?:/.test(inp) ? <a href={inp} target="_blank" rel="noreferrer">{host(inp)}{(() => { try { const p = new URL(inp).pathname; return p.length > 1 ? p.slice(0, 38) + (p.length > 38 ? "…" : "") : ""; } catch { return ""; } })()}</a> : inp) : inp}
              {t.result_en && !running ? <span className="muted"> → {t.result_en}</span> : null}
            </span>
            <span className="ms num">{running ? <span className="spin" aria-label="running" /> : `${secs(t.ms)}${t.from_cache ? " · stored page" : ""}`}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Follows a live run that runs as a job on the server. The run does not depend on this page's connection: steps arrive over
 *  a stream; on any stream error the page polls the job every 2 s (and reopens the stream once the poll answers), resuming
 *  from the last step it has. Steps already shown stay. When the job ends the result is fetched by id. Only a failure the
 *  server reports ends in `error`. */
export function useLiveRun<T>() {
  const [st, setSt] = useState<{ running: boolean; steps: TraceStep[]; result: T | null; error: string | null; waiting: boolean }>({ running: false, steps: [], result: null, error: null, waiting: false });
  const gen = useRef(0);
  const es = useRef<EventSource | null>(null);
  const dog = useRef<number | undefined>(undefined);
  useEffect(() => () => { gen.current++; es.current?.close(); window.clearInterval(dog.current); }, []);
  const start = useCallback((begin: () => Promise<LiveJob<T>>, onDone?: (r: T) => void) => {
    const my = ++gen.current;
    es.current?.close();
    window.clearInterval(dog.current);
    setSt({ running: true, steps: [], result: null, error: null, waiting: false });
    let id = "", next = 0, ended = false, misses = 0;
    const live = () => my === gen.current && !ended;
    const merge = (steps: TraceStep[]) => steps.length && setSt((p) => {
      const out = [...p.steps];
      for (const s of steps) { const i = out.findIndex((x) => x.step != null && x.step === s.step); if (i >= 0) out[i] = s; else out.push(s); }
      return { ...p, steps: out };
    });
    const stop = () => { es.current?.close(); window.clearInterval(dog.current); };
    const fail = (msg: string) => { if (!live()) return; ended = true; stop(); setSt((p) => ({ ...p, running: false, waiting: false, error: msg })); };
    const apply = (j: LiveJob<T>): boolean => {
      if (!live()) return true;
      merge(j.steps ?? []);
      next = Math.max(next, j.next ?? next);
      if (j.status === "done" && j.result) { ended = true; stop(); setSt((p) => ({ ...p, running: false, waiting: false, result: j.result! })); onDone?.(j.result); return true; }
      if (j.status === "failed") { fail(`The live run failed: ${j.error_en ?? "the search or the model failed"}.`); return true; }
      return false;
    };
    const poll = async () => {
      while (live()) {
        try {
          const j = await api.liveJob<T>(id, next);
          if (apply(j)) return;
          misses = 0;
          setSt((p) => (p.waiting ? { ...p, waiting: false } : p));
          listen();
          return;
        } catch (e) {
          if ((e as ApiError).status === 404) { fail("The live run was interrupted: the server restarted. Nothing was changed."); return; }
          if (++misses > 300) { fail("Kello has not answered for ten minutes. Check your connection and try again."); return; }
          setSt((p) => (p.waiting ? p : { ...p, waiting: true }));
        }
        await sleep(2000);
      }
    };
    const listen = () => {
      if (!live()) return;
      es.current?.close();
      const src = new EventSource(`/api/live/${id}/stream?since=${next}`);
      es.current = src;
      // The server sends something at least every 5 s. A connection that goes quiet for 15 s is dead even if
      // the browser has not noticed (a network switch, a sleeping laptop): drop it and follow the run by polling.
      let seen = Date.now();
      window.clearInterval(dog.current);
      dog.current = window.setInterval(() => {
        if (es.current !== src || !live()) return;
        if (Date.now() - seen > 15000) { src.close(); window.clearInterval(dog.current); setSt((p) => (p.waiting ? p : { ...p, waiting: true })); poll(); }
      }, 3000);
      const alive = () => { seen = Date.now(); };
      src.addEventListener("job", alive);
      src.addEventListener("ping", alive);
      src.addEventListener("step", (e) => { alive(); const s: TraceStep = JSON.parse((e as MessageEvent).data); next += 1; merge([s]); });
      // The stream says the run has ended: fetch the result by id (a poll that is retried like every request).
      src.addEventListener("done", () => { src.close(); window.clearInterval(dog.current); if (live()) poll(); });
      src.addEventListener("error", (e) => {
        src.close();
        window.clearInterval(dog.current);
        if (!live() || es.current !== src) return;
        const data = (e as MessageEvent).data;
        if (data) { let why = ""; try { why = JSON.parse(data).error_en ?? ""; } catch { /* plain */ } fail(`The live run failed${why ? `: ${why}` : ""}.`); return; }
        setTimeout(poll, 1000);   // the connection dropped, not the run: follow it by polling, then stream again
      });
    };
    begin().then((j) => { if (!live()) return; id = j.job_id; if (!apply(j)) listen(); }, (e) => fail(friendly(e)));
  }, []);
  return { ...st, start };
}

/** The answer of one check, in a director's words, with the quote, the link and the steps behind it. */
export function WebCheckResult({ v, areaName, children, fresh = false, lead = true }: { v: VerifyResult; areaName: string; children?: React.ReactNode; fresh?: boolean; lead?: boolean }) {
  const eff = effectWord(v);
  const use = inUseWord(v, areaName);
  const how = v.searched_en ? `${v.searched_en.replace(/\.$/, "")}${v.seconds ? `, in ${Math.round(v.seconds)} s` : ""}` : effort(v);
  const quotes = (v.sources ?? []).filter((s) => !(v.in_use_quote && s.quote === v.in_use_quote));
  const advice = adviceWord(v);
  if (v.verdict_en) {
    return (
      <div className="verify" role="status">
        <div className="vh"><b>Web check</b>
          {use && <span className={`inuse ${use[0]}`}>{use[1]}</span>}
          {eff && <span className={`verdict ${eff[0]}`}>assumed effect: {eff[1]}</span>}
          <span className="muted small num">{v.from_cache || v.live_outcome === "kept" ? `stored result from ${when(v.checked_at)}` : when(v.checked_at)}{modelName(v.model) ? ` · ${modelName(v.model)}` : ""}</span>
        </div>
        {lead && v.plan_effect_reason_en && <p className={"vadvice" + (fresh ? " new" : "")}>{advice ? <b>{advice}. </b> : null}{v.plan_effect_reason_en}</p>}
        <p className="vsum">{v.verdict_en}</p>
        {lead && v.in_use_quote && <blockquote>“{v.in_use_quote}”{v.in_use_source?.url ? <> <a href={v.in_use_source.url} target="_blank" rel="noreferrer">{v.in_use_source.title ?? host(v.in_use_source.url)}</a></> : null}</blockquote>}
        {children}
        {quotes.length > 0 && (
          <details className="vhow"><summary>{plural(quotes.length, "quote")} from the pages read</summary>
            {quotes.map((s, i) => (
              <blockquote key={i}>{s.quote && <>“{s.quote}” </>}<a href={s.url} target="_blank" rel="noreferrer">{s.title ?? host(s.url)}</a>{s.fetched_at && <span className="muted small"> · read {when(s.fetched_at)}</span>}</blockquote>
            ))}
          </details>
        )}
        {how && <details className="vhow"><summary>{how}</summary><Endpoints rows={v.endpoints_used} /><Trace steps={(v.trace ?? []).filter((t) => t.status !== "running")} /></details>}
      </div>
    );
  }
  return (
    <div className="verify" role="status">
      <div className="vh"><b>Web check</b><span className="muted small num">{when(v.checked_at)}</span></div>
      <dl className="vq">
        {use && (
          <div><dt>Is it already in place here?</dt>
            <dd>
              <span className={`inuse ${use[0]}`}>{use[1]}</span>
              {v.in_use_scope && SCOPE[v.in_use_scope] && v.in_use_here !== "no_evidence" ? <span className="small muted"> {SCOPE[v.in_use_scope]}</span> : null}
              {v.plan_effect_reason_en ? <p>{v.plan_effect_reason_en}</p> : v.in_use_summary_en ? <p>{v.in_use_summary_en}</p> : null}
              {v.in_use_quote && <blockquote>“{v.in_use_quote}”{v.in_use_source?.url ? <> <a href={v.in_use_source.url} target="_blank" rel="noreferrer">{v.in_use_source.title ?? host(v.in_use_source.url)}</a></> : null}</blockquote>}
            </dd>
          </div>
        )}
        {eff && <div><dt>The effect we assumed</dt><dd><span className={`verdict ${eff[0]}`}>{eff[1]}</span>{v.effect_summary_en ? <p>{v.effect_summary_en}</p> : null}</dd></div>}
      </dl>
      {!use && !eff && <p className="vsum">{v.summary_en || "The check did not finish."}</p>}
      {children}
      {v.unanswered_en ? <p className="small muted"><b>Still open:</b> {v.unanswered_en}</p> : null}
      {quotes.length > 0 && (
        <details className="vhow"><summary>{plural(quotes.length, "quote")} from the pages read</summary>
          {quotes.map((s, i) => (
            <blockquote key={i}>{s.quote && <>“{s.quote}” </>}<a href={s.url} target="_blank" rel="noreferrer">{s.title ?? host(s.url)}</a>{s.fetched_at && <span className="muted small"> · read {when(s.fetched_at)}</span>}</blockquote>
          ))}
        </details>
      )}
      {how && <details className="vhow"><summary>{how}</summary><Trace steps={(v.trace ?? []).filter((t) => t.status !== "running")} /></details>}
    </div>
  );
}

/* ---------- scout: what does this county already do or plan? ---------- */
const WHERE: Record<string, string> = { county: "this county", collaborative_area: "the university hospital area", national: "national" };
export function Finding({ f, bears }: { f: ScoutFinding; bears?: string | null }) {
  const meta = [f.date ? dateOnly(f.date) : "no date on the page", f.scope ? WHERE[f.scope] : null].filter(Boolean).join(" · ");
  return (
    <li>
      <span className="small muted num">{meta}</span>
      <p className="what">{f.what_en}</p>
      {f.quote && <blockquote>“{f.quote}”</blockquote>}
      <span className="small">{f.url && <a href={f.url} target="_blank" rel="noreferrer">{f.title ? `${f.title.slice(0, 70)}${f.title.length > 70 ? "…" : ""} (${host(f.url)})` : host(f.url)}</a>}{bears ? <span className="muted"> · bears on: {bears}</span> : null}</span>
    </li>
  );
}
const dateOnly = (d: string) => { const x = new Date(d); return Number.isNaN(x.getTime()) ? d : x.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };

/** The scout panel: stored findings, and a live run that shows every search and page as it happens. */
export function Scout({ scope, name, stored, onNew, bears, linked }: { scope: string; name: string; stored: ScoutResult | null; onNew: (r: ScoutResult) => void; bears: (id?: string | null) => string | null; linked: Set<string> }) {
  const run = useLiveRun<ScoutResult>();
  const go = () => run.start(() => api.scoutStart(scope), onNew);
  const data = run.result ?? (stored?.checked_at ? stored : null);
  const how = data ? (data.searched_en ? data.searched_en.replace(/\.$/, "") : effort(data)) : null;
  const rows = data?.findings ?? [];
  const rest = rows.filter((f) => !(f.relates_to && linked.has(f.relates_to)));
  return (
    <section className="panel" aria-label="What the county is already doing">
      <header>
        <h2>What is {name} already doing?</h2>
        <span className="small muted">{data?.checked_at ? (data.from_cache ? `Stored web search from ${when(data.checked_at)}` : `Web search, last run ${when(data.checked_at)}`) : "A web search of county and hospital pages"}</span>
        <div className="spacer" />
        <button className="btn sm" onClick={go} disabled={run.running}>{data ? "Search again" : "Search the web"}</button>
      </header>
      <div className="scoutbody">
        {run.running && <div className="livebox"><b>Searching now, through the Oxylabs Web API</b>{run.waiting && <p className="small muted">Waiting for the connection. The search goes on on the server; the steps catch up when the page reconnects.</p>}<Trace steps={run.steps} live /></div>}
        {data?.live_error_en && !run.running && run.result && <p className="small readerr">The live search did not finish ({data.live_error_en}), so these are the findings of {when(data.checked_at)}. <button className="btn sm" onClick={go}>Try again</button></p>}
        {run.error && <p className="small readerr">{run.error} {stored?.checked_at ? "The findings below are from the last run." : ""} <button className="btn sm" onClick={go}>Try again</button></p>}
        {!data && !run.running && !run.error && <p className="muted">No search has been run for {name} yet. An agent looks through county and hospital pages for pilots, decisions and capacity news; it takes about a minute.</p>}
        {data && !run.running && (
          <>
            {data.summary_en && <p>{data.summary_en}</p>}
            {rows.length === 0 && <p className="small muted">Nothing running or planned here was found on the pages read.</p>}
            {(rest.length > 0 || data.not_found_en || how) && (
              <details className="more flat">
                <summary>{rest.length > 0 ? `${plural(rest.length, "finding")}, each with its quote and link` : "What was searched"}{rows.length > rest.length ? <span className="muted"> {rows.length - rest.length} more shown on the action {rows.length - rest.length === 1 ? "it bears" : "they bear"} on</span> : null}</summary>
                {rest.length > 0 && <ul>{rest.map((f, i) => <Finding key={i} f={f} bears={bears(f.relates_to)} />)}</ul>}
                {data.not_found_en && <p className="small muted">Looked for and not found: {data.not_found_en}</p>}
                {how && <details className="vhow"><summary>{how}</summary><Endpoints rows={data.endpoints_used} /><Trace steps={(data.trace ?? []).filter((t) => t.status !== "running")} /></details>}
              </details>
            )}
          </>
        )}
      </div>
    </section>
  );
}
