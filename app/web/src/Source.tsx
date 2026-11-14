import { chipText, openSource, SrcRef } from "./lib";

/** The one provenance mark used everywhere. Clicking opens Sources & method at that source, with the quote. */
export function SourceChip({ s, short = false }: { s: SrcRef; short?: boolean }) {
  const text = short ? s.label ?? (s.kind === "estimated" ? "Estimated" : s.kind === "assumption" ? "Assumption" : s.kind === "reported" ? "Reported" : "Measured") : chipText(s);
  return (
    <button type="button" className={`chip ${s.kind}`} onClick={(e) => { e.stopPropagation(); openSource(s); }}
      title={`${chipText(s)}${s.note ? `. ${s.note.replace(/\.$/, "")}` : ""}. Open the source and method.`}>
      <i aria-hidden="true" />{text}
    </button>
  );
}

/**
 * Dot and range plot for one indicator: the range across counties, Finland as a tick, this area as the filled dot.
 * The axis is turned so that better is always to the right.
 */
export function RangePlot({ value, national, best, worst, fmt, label }: { value?: number | null; national?: number | null; best: number; worst: number; fmt: (n: number) => string; label: string }) {
  const span = best - worst || 1;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - worst) / span) * 100));
  return (
    <div className="rplot" role="img" aria-label={label}>
      <div className="rail" />
      {national != null && <div className="nat" style={{ left: `${pos(national)}%` }}><span className="num">Finland {fmt(national)}</span></div>}
      <div className="end lo num">{fmt(worst)}</div>
      <div className="end hi num">{fmt(best)}</div>
      {value != null && <div className="dot" style={{ left: `${pos(value)}%` }} />}
    </div>
  );
}
