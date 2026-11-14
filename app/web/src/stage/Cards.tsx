import { useLayoutEffect, useRef, useState } from "react";
import { days, eur, eurx, int, Intervention, Kind, one, openSource, PathwayFigure, PathwayStep, SrcRef } from "../lib";
import { CheckM, figureIn, PageM, PinM } from "./model";

export const KindTag = ({ kind, title }: { kind: Kind | string; title?: string }) => <span className={`tag ${kind}`} title={title}>{kind}</span>;

const figRef = (f: PathwayFigure, what: string): SrcRef => ({ kind: f.kind, source_id: f.source_id, source_url: f.source_url, page: f.page, quote: f.quote, read_by: f.read_by, period: f.period, what, value: f.value == null ? null : `${one(f.value)}${f.unit === "%" ? "%" : f.unit ? ` ${f.unit}` : ""}` });
const figText = (f: PathwayFigure) => (f.unit === "days" ? `${days(f.value)} days here, ${days(f.national)} in Finland` : `${one(f.value)}${f.unit === "%" ? "%" : ""} here, ${one(f.national)}${f.unit === "%" ? "%" : ""} in Finland`);
/** A figure that does not say what it counts gets a few words in front. */
const FIG: Record<string, string> = { "Alive one year after diagnosis": "alive after one year", "Lung clinic referrals handled in over 21 days": "referrals taking over 21 days" };
const TONE: Record<string, string> = { here: "here", possibly_here: "maybe", not_behind: "ok", cannot_tell: "unknown" };

/** The four questions of the care path, one after another; the step where patients are lost turns red. */
export function CarePathCard({ steps, national, shown, split, splitOn, lost }: { steps: PathwayStep[]; national?: boolean; shown: number; split: { label: string; n: number; note?: string }[]; splitOn: boolean; lost: number | null }) {
  return (
    <div className="st-path">
      <ol>
        {steps.map((s, i) => {
          const f = s.figures.find((x) => x.value != null && x.national != null);
          return (
            <li key={s.id} className={`st-step ${national ? "unknown" : TONE[s.verdict ?? ""] ?? "unknown"}` + (i < shown ? " on" : "")}>
              <i aria-hidden="true" />
              <div>
                <b>{s.label_en}</b>
                {f && <button className="st-fig num" onClick={() => openSource(figRef(f, f.label_en))} title={`${f.label_en}. Open the source.`}>{FIG[f.label_en] ? `${FIG[f.label_en]}: ` : ""}{national ? `${f.unit === "days" ? `${days(f.value)} days` : `${one(f.value)}${f.unit === "%" ? "%" : ""}`} in Finland` : figText(f)}{f.kind !== "measured" && <> <KindTag kind={f.kind} /></>}</button>}
              </div>
              {!national && <span className="st-verdict">{s.verdict_en}</span>}
            </li>
          );
        })}
      </ol>
      {split.length > 0 && (
        <div className={"st-split" + (splitOn ? " on" : "")}>
          {split.map((x) => <div key={x.label} title={x.note}><b className="num">{x.n}</b><span>{x.label}</span></div>)}
          {lost != null && <p className="st-fine num">of the {lost} a year <KindTag kind="estimated" title={split.map((x) => x.note).filter(Boolean).join(" ")} /></p>}
        </div>
      )}
    </div>
  );
}

export interface LedgerRow { pin: PinM; on: boolean; off?: boolean; check?: CheckM | null; checkOn?: boolean; missOn?: boolean; effect?: { value: string; range: string; short?: string; kind: string; basis?: string } | null; effectOn?: number }

/** The plan as it builds: what it costs, how many of the missing it reaches, and one row per action. */
export interface Narrow { n: number; low: number; high: number; fresh: { n: number; eur: number; extra: number }; part: { n: number; eur: number; extra: number }; open: { n: number; eur: number; extra: number } }
const dec = (x: number) => String(+x.toFixed(1));

