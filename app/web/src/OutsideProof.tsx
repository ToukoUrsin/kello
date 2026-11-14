import { OutsideProof as Proof, ProofItem, one } from "./lib";

const num = (n: number) => String(+n.toFixed(1));
const model = (it: ProofItem) => (it.model?.value != null ? `+${num(it.model.value)} per 100${it.model.lo != null && it.model.hi != null ? ` (${num(it.model.lo)} to ${num(it.model.hi)})` : ""}` : null);
/** "+3.5 per 100 patients" from a before and after in percent. */
const change = (it: ProofItem) => (it.change_pp != null ? `${it.change_pp >= 0 ? "+" : "−"}${num(Math.abs(it.change_pp))} per 100 patients` : null);

/** One published before-and-after in a sentence, for step 5 of the Run. */
export function ProofLine({ p, actionId }: { p?: Proof | null; actionId?: string | null }) {
  const it = p?.items.find((x) => x.action_id === actionId) ?? p?.items[0];
  if (!it) return p?.backtest_en ? <p className="st-fine on">{p.backtest_en}</p> : null;
  const m = model(it);
  return (
    <p className="st-fine on st-proof">
      <b>Measured outside the model.</b> {it.where_en}, {it.period}: {it.what_en.toLowerCase()} went from {one(it.before.value)}{it.unit} to {one(it.after.value)}{it.unit}{change(it) ? ` (${change(it)})` : ""}.{m && it.action_en ? ` The plan assumes ${m} for ${it.action_en}.` : ""}{" "}
      <a href={it.source_url} target="_blank" rel="noreferrer">source</a>
    </p>
  );
}

/** Published before-and-after figures next to the model's effect size, and whether a backtest is possible. */
export default function OutsideProof({ p }: { p?: Proof | null }) {
  if (!p || (!p.items.length && !p.backtest_en)) return null;
  return (
    <div className="proof">
      <h3>Has a change like this been measured?</h3>
      {p.items.length === 0 && <p>No published before-and-after from Finland or the Nordic countries was found for these actions.</p>}
      <ul>
        {p.items.map((it) => {
          const m = model(it);
          return (
            <li key={it.id}>
              <div className="proof-head"><b>{it.where_en}, {it.period}</b><span className={`tag ${it.kind}`}>{it.kind}</span></div>
              <p className="proof-nums num">{it.what_en}: <b>{one(it.before.value)}{it.unit}</b>{it.before.n ? ` (${it.before.n})` : ""} in {it.before.label} → <b>{one(it.after.value)}{it.unit}</b>{it.after.n ? ` (${it.after.n})` : ""} in {it.after.label}{change(it) ? `: ${change(it)}` : ""}.</p>
              {m && <p className="num">The plan assumes <b>{m}</b>{it.action_en ? ` for ${it.action_en}` : ""}.</p>}
              {it.caveat_en && <p>{it.caveat_en}</p>}
              <q lang={it.quote_lang ?? undefined}>{it.quote}</q>
              <a className="muted" href={it.source_url} target="_blank" rel="noreferrer">{it.source_title ?? "source"}{it.page != null ? ` · p. ${it.page}` : ""}</a>
            </li>
          );
        })}
      </ul>
      {p.backtest_en && <p className="proof-back">{p.backtest_en}</p>}
    </div>
  );
}
