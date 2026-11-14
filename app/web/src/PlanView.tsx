import { StudyLine } from "./StudyLine";
import { Fragment, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, AreaMeta, ChartRead, eurFi, eurx, fiNumbers, friendly, one, Plan, ReportJob, ReportResult, ReportRow, useAsync, when, whenFi, VerifyResult, OptResult } from "./lib";
import { adviceWord, checkCount, host } from "./WebCheck";
import { Failed } from "./App";
import { PilotFigures, pilotText } from "./Pilot";
import type { Lang } from "./App";

const PRESETS = [500_000, 1_000_000, 2_000_000];
const CITE = /\[\^([^\]\s]+)\]/g;
/** Reviewer text as plain words: no citation markers, no Markdown marks. */
const plain = (t: string) => t.replace(/\s?\[\^[^\]\s]+\]/g, "").replace(/\*\*|__|`/g, "").replace(/\s+/g, " ").trim();
/** Keep what the reviewer changed and why; drop sentences where the model talks about itself. */
const reason = (t: string) => plain(t).split(/(?<=[.!?])\s+/).filter((s) => !/\b(I|I've|I'm|my)\b|obviously|as instructed|the draft's/.test(s)).join(" ");
const OBJ: Record<string, string> = { curative: "most patients treated to cure", gap: "closing the gap to Finland", deaths: "most deaths avoided" };
const T = {
  en: { doc: "county plan", national: "national plan", retrieved: "retrieved", unverified: "listed, not opened by us", sample: "TEMPLATE TEXT", sources: "Sources", year: "a year", ceiling: "budget",
    zero: "Enter a budget above €0 to write a plan.", without: "Left out of this plan",
    stages: [["material", "Collecting the county's numbers"], ["writing", "Claude writes the page"], ["reviewing", "A second pass checks every sentence against the sources"]] },
  fi: { doc: "hyvinvointialueen suunnitelma", national: "kansallinen suunnitelma", retrieved: "haettu", unverified: "listattu, emme avanneet", sample: "MALLIPOHJAN TEKSTI", sources: "Lähteet", year: "vuodessa", ceiling: "budjettikatto",
    zero: "Anna budjetti, joka on suurempi kuin 0 €.", without: "Jätetty pois tästä suunnitelmasta",
    stages: [["material", "Kootaan alueen luvut"], ["writing", "Claude kirjoittaa sivun"], ["reviewing", "Toinen kierros tarkistaa jokaisen lauseen lähteistä"]] },
} as const;

/** Minimal Markdown for the plan: headings, lists, paragraphs, bold, the summary strip (>), tables, and [^id] citations as numbered footnotes. */
function renderPlan(md: string, toFootnote: (n: number) => void, under?: (no: string) => ReactNode, afterStrip?: ReactNode): { nodes: ReactNode[]; order: string[] } {
  const order: string[] = [];
  const num = (id: string) => { let i = order.indexOf(id); if (i < 0) { order.push(id); i = order.length - 1; } return i + 1; };
  const inline = (text: string, key: string): ReactNode[] => {
    const out: ReactNode[] = [];
    const parts = text.split(/(\*\*[^*]+\*\*|(?:\s?\[\^[^\]\s]+\])+)/g);
    let boldText: string | null = null; // the bold run just before, if a footnote follows it directly
    parts.forEach((p, i) => {
      if (!p) return;
      if (p.startsWith("**") && p.endsWith("**")) { boldText = p.slice(2, -2); out.push(<strong key={key + i}>{boldText}</strong>); }
      else if (/^\s?\[\^/.test(p)) {
        const ids = [...p.matchAll(CITE)].map((m) => m[1]);
        // Buttons, not #fn links: the app's own routing lives in the hash, so a hash link would leave the plan.
        // The last word before a footnote number travels with it, so a number never starts a line on its own.
        const prev = out[out.length - 1];
        let word: string | null = null;
        if (typeof prev === "string") { const m = /^([\s\S]*\s)?(\S+)$/.exec(prev); if (m) { word = m[2]; if (m[1]) out[out.length - 1] = m[1]; else out.pop(); } }
        let bold = false;
        if (word == null && boldText != null) { const m = /^([\s\S]*\s)?(\S+)$/.exec(boldText); if (m) { word = m[2]; bold = true; if (m[1]) out[out.length - 1] = <strong key={key + i + "h"}>{m[1]}</strong>; else out.pop(); } }
        const sup = (<sup key={key + i}>{ids.map((id, j) => { const n = num(id); return <Fragment key={id}>{j > 0 && ","}<button type="button" className="fnref" onClick={() => toFootnote(n)} aria-label={`Source ${n}`}>{n}</button></Fragment>; })}</sup>);
        out.push(word ? <span key={key + i + "w"} className="nb">{bold ? <strong>{word}</strong> : word}{sup}</span> : sup);
        boldText = null;
      } else { out.push(p); boldText = null; }
    });
    return out;
  };
  const nodes: ReactNode[] = [];
  let list: { type: "ol" | "ul"; items: string[] } | null = null;
  let para: string[] = [];
  let table: string[][] = [];
  let gap = false;
  let olSeen = 0; // numbered items so far in this section: a list split by a paragraph keeps counting 1..n
  const cells = (line: string) => line.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const flush = (k: number) => {
    if (para.length) { nodes.push(<p key={"p" + k}>{inline(para.join(" "), "p" + k)}</p>); para = []; }
    if (list) {
      const items = list.items.map((it, i) => <li key={i}>{inline(it, `l${k}-${i}`)}</li>);
      if (list.type === "ol") { nodes.push(<ol key={"l" + k} start={olSeen + 1}>{items}</ol>); olSeen += list.items.length; }
      else nodes.push(<ul key={"l" + k}>{items}</ul>);
      list = null;
    }
    if (table.length) {
      const [headRow, ...rest] = table;
      const body = rest.filter((r) => !r.every((c) => /^:?-+:?$/.test(c)));
      const numeric = (i: number) => i > 0 && body.some((r) => r[0] !== "" && /^[€\d−-]/.test(r[i] ?? "") && (r[i] ?? "").length < 26);
      nodes.push(
        <table key={"t" + k} className={`ptable c${headRow.length}`}>
          <thead><tr>{headRow.map((h, i) => <th key={i} className={numeric(i) ? "n" : ""}>{h}</th>)}</tr></thead>
          <tbody>
            {body.map((r, j) => {
              // A row with only its second cell filled is a group heading; an unnumbered row with more is the total.
              if (r[0] === "" && r.slice(2).every((c) => !c)) return <tr key={j} className="grp"><td colSpan={headRow.length}>{inline(r[1] ?? "", `t${k}-${j}`)}</td></tr>;
              // Today's web check gets its own full-width line under the action, so it never squeezes the columns.
              const note = r[0] !== "" ? under?.(r[0]) : null;
              return (
                <Fragment key={j}>
                  <tr className={(r[0] === "" ? "tot" : "") + (note ? " noted" : "")}>
                    {r.map((c, i) => <td key={i} className={(numeric(i) ? "n " : "") + (i === 0 ? "no" : "")} data-label={i > 1 && c ? headRow[i] : undefined}>{inline(c, `t${k}-${j}-${i}`)}</td>)}
                  </tr>
                  {note && <tr className="wn"><td /><td colSpan={headRow.length - 1}>{note}</td></tr>}
                </Fragment>
              );
            })}
          </tbody>
        </table>);
      table = [];
    }
  };
  md.split("\n").forEach((raw, k) => {
    const line = raw.trim();
    const ol = /^(\d+)[.)]\s+(.*)$/.exec(line), ul = /^[-*]\s+(.*)$/.exec(line);
    if (line.startsWith("|")) { if (para.length || list) flush(k); table.push(cells(line)); return; }
    if (table.length) flush(k);
    // a blank line between numbered items must not restart the numbering
    if (!line) { if (para.length) flush(k); gap = !!list; return; }
    if (gap) { if (!(list && ((ol && list.type === "ol") || (ul && list.type === "ul")))) flush(k); gap = false; }
    if (line.startsWith("## ")) { flush(k); olSeen = 0; nodes.push(<h2 key={"h" + k}>{inline(line.slice(3), "h" + k)}</h2>); }
    else if (line.startsWith("# ")) { flush(k); olSeen = 0; nodes.push(<h1 key={"h" + k}>{inline(line.slice(2), "h" + k)}</h1>); }
    else if (line.startsWith("> ")) { flush(k); const bits = line.slice(2).split(" · "); nodes.push(<p key={"s" + k} className="strip num">{bits.map((b, i) => (i === 0 ? <b key={i}>{b}</b> : <span key={i}>{b}</span>))}</p>); if (afterStrip) nodes.push(<Fragment key={"as" + k}>{afterStrip}</Fragment>); }
    else if (ol) { if (para.length || (list && list.type !== "ol")) flush(k); (list ??= { type: "ol", items: [] }).items.push(ol[2]); }
    else if (ul) { if (para.length || (list && list.type !== "ul")) flush(k); (list ??= { type: "ul", items: [] }).items.push(ul[1]); }
    else if (list) list.items[list.items.length - 1] += " " + line;
    else para.push(line);
  });
  flush(99999);
  return { nodes, order };
}

/** A query string of several hundred characters does not belong on a printed page: the link keeps it, the text shows where it goes. */
const shortUrl = (u: string) => { if (u.length <= 100) return u; try { const x = new URL(u); return `${x.origin}${x.pathname}${x.search ? "?…" : ""}`; } catch { return `${u.slice(0, 96)}…`; } };
const dayOf = (iso: string) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };

/** Grey blocks in the shape of the plan: title, summary strip, two short sections, the action table, the rest. */
function PlanSkeleton({ rest = false }: { rest?: boolean }) {
  const bar = (h: number, w: number, mb = 10) => <div className="skeleton" style={{ height: h, width: `${w}%`, marginBottom: mb }} />;
  return (
    <div aria-hidden="true" className="planskel">
      {!rest && <>{bar(28, 78, 14)}{bar(46, 100, 22)}{bar(14, 26, 10)}{bar(12, 96)}{bar(12, 70, 22)}{bar(14, 18, 10)}{bar(12, 100)}{bar(12, 84, 22)}</>}
      {bar(14, 24, 10)}
      {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skrow">{bar(40, 100, 6)}</div>)}
      {bar(14, 34, 10)}{bar(12, 92)}{bar(12, 88)}{bar(12, 60, 20)}{bar(14, 30, 10)}{bar(12, 96)}{bar(12, 74)}
    </div>
  );
}

/** Stored English plan text names university hospital areas by acronym ("the Northern Finland (OYS) collaborative area");
 *  the page names them by city, at render time, without touching the stored text. */
const YTA_CITY: Record<string, string> = { HUS: "Helsinki", TYKS: "Turku", TAYS: "Tampere", KYS: "Kuopio", OYS: "Oulu" };
const plainAreas = (t: string) => t
  .replace(/\b(the )?(?:[A-Z][a-z]+ Finland )?\((HUS|TYKS|TAYS|KYS|OYS)\) collaborative area/g, (_m, the, y) => `${the ?? ""}${YTA_CITY[y]} university hospital area`)
  .replace(/\b(HUS|TYKS|TAYS|KYS|OYS) collaborative area/g, (_m, y) => `${YTA_CITY[y]} university hospital area`)
  .replace(/collaborative area \(university hospital\)/g, "university hospital area")
  .replace(/collaborative area \((HUS|TYKS|TAYS|KYS|OYS)\)/g, (_m, y) => `${YTA_CITY[y]} university hospital area`)
  .replace(/collaborative area/g, "university hospital area")
  .replace(/\bOYS\b/g, "Oulu university hospital");

interface Props { scope: string; budget: number; setBudget: (n: number) => void; lang: Lang; setLang: (l: Lang) => void; objective: string | null; without: string[]; areas: AreaMeta[]; openCounty: () => void }

export default function PlanView({ scope, budget, setBudget, lang, setLang, objective, without, areas, openCounty }: Props) {
  const [stage, setStage] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fn, setFn] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const es = useRef<EventSource | null>(null);
  const ivs = useAsync(api.interventions, []);
  const opt = useAsync<OptResult>(() => api.optimize(scope, budget, objective), [scope, budget, objective]);
  const t = T[lang];
  const area = areas.find((a) => a.id === scope);
  const nameEn = scope === "FI" ? "Finland" : area?.short_en ?? scope;
  const name = lang === "fi" ? (scope === "FI" ? "Suomi" : area?.name_fi ?? area?.short_fi ?? scope) : scope === "FI" ? "Finland" : area?.name_en ?? nameEn;
  const key = without.join(",");

  const run = useCallback((refresh = false) => {
    es.current?.close();
    setPlan(null); setDraft(""); setError(null);
    if (budget <= 0) { setStage(null); return; }
    setStage("material");
    const q = new URLSearchParams({ budget_eur: String(budget), lang });
    if (objective) q.set("objective", objective);
    if (key) q.set("without", key);
    if (refresh) q.set("refresh", "true");
    const src = new EventSource(`/api/plan/${scope}/stream?${q}`);
    es.current = src;
    src.addEventListener("status", (e) => setStage(JSON.parse((e as MessageEvent).data).stage));
    src.addEventListener("delta", (e) => setDraft((d) => d + JSON.parse((e as MessageEvent).data).text));
    src.addEventListener("done", (e) => { const p: Plan = JSON.parse((e as MessageEvent).data); setPlan(p); setStage(null); api.notePlan(p.fixture === true); src.close(); });
    src.addEventListener("error", (e) => {
      const data = (e as MessageEvent).data;
      let msg = "The plan did not arrive: the connection was lost while it was being written.";
      if (data) { try { const j = JSON.parse(data); msg = /rate|busy|429|503|529|overload/i.test(`${j.error} ${j.detail ?? ""} ${j.status ?? ""}`) ? "The plan writer is busy right now. Wait a minute and try again." : "The plan could not be written this time."; } catch { /* keep default */ } }
      setError(msg); setStage(null); src.close();
    });
  }, [scope, budget, lang, objective, key]);

  useEffect(() => { const timer = setTimeout(() => run(false), 300); return () => { clearTimeout(timer); es.current?.close(); }; }, [run]);

  // A footnote number scrolls to its source inside the plan and marks it for a moment.
  const toFootnote = useCallback((n: number) => {
    setFn(n);
    document.getElementById(`plan-fn-${n}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);
  useEffect(() => { if (fn == null) return; const timer = setTimeout(() => setFn(null), 2600); return () => clearTimeout(timer); }, [fn]);

  const raw = plan?.markdown ?? draft;
  const pilot = plan?.pilot || opt.data?.pilot || null;
  const ownPilot = !!pilot && scope !== "FI";
  // The pilot is drawn once, from its data, below the plan; the model's own pilot paragraph is left out so it is not said twice.
  const md = useMemo(() => {
    const m = lang === "fi" ? fiNumbers(raw) : plainAreas(raw);
    return ownPilot ? m.replace(/\n## (?:Pilot ask|Pilottiehdotus)\s*\n[\s\S]*?(?=\n## |$)/, "\n") : m;
  }, [raw, lang, ownPilot]);
  // Today's web checks, printed under the action they belong to. The stored plan itself never changes with a check.
  const checks = useAsync(() => (scope === "FI" ? Promise.resolve([] as VerifyResult[]) : api.verifyLatest(scope)), [scope]);
  const acts = plan?.actions;
  const { nodes, order } = useMemo(() => {
    const by: Record<string, VerifyResult> = Object.fromEntries((checks.data ?? []).map((v) => [v.intervention_id ?? "", v]));
    const count = acts?.length ? checkCount(acts.map((a) => a.id), by, lang === "fi") : null;
    const under = (no: string) => {
      const id = acts?.find((a) => String(a.n) === no)?.id;
      const v = id ? by[id] : undefined;
      // The check's sentence exists in English only, so the Finnish plan carries the count and not the sentence.
      if (!v || lang !== "en" || !v.plan_effect_reason_en || (v.plan_effect !== "flag" && v.plan_effect !== "exclude")) return null;
      return <span className="webnote"><b>Web check {dayOf(v.checked_at)}: {(adviceWord(v) ?? "").toLowerCase()}.</b> {v.plan_effect_reason_en}{v.in_use_source?.url ? <> <a href={v.in_use_source.url} target="_blank" rel="noreferrer">{host(v.in_use_source.url)}</a></> : null}</span>;
    };
    return renderPlan(md, toFootnote, under, count ? <p className="webline num">{count}.</p> : null);
  }, [md, toFootnote, checks.data, acts, lang]);
  // One A4, always. When the page prints, the sheet takes class "paper" (fixed 194 mm wide, the print type sizes) and
  // --k scales the type so the text fills the page without running onto a second one. Measured, not guessed.
  const sheet = useRef<HTMLElement>(null);
  const fit = useCallback(() => {
    const el = sheet.current; if (!el) return;
    const had = el.classList.contains("paper");
    el.classList.add("paper");
    const max = (276 * 96) / 25.4; // the page holds 284 mm; keep a little air
    const fits = (k: number) => { el.style.setProperty("--k", k.toFixed(3)); return el.getBoundingClientRect().height <= max; };
    let lo = 0.8, hi = 1.12;
    if (!fits(hi)) { for (let i = 0; i < 7; i++) { const mid = (lo + hi) / 2; if (fits(mid)) lo = mid; else hi = mid; } fits(lo); }
    if (!had) el.classList.remove("paper");
  }, []);
  useEffect(() => {
    const el = sheet.current; if (!el) return;
    const on = () => { fit(); el.classList.add("paper"); }, off = () => el.classList.remove("paper");
    const mq = window.matchMedia("print"), onMq = (e: MediaQueryListEvent) => (e.matches ? on() : off());
    window.addEventListener("beforeprint", on); window.addEventListener("afterprint", off); mq.addEventListener("change", onMq);
    return () => { window.removeEventListener("beforeprint", on); window.removeEventListener("afterprint", off); mq.removeEventListener("change", onMq); };
  }, [fit]);
  const removed = plan?.review.removed ?? [];
  const flagged = plan?.review.flagged ?? [];
  const sum = plan?.review.summary ?? { rewritten: flagged.length, removed: removed.length };
  const changes = [...flagged.map((r) => ({ kind: "Rewritten", sentence: r.sentence, why: r.reason })),
    ...removed.map((r) => (typeof r === "string" ? { kind: "Removed", sentence: r, why: "" } : { kind: "Removed", sentence: r.sentence, why: r.reason }))];
  const stageIdx = t.stages.findIndex(([s]) => s === stage);
  const money = (n: number) => (lang === "fi" ? eurFi(n) : eurx(n));
  const shownBudget = plan?.nearest?.budget_eur ?? budget;
  const left = (plan?.excluded ?? without).map((id) => { const iv = ivs.data?.interventions.find((i) => i.id === id); return (lang === "fi" ? iv?.name_fi : null) ?? iv?.name_en ?? id; });

  const copy = async () => {
    const url = window.location.href;
    try { await navigator.clipboard.writeText(url); } catch {
      const ta = document.createElement("textarea"); ta.value = url; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };
  const pdf = () => {
    // The browser's own "Save as PDF" writes the file; the page title becomes its name.
    const old = document.title;
    document.title = `Kello ${lang === "fi" ? "suunnitelma" : "plan"} - ${name} - ${money(shownBudget).replace("€", "EUR").trim()}`;
    window.print();
    setTimeout(() => { document.title = old; }, 500);
  };

  return (
    <div className="planwrap">
      <article className="sheet" aria-live="polite" aria-busy={!!stage} lang={lang} ref={sheet}>
        <div className="runhead num">
          <span>Kello · {scope === "FI" ? t.national : t.doc} · {name}</span>
          <span>{t.ceiling} {money(shownBudget)} {t.year}{plan?.generated_at ? ` · ${lang === "fi" ? whenFi(plan.generated_at) : when(plan.generated_at).replace(/,.*$/, "")}` : ""}{plan?.fixture ? ` · ${t.sample}` : ""}</span>
        </div>
        {plan?.nearest && <p className="nearest">{lang === "fi" ? plan.nearest.label_fi : plan.nearest.label_en}</p>}
        {budget <= 0 ? <p className="muted">{t.zero}</p> : error ? <Failed message={error} retry={() => run(false)} /> : md ? (
          <>
            <div className={"doc" + (stage === "writing" ? " caret" : "")}>{nodes}</div>
            {ownPilot && pilot && <section className="planpilot" aria-label="Pilot ask">
              <h2>{lang === "fi" ? "Pilottiehdotus" : "Pilot ask"}</h2>
              <p className="asklead">{pilotText(pilot, lang).lead}</p>
              <PilotFigures p={pilot} lang={lang} cmpName={lang === "fi" ? areas.find((a) => a.id === pilot.six_months?.comparison_area_id)?.name_fi : undefined} />
              {pilotText(pilot, lang).rest && <p>{pilotText(pilot, lang).rest}</p>}
              {pilot.cannot_show_en && <p className="small muted">{lang === "fi" ? (pilot.cannot_show_fi ?? pilot.cannot_show_en) : pilot.cannot_show_en}</p>}
            </section>}
            {((plan?.action_studies?.length ?? 0) > 0 || (opt.data?.chosen?.some((c) => c.study_line_en) ?? false)) && <section className="planstudies" aria-label="Effect studies">
              <h2>{lang === "fi" ? "Vaikutusarviot ja tutkimukset" : "Effect sizes and their studies"}</h2>
              <ul>{(plan?.action_studies ?? opt.data?.chosen?.map((c) => ({ id: c.intervention_id, study_line_en: c.study_line_en, why_here_en: c.why_here_en })) ?? []).filter((x) => x.study_line_en || x.why_here_en).filter((x, i, all) => all.findIndex((y) => y.id === x.id && y.why_here_en === x.why_here_en && y.study_line_en === x.study_line_en) === i).map((x, i) => <li key={`${x.id}-${i}`}>{x.why_here_en && <><b>{lang === "fi" ? "Miksi täällä:" : "Why here:"}</b> {x.why_here_en}<br /></>}{x.study_line_en && <StudyLine text={x.study_line_en} label={lang === "fi" ? "Vaikutusarvio perustuu:" : "The effect comes from:"} linkLabel={lang === "fi" ? "avaa tutkimus" : "open the study"} />}</li>)}</ul>
            </section>}
            {!plan && stage && <PlanSkeleton rest />}
            {plan && left.length > 0 && <p className="leftout"><b>{t.without}:</b> {left.join("; ")}.</p>}
            {plan && order.length > 0 && (
              <div className="fn">
                <h2>{t.sources}</h2>
                <ol>
                  {order.map((id, i) => {
                    const s = plan.sources?.[id];
                    return (
                      <li key={id} id={`plan-fn-${i + 1}`} className={fn === i + 1 ? "on" : ""}>
                        {(s?.title ?? id).replace(/[.\s]+$/, "")}{s?.publisher ? `, ${s.publisher.replace(/[.\s]+$/, "")}` : ""}{s?.url ? <>. <a href={s.url} target="_blank" rel="noreferrer">{shortUrl(s.url).replace(/^https?:\/\/(www\.)?/, "")}</a></> : ""}
                        {s?.retrieved_at ? ` (${t.retrieved} ${lang === "fi" ? whenFi(s.retrieved_at) : s.retrieved_at.slice(0, 10)})` : ""}{s?.verified === false ? ` [${t.unverified}]` : ""}
                      </li>
                    );
                  })}
                </ol>
              </div>
            )}
          </>
        ) : <PlanSkeleton />}
      </article>

      <aside className="side noprint">
        <section className="panel">
          <header><h2>One-page plan for {nameEn}</h2></header>
          <div className="body" style={{ display: "grid", gap: 12 }}>
            <div className="row">
              <button className="btn primary" onClick={pdf} disabled={!plan}>Print / save PDF</button>
              <button className="btn" onClick={copy} disabled={budget <= 0}>{copied ? "Link copied" : "Copy link"}</button>
            </div>
            <div>
              <span className="lb" id="lb-lang">Language</span>
              <div className="seg" role="group" aria-labelledby="lb-lang">
                <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
                <button aria-pressed={lang === "fi"} onClick={() => setLang("fi")}>Suomi</button>
              </div>
            </div>
            <div>
              <span className="lb" id="lb-b">Budget a year</span>
              <div className="seg" role="group" aria-labelledby="lb-b">
                {PRESETS.map((b) => <button key={b} aria-pressed={budget === b} onClick={() => setBudget(b)}>{eurx(b).replace(/,000$/, "k")}</button>)}
              </div>
              {!PRESETS.includes(budget) && <div className="small muted" style={{ marginTop: 4 }}>Using {eurx(budget)} from the link or the county page.</div>}
            </div>
            {stage && (
              <ul className="stages" role="status">
                {T.en.stages.map(([s, label], i) => <li key={s} className={i < stageIdx ? "done" : i === stageIdx ? "on" : ""}><i />{label}</li>)}
              </ul>
            )}
            {plan && !stage && (
              <p className="small muted">
                {plan.generated_by === "template" ? "This is the template text: the plan writer could not be reached, so the sentences are built straight from the numbers. " : `Written by ${plan.generated_by}${plan.generated_at ? ` on ${when(plan.generated_at)}` : ""}. `}
                {plan.objective ? `Actions ranked by ${OBJ[plan.objective] ?? plan.objective}. ` : ""}
                The numbers and their order are the county page's own. The link carries the county, budget, language and anything left out, and always shows this same text.{" "}
                {!plan.nearest && <button className="btn quiet sm inline" onClick={() => run(true)}>Write it again</button>}
              </p>
            )}
            <button className="btn sm" onClick={openCounty}>Change the actions on the county page</button>
          </div>
        </section>

        {plan && (
          <section className="panel review">
            <header><h2>Reviewer note</h2></header>
            <div className="body">
              {plan.review.summary?.reviewed === false || /fail|none/.test(plan.review.checked_by ?? "") ? (
                <p className="count">Not checked by a second pass{plan.generated_by === "template" ? ": this is the template text." : "."}</p>
              ) : (
                <p className="count num">Checked by a second pass: {sum.rewritten} sentence{sum.rewritten === 1 ? "" : "s"} rewritten, {sum.removed} removed.</p>
              )}
              <p className="small muted" style={{ marginTop: 4 }}>
                {plan.claims.length} sourced statements on the page{plan.review.summary?.citations_added ? `; ${plan.review.summary.citations_added} got a missing source added` : ""}. The table, the targets and the totals are not written by the model: they are filled in from the ranking.
              </p>
              {changes.length > 0 && (
                <details className="changes">
                  <summary>What the second pass changed</summary>
                  <ul>
                    {changes.map((c, i) => (
                      <li key={i}><b>{c.kind}:</b> <q>{plain(c.sentence)}</q>{reason(c.why) ? <span> {reason(c.why)}</span> : null}</li>
                    ))}
                  </ul>
                </details>
              )}
              {plan.review.unknown_source_ids?.length ? <p style={{ color: "var(--bad)", marginTop: 8 }}>Citations to unknown sources: {plan.review.unknown_source_ids.join(", ")}</p> : null}
              {plan.review.error && <p className="small" style={{ color: "var(--bad)", marginTop: 8 }}>The second pass did not finish; the text is the first draft.</p>}
            </div>
          </section>
        )}

        <ReadReport />
      </aside>
    </div>
  );
}

/* ---------- report reader (Gemini) ---------- */
type RowState = "adding" | "added" | "failed";
const LAST = "kello.reader.last";
const shortTitle = (t: string) => { const x = t.split(/ [-–] | \(|: /)[0].trim(); return x.length > 44 ? `${x.slice(0, 42)}…` : x; };
const hostOf = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u.slice(0, 34); } };
const EXAMPLE_PAGE = "https://cancerregistry.fi/statistics/cancer-statistics/";

