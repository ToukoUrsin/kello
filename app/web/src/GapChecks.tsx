import { GapCheck, api, useAsync } from "./lib";
import { Failed } from "./App";

const label: Record<string, string> = { holds: "holds", mostly_holds: "mostly holds", weakens: "speaks against", cannot_tell: "cannot tell" };

function Source({ c }: { c: GapCheck }) {
  if (!c.source_url) return null;
  const page = c.page == null ? "" : typeof c.page === "number" ? ` · p. ${c.page}` : ` · ${c.page}`;
  return <a className="muted" href={c.source_url} target="_blank" rel="noreferrer">source{page}</a>;
}

function Mark({ c }: { c: GapCheck }) {
  return <span className="gapmark" role="img" aria-label={label[c.verdict] ?? c.verdict} />;
}

function Check({ c }: { c: GapCheck }) {
  return (
    <li className={`gapcheck ${c.verdict}`}>
      <div className="gapcheck-q"><Mark c={c} /><b>{c.question_en}</b>{c.verdict === "cannot_tell" ? <span className="tag">not published</span> : <span className={`tag ${c.kind}`}>{c.kind}</span>}</div>
      <p>{c.answer_en}</p>
      <Source c={c} />
    </li>
  );
}

/** "Is this gap real?": five checks of a county's shortfall.
 *  line  = one sentence and five marks, opens into the full answers (first screen)
 *  strip = the sentence, then the five questions with their short answers always visible; opens into the full answers (county page)
 *  full  = everything open */
export default function GapChecks({ areaId, variant }: { areaId: string; variant: "line" | "strip" | "full" }) {
  const state = useAsync(() => api.area(areaId), [areaId]);
  const checks = state.data?.gap_checks ?? [];
  const overall = state.data?.gap_checks_overall_en;
  if (state.loading && !state.data) return <div className={`gapchecks ${variant} muted`} aria-label="Checking whether the gap is real">Checking the gap…</div>;
  if (state.error && !state.data) return <div className={`gapchecks ${variant}`}><Failed message={`The checks of the gap could not be loaded. ${state.error}`} retry={state.reload} /></div>;
  if (!checks.length) return null;
  if (variant === "line") {
    const first = (overall ?? "").split(". ")[0].replace(/\.?$/, ".");
    return <details className="gapchecks line"><summary><b>Is this gap real?</b> <span className="gapsum">{first}</span> <span className="gapmarks" aria-hidden="true">{checks.map((c) => <i key={c.id} className={c.verdict} />)}</span></summary><p className="gapsum-open">{first}</p><ol>{checks.map((c) => <Check key={c.id} c={c} />)}</ol></details>;
  }
  if (variant === "strip") {
    return (
      <section className="gapchecks gstrip" aria-label="Is this gap real?">
        <p className="gapstrip-head"><b>Is this gap real?</b> {overall}</p>
        <ul className="gapstrip">
          {checks.map((c) => (
            <li key={c.id} className={`gapcheck ${c.verdict}`}>
              <span className="gapstrip-q">{c.question_en}</span>
              <span className="gapstrip-a"><Mark c={c} />{c.short_answer_en ?? label[c.verdict]}</span>
            </li>
          ))}
        </ul>
        <details className="gapstrip-more"><summary>How each check was made</summary><ol>{checks.map((c) => <Check key={c.id} c={c} />)}</ol></details>
      </section>
    );
  }
  return <section className="gapchecks full panel" aria-label="Is this gap real?"><header><h2>Is this gap real?</h2></header><div className="body"><p className="lede">{overall}</p><ol>{checks.map((c) => <Check key={c.id} c={c} />)}</ol></div></section>;
}
