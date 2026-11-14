import { useCallback, useEffect, useRef, useState } from "react";
import { EndpointUse, ScoutFinding, ScoutResult, TraceStep, VerifyResult, when } from "./lib";

/* The live web check and the county scout: an agent searches and reads pages through the Oxylabs Web API and answers
   with verbatim quotes. The steps are shown while they run, with the endpoint and the time each one took. */

/** Words a county director reads, never the raw verdict codes. */
const EFFECT: Record<string, [string, string]> = {
  supports: ["supported", "supported"], supported: ["supported", "supported"],
  weaker: ["weaker", "weaker than we assumed"], mixed: ["weaker", "weaker than we assumed"],
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
/** "6 of 6 actions checked against the web today: 4 partly in place, ask first; 2 no public sign" - counts only, from the stored checks. */
export function checkCount(ids: string[], checks: Record<string, VerifyResult | undefined>, fi = false): string | null {
  const done = ids.map((id) => checks[id]).filter((v): v is VerifyResult => !!v && !!v.checked_at && !!(v.plan_effect || v.in_use_here));
  if (!done.length) return null;
  const today = done.every((v) => sameDay(new Date(v.checked_at), new Date()));
  const n = (f: (v: VerifyResult) => boolean) => done.filter(f).length;
  const out = n(movesOut), flag = n((v) => !movesOut(v) && (v.plan_effect === "flag" || v.in_use_here === "partly")), planned = n((v) => !movesOut(v) && v.plan_effect !== "flag" && v.in_use_here === "planned");
  const none = done.length - out - flag - planned;
  const bits = fi
    ? [out ? `${out} jo käytössä, poistettu` : null, flag ? `${flag} osittain käytössä, kysy ensin` : null, planned ? `${planned} suunnitteilla` : null, none ? `${none} ei julkista merkkiä` : null]
    : [out ? `${out} already in place, taken out` : null, flag ? `${flag} partly in place, ask first` : null, planned ? `${planned} planned` : null, none ? `${none} no public sign` : null];
  return fi ? `${done.length}/${ids.length} toimesta tarkistettu verkosta${today ? " tänään" : ""}: ${bits.filter(Boolean).join("; ")}`
    : `${done.length} of ${ids.length} actions checked against the web${today ? " today" : ""}: ${bits.filter(Boolean).join("; ")}`;
}
const SCOPE: Record<string, string> = { county: "named for this county", collaborative_area: "named for the university hospital area, not the county", national: "a national programme that does not name this county" };

const isSearch = (t: TraceStep) => /search/i.test(t.tool ?? "");
const isRead = (t: TraceStep) => /scrape|read|fetch|open/i.test(t.tool ?? "");
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : w.endsWith("ch") ? "es" : "s"}`;
export const host = (u?: string | null) => { try { return new URL(u ?? "").hostname.replace(/^www\./, ""); } catch { return u ?? ""; } };
const text = (x: unknown): string => (typeof x === "string" ? x : x && typeof x === "object" ? String((x as Record<string, unknown>).query ?? (x as Record<string, unknown>).url ?? "") : "");
const secs = (ms?: number) => (ms == null ? "" : ms >= 950 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
const toolName = (t: TraceStep) => (/claude|gemini/i.test(t.tool ?? "") ? t.model ?? (t.tool ?? "").replace(/^./, (c) => c.toUpperCase()) : (t.tool ?? "").replace(/^oxylabs/i, "Oxylabs"));

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
            <span className="tool num">{toolName(t)}</span>
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

/** Runs a server-sent stream of `step` events that ends in `done` (the result) or `error`. */
export function useLiveRun<T>() {
  const [st, setSt] = useState<{ running: boolean; steps: TraceStep[]; result: T | null; error: string | null }>({ running: false, steps: [], result: null, error: null });
  const es = useRef<EventSource | null>(null);
  useEffect(() => () => es.current?.close(), []);
  const start = useCallback((url: string, onDone?: (r: T) => void) => {
    es.current?.close();
    setSt({ running: true, steps: [], result: null, error: null });
    const src = new EventSource(url);
    es.current = src;
    src.addEventListener("step", (e) => {
      const s: TraceStep = JSON.parse((e as MessageEvent).data);
      setSt((p) => { const i = p.steps.findIndex((x) => x.step === s.step); const steps = i >= 0 ? p.steps.map((x, j) => (j === i ? s : x)) : [...p.steps, s]; return { ...p, steps }; });
    });
    src.addEventListener("done", (e) => {
      const r: T = JSON.parse((e as MessageEvent).data);
      src.close();
      setSt((p) => ({ ...p, running: false, result: r }));
      onDone?.(r);
    });
    src.addEventListener("error", (e) => {
      const data = (e as MessageEvent).data;
      let msg = "The web check lost its connection before it finished.";
      if (data) { try { const j = JSON.parse(data); msg = /key|not connected|no_search/i.test(`${j.error} ${j.reason ?? ""}`) ? "The web search is not connected on this copy of Kello." : /rate|busy|429|503/i.test(`${j.error} ${j.detail ?? ""}`) ? "The web check is busy right now." : "The web check did not finish."; } catch { /* keep default */ } }
      src.close();
      setSt((p) => ({ ...p, running: false, error: msg }));
    });
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
          <span className="muted small num">{v.from_cache ? `stored result from ${when(v.checked_at)}` : when(v.checked_at)}{v.model ? ` · ${v.model}` : ""}</span>
        </div>
        {lead && v.plan_effect_reason_en && <p className={"vadvice" + (fresh ? " new" : "")}>{advice ? <b>{advice}. </b> : null}{v.plan_effect_reason_en}</p>}
        {v.previous && !v.live_candidate && (() => {
          const before = ADVICE[v.previous.advice ?? ""] ?? null;
          const day = v.previous.checked_at ? when(v.previous.checked_at) : "the stored check";
          if (before && advice && before !== advice) return <p className="small beforeafter"><span>Before, {day}: <b>{before}</b></span><span>Now: <b>{advice}</b></span></p>;
          return <p className="small muted">Same answer as the stored check of {day}{advice ? <>: <b>{advice}</b></> : null}. The plan stays as it is.</p>;
        })()}
        {v.live_candidate && <p className="small muted">This run found less than the stored check, so the stored answer stays.</p>}
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
        <button className="btn sm" onClick={() => run.start(`/api/scout/stream?area_id=${encodeURIComponent(scope)}`, onNew)} disabled={run.running}>{data ? "Search again" : "Search the web"}</button>
      </header>
      <div className="scoutbody">
        {run.running && <div className="livebox"><b>Searching now, through the Oxylabs Web API</b><Trace steps={run.steps} live /></div>}
        {run.error && <p className="small readerr">{run.error} {stored?.checked_at ? "The findings below are from the last run." : ""} <button className="btn sm" onClick={() => run.start(`/api/scout/stream?area_id=${encodeURIComponent(scope)}`, onNew)}>Try again</button></p>}
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
