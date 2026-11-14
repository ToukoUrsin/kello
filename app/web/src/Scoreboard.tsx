import { Goal3, one, SurvivalTarget } from "./lib";
import { SourceChip } from "./Source";

const CANCER: Record<string, string> = { lung: "Lung", pancreas: "Pancreas", liver: "Liver" };
const SEX: Record<string, string> = { male: "men", female: "women", men: "men", women: "women" };
const pts = (n: number) => `${n < 0 ? "−" : n > 0 ? "+" : ""}${one(Math.abs(n))}`;

function trend(t: SurvivalTarget): string {
  const c = t.gap_change_pp_per_decade;
  if (c == null) return "–";
  // gap = Finland minus the benchmark, so a falling gap means Finland is dropping further behind
  if (Math.abs(c) < 0.5) return "steady";
  return `${c < 0 ? "grows" : "shrinks"} ${one(Math.abs(c))}`;
}

/** Strategy goal "equal and effective cancer care": its three targets and where Finland stands on each. Measured values only. */
export default function Scoreboard({ g }: { g: Goal3 }) {
  const order = ["lung", "pancreas", "liver"];
  const rows = [...g.survival_targets].filter((t) => typeof t.finland === "number" && typeof t.benchmark === "number")
    .sort((a, b) => order.indexOf(a.cancer) - order.indexOf(b.cancer) || (a.sex === "male" ? -1 : 1));
  const m = g.mortality_trend ?? {};
  const s0 = rows[0];
  const done = m.target_pct && m.change_since_baseline_pct != null ? Math.max(0, Math.min(1, m.change_since_baseline_pct / m.target_pct)) : null;
  const tw = g.treated_within_target;
  return (
    <section className="panel g3" aria-label="National cancer strategy targets">
      <header><h2>The national cancer strategy 2026–2035 sets three targets for equal care. Where Finland stands:</h2></header>
      <div className="g3grid">
        {rows.length > 0 && (
          <div className="g3cell">
            <h3>Survival in poor-prognosis cancers reaches the Nordic level</h3>
            <table className="g3t num">
              <thead><tr><th title="Five-year relative survival. NORDCAN publishes men and women separately, so both are shown.">Alive after 5 years</th><th>Finland</th><th title="Mean of Sweden and Norway">Sweden &amp; Norway</th><th>Gap, points</th><th title="How many years ago Sweden and Norway were at Finland's current level">Finland is behind</th><th title="Change in the gap, in points per decade. A growing gap means Finland is falling further behind.">Gap, per decade</th></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.cancer + t.sex}>
                    <td><b>{CANCER[t.cancer] ?? t.cancer}</b>, {SEX[t.sex] ?? t.sex}</td>
                    <td>{one(t.finland)}%</td>
                    <td>{one(t.benchmark)}%</td>
                    <td className="gapcell"><i style={{ width: Math.max(2, Math.round(Math.min(1, Math.abs(t.gap_pp) / 16) * 44)) }} /><b>{pts(t.gap_pp)}</b></td>
                    <td>{t.lag_years != null ? `about ${Math.round(t.lag_years)} years` : "–"}</td>
                    <td>{trend(t)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="chiprow">
              <SourceChip s={{ kind: "measured", publisher: "NORDCAN", source_id: s0.source_id, source_url: g.sources?.[s0.source_id ?? ""]?.url ?? s0.source_url, period: s0.period,
                what: "Five-year relative survival, age-standardised: Finland against the mean of Sweden and Norway. Gap, years behind and trend are computed from the published values.", note: "gap and trend computed" }} />
            </div>
          </div>
        )}
        <div className="g3side">
          {m.latest && m.baseline_value != null && m.target_value != null && (
            <div className="g3cell">
              <h3>Cancer mortality falls 10%</h3>
              <p className="g3fig num"><b>{pts(m.change_since_baseline_pct ?? 0)}%</b> since {m.baseline_year}{m.remaining_pct != null ? <> · <strong>{one(Math.abs(m.remaining_pct))}</strong> points to go</> : null}</p>
              {done != null && (
                <div className="meter num" role="img" aria-label={`Age-standardised cancer mortality: ${one(m.baseline_value)} in ${m.baseline_year}, ${one(m.latest.value)} in ${m.latest.year}, target ${one(m.target_value)}`}>
                  <div className="track"><i style={{ width: `${Math.max(2, done * 100)}%` }} /></div>
                  <div className="ends"><span>{m.baseline_year}: {one(m.baseline_value)}</span><span>{m.latest.year}: {one(m.latest.value)}</span><span>target {one(m.target_value)}</span></div>
                </div>
              )}
              <div className="chiprow">
                <SourceChip s={{ kind: "measured", source_id: m.source_id, source_url: m.source_url, period: `${m.baseline_year}-${m.latest.year}`, what: `All-cancer deaths per 100,000, age-standardised, Finland${m.baseline_year_stated_in_strategy === false ? `. The strategy does not name a baseline year; ${m.baseline_year} is our reading` : ""}`,
                  value: `${one(m.latest.value)} in ${m.latest.year}`, quote: m.strategy_quote_fi }} />
                {m.baseline_year_stated_in_strategy === false && <span className="small muted">{m.baseline_year} baseline is our reading.</span>}
              </div>
            </div>
          )}
        </div>
      </div>
      {tw && tw.available === false && (
        <p className="g3row small" title={[tw.data_gap_en, tw.who_could_publish_en].filter(Boolean).join(" Who could publish it: ")}>
          <b>Patients are treated within target times:</b> no public figure found, for any cancer or county.
        </p>
      )}
    </section>
  );
}
