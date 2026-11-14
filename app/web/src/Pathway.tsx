import { Pathway as PathwayData, PathwayFigure, PathwayStep, one, SrcRef } from "./lib";
import { SourceChip } from "./Source";

const source = (f: PathwayFigure, where: string): SrcRef => ({
  kind: f.kind, source_id: f.source_id, source_url: f.source_url, page: f.page, quote: f.quote, read_by: f.read_by,
  period: f.period, what: `${f.label_en}, ${where}`, value: f.value == null ? null : `${one(f.value)}${f.unit === "%" ? "%" : ` ${f.unit ?? ""}`}`,
  note: f.note_en,
});

function Figure({ f, where }: { f: PathwayFigure; where: string }) {
  const value = f.value == null ? "not published" : `${one(f.value)}${f.unit === "%" ? "%" : ` ${f.unit ?? ""}`}`;
  const national = f.national == null ? null : `${one(f.national)}${f.unit === "%" ? "%" : ` ${f.unit ?? ""}`}`;
  return <li className="pathway-figure"><span><b>{f.label_en}</b><span className="num">{value}{national != null && <> <span className="muted">vs Finland {national}</span></>}</span></span><SourceChip short s={source(f, where)} /></li>;
}

function Step({ step, n }: { step: PathwayStep; n: number }) {
  return <li className={`pathway-step ${step.verdict ?? ""}`}><span className="pathway-q"><span className="pathway-index">{n}</span>{step.label_en}</span><b className="pathway-v">{step.verdict_en}</b></li>;
}

function StepDetail({ step, where }: { step: PathwayStep; where: string }) {
  return <div className="pathway-detail"><h3>{step.label_en}: {step.verdict_en}</h3>{step.answer_en && <p>{step.answer_en}</p>}<ul>{step.figures.map((f) => <Figure key={f.label_en} f={f} where={where} />)}</ul><p className="pathway-missing"><span>Finland does not publish:</span> {step.what_not_published_en}</p></div>;
}

export function DrugFinding({ pathway, where }: { pathway?: PathwayData; where: string }) {
  const f = pathway?.drug_finding?.drug ?? pathway?.steps.find((s) => s.id === "treatment")?.figures.find((x) => x.label_en === "Drug therapy on record");
  const life = pathway?.drug_finding?.life_prolonging;
  if (!f || f.value == null || f.national == null) return null;
  return <section className="drugfinding" aria-label="The second gap: drug treatment"><div><span className="eyebrow">Second finding</span><h2>The second gap: drug treatment</h2><p><b className="num">{one(f.value)}%</b> of patients have drug therapy on record here, against <b className="num">{one(f.national)}%</b> in Finland.{life?.value != null && life.national != null && <> Life-prolonging treatment is <b className="num">{one(life.value)}%</b> here vs <b className="num">{one(life.national)}%</b> in Finland.</>} The report warns that outpatient drug therapy is the least reliable field: it may be given at the university hospital and recorded there.</p>{pathway?.drug_finding?.next_en && <p className="drugnext"><b>What the plan does about it.</b> {pathway.drug_finding.next_en}</p>}</div><SourceChip s={source(f, where)} /></section>;
}

export default function Pathway({ pathway, where, drug = true }: { pathway?: PathwayData; where: string; drug?: boolean }) {
  if (!pathway?.steps?.length || pathway.steps.every((x) => x.verdict === "cannot_tell")) return null;
  const here = pathway.steps.filter((x) => x.verdict === "here");
  const head = here.length ? `${where} falls behind at ${here.length === 1 ? "one step" : `${here.length} steps`} of four` : `Where on the care path does ${where} differ?`;
  return (
    <section className="pathway panel" aria-label="Where the gap appears in the care pathway">
      <header><h2>{head}</h2></header>
      <ol className="pathway-grid">{pathway.steps.map((x, i) => <Step key={x.id} step={x} n={i + 1} />)}</ol>
      <details className="pathway-more"><summary>Why, step by step, with the figures</summary>
        <div className="pathway-details">{pathway.steps.map((x) => <StepDetail key={x.id} step={x} where={where} />)}</div>
        {pathway.stage_bound_en && <p className="pathway-bound">{pathway.stage_bound_en}</p>}
      </details>
      {drug && <DrugFinding pathway={pathway} where={where} />}
    </section>
  );
}