export function Ledger({ rows, total, reached, of, lo, hi, rangeOn, unit, compact, sel, onSel, flyTo, narrow, part }: {
  rows: LedgerRow[]; total: number; reached: number; of: number | null; lo: number; hi: number; rangeOn: boolean; unit: "extra" | "deaths"; compact: boolean; sel: string | null; onSel: (id: string) => void; flyTo: string | null; narrow?: Narrow | null;
  /** On a phone the sum sits under the headline and the rows further down: the same ledger, drawn in two places. */
  part?: "head" | "rows";
}) {
  const per = unit === "deaths" ? "deaths avoided a year" : "patients a year";
  /** "about 1 patient a year", "about 1.7 patients a year". */
  const pa = (x: number) => `${dec(x)} ${unit !== "deaths" && dec(x) === "1" ? "patient a year" : per}`;
  const none = !narrow && rows.every((r) => !r.on);   // before the first action lands there is no sum to show
  // The total is the sum of the rows on screen, never a number on its way somewhere: the headline shows the same value.
  return (
    <div className={"st-ledger" + (part ? ` ${part}` : "")}>
      {part === "rows" ? null : narrow ? (
        <>
          <div className="st-total narrowed" key="n"><b className="num">{eurx(narrow.low)} to {eurx(narrow.high)}</b><span>a year</span></div>
          <ul className="st-narrow">
            {narrow.fresh.n > 0 && <li><i className="none" aria-hidden="true" /><span><b>{narrow.fresh.n} with no public sign of it:</b> <span className="num">{eurx(narrow.fresh.eur)}, about {pa(narrow.fresh.extra)}</span></span></li>}
            <li><i className="partly" aria-hidden="true" /><span><b>{narrow.part.n} partly in place:</b> <span className="num">up to {eurx(narrow.part.eur)} for what is missing, up to {pa(narrow.part.extra)}</span></span></li>
            {narrow.open.n > 0 && <li><i aria-hidden="true" /><span><b>{narrow.open.n} not checked yet:</b> <span className="num">{eurx(narrow.open.eur)}, about {pa(narrow.open.extra)}</span></span></li>}
          </ul>
        </>
      ) : (
        <div className="st-total" style={none ? { visibility: "hidden" } : undefined}><b className="num">{eurx(Math.round(total))}</b><span>a year</span></div>
      )}
      {part !== "rows" && <p className={"st-reach" + (rangeOn ? " on" : "")} style={none ? { visibility: "hidden" } : undefined}>
        <span className="num">{narrow ? `If all ${narrow.n} are needed in full: ` : ""}{unit === "deaths" ? `about ${one(reached)} deaths avoided a year` : of != null ? `${narrow ? "reach" : "reaches"} about ${int(Math.round(reached))} of ${of} a year` : `about ${int(Math.round(reached))} more treated to cure a year`}</span>
        <span className="st-range num">range {int(Math.round(lo) || 0)} to {int(Math.round(hi) || 0)}</span>
        <KindTag kind="estimated" title="Modelled from the measured gap and each action's effect. The range starts at 0: no effect is possible." />
      </p>}
      {part !== "head" && <ul className={compact ? "compact" : ""}>
        {rows.map(({ pin: p, on, off, check, checkOn, missOn, effect, effectOn = 0 }) => (
          <li key={p.id} className={(on ? "on" : "") + (off ? " off" : "") + (sel === p.id ? " sel" : "")}>
            <button onClick={() => onSel(p.id)} title={p.name} aria-pressed={sel === p.id}>
              <i className="num">{p.count ?? p.n}</i>
              <b>{p.short}</b>
              <span className="num st-cost">{p.count != null ? eur(p.eur) : eurx(p.eur)}</span>
              {!compact && (
                <span className="st-row2">
                  {!(checkOn && check?.advice) && effectOn === 0 && on && <span className="st-per num">{p.extra < 0.05 ? "finds the cause, moves no patient by itself" : `about ${pa(p.extra)}`}</span>}
                  {check?.advice && <em className={"st-advice" + (checkOn ? " on" : "")}>{check.advice}</em>}
                  {checkOn && missOn && check?.missing && <span className="st-miss" title={`Missing: ${check.missing}`}>Missing: {check.missing}</span>}
                  {effect && (
                    <span className={"st-effect num" + (effectOn > 0 ? " on" : "")} data-fly={flyTo === p.id ? "to" : undefined}>
                      {effect.short ?? effect.value}
                      <span className={effectOn > 1 ? "on" : ""}> · range {effect.range}</span>
                      <span className={effectOn > 2 ? "on" : ""}> <KindTag kind={effect.kind} title={effect.basis} /></span>
                    </span>
                  )}
                </span>
              )}
            </button>
            {sel === p.id && <p className="st-full">{p.name}</p>}
          </li>
        ))}
      </ul>}
    </div>
  );
}