function ReadReport() {
  const [url, setUrl] = useState("");
  const [over, setOver] = useState(false);
  const [st, setSt] = useState<{ loading: boolean; data?: ReportResult; error?: string; what?: string; elapsed?: number; url?: string }>({ loading: false });
  const [chart, setChart] = useState(false);
  const [all, setAll] = useState(false);
  const [rowState, setRowState] = useState<Record<number, RowState>>({});
  const info = useAsync(api.reader, []);
  const kept = useAsync(api.readKept, []);
  const charts = useAsync(api.readCharts, []);
  const file = useRef<HTMLInputElement>(null);
  const run = useRef(0);
  useEffect(() => () => { run.current++; }, []);
  const pre = info.data?.pre_read ?? [];
  const titleOf = (u?: string) => (u ? pre.find((p) => p.url === u)?.title ?? null : null);
  const nameOf = (u: string) => { const tt = titleOf(u); return tt ? shortTitle(tt) : hostOf(u); };

  // A read takes 85-200 s: start a job, then poll. The page stays usable, and a URL read before comes back at once.
  const go = async (start: () => Promise<ReportJob>, what: string, u?: string) => {
    const my = ++run.current;
    setAll(false); setRowState({}); setChart(false);
    setSt({ loading: true, what, elapsed: 0, url: u });
    try {
      let job = await start();
      while (job.status === "running" && job.job_id) {
        if (my !== run.current) return;
        setSt({ loading: true, what, elapsed: job.elapsed_s, url: u });
        await new Promise((r) => setTimeout(r, 2500));
        job = await api.readJob(job.job_id);
      }
      if (my !== run.current) return;
      if (job.status === "done" && job.result) {
        setSt({ loading: false, what, data: job.result, url: u }); info.reload();
        if (u) try { localStorage.setItem(LAST, u); } catch { /* private window */ }
      } else setSt({ loading: false, what, url: u, error: /rate|busy|429|503|overload/i.test(`${job.error} ${job.detail ?? ""}`) ? "The report reader is busy right now. Wait a minute and try again." : "This document could not be read. Check that the link opens a report or a PDF." });
    } catch (e) {
      if (my !== run.current) return;
      const err = e as ApiError;
      setSt({ loading: false, what, url: u, error: err.status === 503 ? "The report reader is not connected on this copy of Kello. The two examples below still open." : friendly(e) });
    }
  };
  const readUrl = (u: string) => { setUrl(u); go(() => api.readStartUrl(u), u, u); };
  // The last document read on this device opens again after a reload (the read itself is stored by Kello).
  useEffect(() => { let u: string | null = null; try { u = localStorage.getItem(LAST); } catch { /* private window */ } if (u) readUrl(u); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const onFile = (f?: File | null) => { if (f) go(() => api.readStartFile(f), f.name); };
  const clear = () => { run.current++; setSt({ loading: false }); setChart(false); setUrl(""); try { localStorage.removeItem(LAST); } catch { /* private window */ } };

  const doc = st.data?.document;
  const rows = st.data?.extracted ?? [];
  const shown = all ? rows : rows.slice(0, 8);
  const el = st.elapsed ?? 0;
  const docUrl = st.url ?? doc?.url;
  const keptRows = kept.data?.rows ?? [];
  const isKept = (i: number) => rowState[i] === "added" || keptRows.some((k) => (k.source_url ?? k.url) === docUrl && k.row_index === i);
  const nKept = rows.filter((_, i) => isKept(i)).length;
  const add = (i: number) => {
    if (!docUrl) return;
    setRowState((s) => ({ ...s, [i]: "adding" }));
    api.readKeep(docUrl, i).then(() => { setRowState((s) => ({ ...s, [i]: "added" })); kept.reload(); }, () => setRowState((s) => ({ ...s, [i]: "failed" })));
  };
  const acc = charts.data?.accuracy ?? null;
  const inKello = docUrl ? pre.find((p) => p.url === docUrl)?.in_kello ?? null : null;
  const what = (x: ReportRow) => `${x.label_en ?? x.label ?? x.indicator_guess ?? ""}${x.area ? `, ${x.area}` : ""}${x.period ? `, ${x.period}` : ""}`;
  return (
    <section className="panel reader" aria-label="Read a report">
      <header><h2>Read a report</h2></header>
      <div className="body" style={{ display: "grid", gap: 10 }}>
        <p className="small muted">Many Finnish figures exist only inside PDF reports and charts. Paste a link or drop a PDF: Gemini reads it and returns each value with its page and quote. You choose which values go into Kello.</p>
        <form className="row" style={{ flexWrap: "nowrap" }} onSubmit={(e) => { e.preventDefault(); const u = url.trim(); if (u) readUrl(u); }}>
          <label className="sr" htmlFor="rr-url">Report URL</label>
          <input id="rr-url" className="input" type="url" placeholder="https://… report or PDF" value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className="btn" disabled={st.loading || !url.trim()}>Read</button>
        </form>
        <div className="preread">
          <span className="small"><b>Two worked examples</b>, both open at once:</span>
          <button type="button" className="btn sm" disabled={st.loading} onClick={() => readUrl(EXAMPLE_PAGE)}>A registry statistics page<span className="muted num"> · {pre.find((p) => p.url === EXAMPLE_PAGE)?.values ?? ""} lung cancer values</span></button>
          {charts.data && charts.data.count > 0 && <button type="button" className="btn sm" disabled={st.loading} onClick={() => { run.current++; setSt({ loading: false }); setChart(true); }}>A chart with no numbers printed<span className="muted num"> · {charts.data.count} values read off the bars</span></button>}
        </div>
        {pre.filter((p) => p.url !== EXAMPLE_PAGE).length > 0 && (
          <details className="more flat">
            <summary>Other reports already read <span className="muted num">{pre.filter((p) => p.url !== EXAMPLE_PAGE).length}</span></summary>
            <div className="preread">
              {pre.filter((p) => p.url !== EXAMPLE_PAGE).map((p) => (
                <button key={p.url} type="button" className="btn sm" disabled={st.loading} title={p.title ?? p.url} onClick={() => readUrl(p.url)}>
                  {nameOf(p.url)}<span className="muted num"> · {hostOf(p.url)}</span>
                </button>
              ))}
            </div>
          </details>
        )}
        <div className={"drop" + (over ? " over" : "")} role="button" tabIndex={0} onClick={() => file.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && file.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); onFile(e.dataTransfer.files?.[0]); }}>
          Drop a PDF here, or choose a file
          <input ref={file} type="file" accept="application/pdf,image/*" hidden onChange={(e) => onFile(e.target.files?.[0])} />
        </div>
        {st.loading && (
          <div role="status" className="reading small">
            <div><span className="spin" />Gemini is reading {st.url ? nameOf(st.url) : st.what} <span className="num muted">· {Math.round(el)} s</span></div>
            <div className="prog" aria-hidden="true"><i style={{ width: `${Math.min(96, (el / 200) * 100)}%` }} /></div>
            <div className="muted">{el < 100 ? "First pass: every page is read for numbers. A new report takes one and a half to three and a half minutes." : "Second pass: each number is checked again against its page."} You can keep working while it reads.</div>
            <div aria-hidden="true">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 30, marginTop: 6 }} />)}</div>
          </div>
        )}
        {st.error && <div role="alert" className="small readerr">{st.error} {st.url && <button type="button" className="btn sm" onClick={() => readUrl(st.url!)}>Try again</button>}</div>}
        {chart && charts.data && acc && <ChartExample c={charts.data} onClose={clear} />}
        {st.data && !chart && (
          <div className="readresult">
            <p className="small"><b>{doc?.title ?? st.what}</b><span className="muted num"> · {rows.length} values in this read{st.data.model ? ` · read by ${st.data.model}` : ""}{st.data.cached ? ` · read earlier${st.data.read_at ? `, ${when(st.data.read_at)}` : ""}` : ""}{nKept ? ` · ${nKept} added to Kello by you` : ""}</span> <button type="button" className="btn quiet sm inline" onClick={clear}>Close</button></p>
            {inKello != null && inKello > 0 && inKello !== rows.length && <p className="small muted num">Kello's dataset holds {inKello} values from this report, from several reads of its pages and tables; that is the count in Sources &amp; method.</p>}
            {st.data.notes_en && <details className="gnotes small" open={rows.length === 0}><summary>Gemini's note on this document</summary><p>{st.data.notes_en}</p></details>}
            {rows.length === 0 ? <p className="small muted">No value with a page and quote could be taken from this document{st.data.notes_en ? "; the note above says why" : ""}.</p> : (
              <>
                <ul className="rrows num">
                  {shown.map((x, i) => (
                    <li key={i}>
                      <div className="rv"><b>{x.value ?? "–"}</b> {x.unit}</div>
                      <div className="rw">{what(x)}{x.value_kind === "target" ? <span className="tag assumption"> a target, not a measurement</span> : null}
                        {x.quote && <div className="muted quote">p. {x.page ?? "–"} · “{x.quote}”</div>}</div>
                      {docUrl && (
                        <div className="keep">
                          {isKept(i) ? <span className="tag kept" title="Added to Kello by you, as unverified; listed in Sources & method">In Kello</span>
                            : <button type="button" className="btn sm" disabled={rowState[i] === "adding"} onClick={() => add(i)}>{rowState[i] === "adding" ? "Adding" : rowState[i] === "failed" ? "Try again" : "Add to Kello"}</button>}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
                {rows.length > 8 && <button type="button" className="btn quiet sm" onClick={() => setAll((v) => !v)}>{all ? "Show fewer" : `Show all ${rows.length} values`}</button>}
                {docUrl && <p className="small muted">A value you add is listed in Sources &amp; method as “added by you, unverified”. It does not change the plan.</p>}
              </>
            )}
          </div>
        )}
        {keptRows.length > 0 && !st.data && !chart && <p className="small muted num">{keptRows.length} value{keptRows.length === 1 ? "" : "s"} added to Kello by you from reports read here; listed in Sources &amp; method.</p>}
      </div>
    </section>
  );
}

/** The second worked example: numbers the registry publishes only as a stacked bar chart, read off the picture and checked. */
function ChartExample({ c, onClose }: { c: ChartRead; onClose: () => void }) {
  const a = c.accuracy!;
  const rows = (c.rows ?? []).slice(0, 6);
  const blind = a.check_a_blind_read_vs_table;
  return (
    <div className="readresult">
      <p className="small"><b>{a.figure}: {a.caption}</b><span className="muted num"> · {c.count} values · read by {a.model}</span> <button type="button" className="btn quiet sm inline" onClick={onClose}>Close</button></p>
      <p className="small">{a.what} Gemini read the bar lengths off the picture.</p>
      {blind && <p className="small num"><b>How accurate is that?</b> On a chart of the same design whose numbers are printed, we painted the numbers out and compared: {blind.n} values, off by {one(blind.mean_abs_error_pp)} percentage points on average, {one(blind.max_abs_error_pp)} at most.</p>}
      <ul className="rrows num">
        {rows.map((x, i) => (
          <li key={i}>
            <div className="rv"><b>{x.value}</b> {x.unit}</div>
            <div className="rw">{x.label_en}, {x.area_name}, {x.period}<div className="muted quote">{x.figure} · read twice{x.check?.pixel_measure != null ? `; measured from the pixels: ${one(x.check.pixel_measure)}` : ""}</div></div>
            <div className="keep"><span className="tag kept" title="In Kello as read from a chart, unverified">In Kello</span></div>
          </li>
        ))}
      </ul>
      <p className="small muted">{c.count} values in all, kept as “read from a chart, unverified”. {typeof a.limits === "string" ? a.limits : ""} {a.source_url && <a href={a.source_url} target="_blank" rel="noreferrer">Open the report</a>}</p>
    </div>
  );
}