/** A public page the check read, with the sentence it leans on, word for word. */
export function PageCard({ p, on, quoteOn, i }: { p: PageM; on: boolean; quoteOn: boolean; i: number }) {
  return (
    <a className={"st-page" + (on ? " on" : "")} href={p.url} target="_blank" rel="noreferrer" data-page={i}>
      <span className="st-domain">{p.domain}</span>
      <b>{p.title}</b>
      {p.quotes[0] && <q className={quoteOn ? "on" : ""} lang={/[äö]/i.test(p.quotes[0]) ? "fi" : undefined}>{p.quotes[0]}</q>}
    </a>
  );
}

export const effectText = (e: Intervention["effect"]): { value: string; range: string; short: string } => {
  const f = (n: number) => String(+Math.abs(n).toFixed(2));
  const unit = e.metric === "curative_share_pp" ? " more per 100 patients treated to cure" : e.metric.endsWith("_pp") ? (Math.abs(e.value) === 1 ? " point" : " points") : e.metric === "days" ? " days" : e.metric === "relative_days" ? " of the wait" : e.metric === "mortality_rr" ? " relative risk" : "";
  const v = (n: number) => (e.metric === "relative_days" ? `${Math.round(Math.abs(n) * 100)}%` : f(n));
  return { value: `${v(e.value)}${unit}`, range: `${v(e.lo)} to ${v(e.hi)}`, short: e.metric === "curative_share_pp" ? `+${v(e.value)} per 100 patients` : `${v(e.value)}${unit}` };
};

/** One study behind an action's effect: what kind of study, how many patients, and the sentence the number comes from. */
export function StudyCard({ iv, idx, setIdx, quoteOn, flying }: { iv: Intervention; idx: number; setIdx: (i: number) => void; quoteOn: boolean; flying: boolean }) {
  const ev = iv.evidence[idx] ?? iv.evidence[0];
  if (!ev) return <p className="st-quiet">No study is on file for this action.</p>;
  const fig = figureIn(ev.claim, ev.quote);
  const q = ev.quote ?? "";
  return (
    <div className="st-study on">
      <dl>
        {ev.design && <div className="wide"><dt>Study</dt><dd>{ev.design}</dd></div>}
        {ev.year != null && <div><dt>Year</dt><dd className="num">{ev.year}</dd></div>}
        {ev.n != null && <div><dt>Patients</dt><dd className="num">{int(ev.n)}</dd></div>}
      </dl>
      {q ? (
        <q className={quoteOn ? "on" : ""}>
          {fig ? <>{q.slice(0, fig.start)}<mark data-fly="from" className={flying ? "gone" : ""}>{q.slice(fig.start, fig.end)}</mark>{q.slice(fig.end)}</> : q}
        </q>
      ) : <p className="st-claim">{ev.claim}</p>}
      <div className="st-study-foot">
        {ev.url && <a href={ev.url} target="_blank" rel="noreferrer">Open the study</a>}
        {iv.evidence.length > 1 && (
          <span className="st-pager">
            <button onClick={() => setIdx((idx + iv.evidence.length - 1) % iv.evidence.length)} aria-label="Previous study">‹</button>
            <span className="num">{idx + 1} of {iv.evidence.length} studies</span>
            <button onClick={() => setIdx((idx + 1) % iv.evidence.length)} aria-label="Next study">›</button>
          </span>
        )}
      </div>
    </div>
  );
}

/** The figure of the study on its way into the plan row. Measured from the page, so it lands where the row really is. */
export function Fly({ root, on, text }: { root: React.RefObject<HTMLElement>; on: boolean; text: string }) {
  const el = useRef<HTMLSpanElement>(null);
  const [vis, setVis] = useState(false);
  useLayoutEffect(() => {
    const r = root.current, me = el.current;
    if (!on || !r || !me) { setVis(false); return; }
    const a = r.querySelector('[data-fly="from"]')?.getBoundingClientRect(), b = r.querySelector('[data-fly="to"]')?.getBoundingClientRect(), o = r.getBoundingClientRect();
    if (!a || !b) return;
    me.style.transition = "none";
    me.style.transform = `translate(${a.left - o.left}px, ${a.top - o.top}px)`;
    setVis(true);
    const id = requestAnimationFrame(() => requestAnimationFrame(() => { me.style.transition = ""; me.style.transform = `translate(${b.left - o.left}px, ${b.top - o.top}px)`; }));
    return () => cancelAnimationFrame(id);
  }, [on, root]);
  return <span ref={el} className={"st-fly num" + (vis && on ? " on" : "")} aria-hidden="true">{text}</span>;
}
