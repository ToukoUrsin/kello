import { useMemo, useState } from "react";
import { geoPath, geoTransverseMercator } from "d3-geo";
import { api, AreaMeta, days, eurx, Funnel, Goal3, int, Kind, MeasuredVal, mval, one, Overview, OverviewArea, period, range, SrcRef, STEP_SHORT, useAsync } from "./lib";
import { Failed, Loading, Skeleton } from "./App";
import { SourceChip } from "./Source";
import FunnelPlot from "./Funnel";
import DistanceScatter from "./DistanceScatter";
import ExpertQuote from "./ExpertQuote";
import Scoreboard from "./Scoreboard";
import { Col, Dots } from "./Dots";
import GapChecks from "./GapChecks";

/** One map layer: a value per county, the national value, and where it comes from. */
interface Layer {
  id: string; label: string; title: string; unit: string; kind: Kind; dark: "high" | "low";
  values: Map<string, number>; few: Map<string, string>; national: number | null;
  fmt: (n: number) => string; src: (a: OverviewArea | null) => SrcRef; note?: string;
}
const mv = (a: OverviewArea, k: string): MeasuredVal | null => { const v = a.measured?.[k]; return v && typeof v.value === "number" ? v : null; };
const pct = (n: number) => `${one(n)}%`;
const RAMP = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];
const RAMPS: Record<number, number[]> = { 1: [2], 2: [1, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4] };
const CAPITAL = new Set(["01", "02", "03", "04", "90"]);
const ALAND = "91";
const SW = 30; // legend swatch width, px
const CANCERS: [string, string, string][] = [["lung", "Lung", "lung cancer"], ["pancreas", "Pancreas", "pancreatic cancer"], ["liver", "Liver", "liver cancer"], ["all", "All cancers", "cancer"]];
const DEFINITION = "The registry's term is curative-intent treatment: the first treatment within 12 months of diagnosis was one given to cure, according to hospital records.";
const lowerFirst = (t: string) => (t ? t[0].toLowerCase() + t.slice(1) : t);

function niceBreaks(vals: number[]): number[] {
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || 1;
  const step = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 25, 50, 100].find((s) => s * 5 >= span) ?? span / 5;
  const start = Math.floor(lo / step) * step;
  return [1, 2, 3, 4].map((i) => +(start + i * step).toFixed(2)).filter((b) => b > lo && b < hi);
}
const bin = (v: number, b: number[]) => b.filter((x) => v >= x).length;

function measuredLayer(o: Overview, id: string, key: string, label: string, title: string, unit: string, dark: "high" | "low", fmt: (n: number) => string, note?: string, kind: Kind = "measured"): Layer | null {
  const values = new Map<string, number>();
  let any: MeasuredVal | null = null;
  for (const a of o.areas) { const v = mv(a, key); if (v) { values.set(a.id, v.value); any ??= v; } }
  if (values.size < 2 || !any) return null;
  const few = new Map<string, string>();
  if (values.has(ALAND)) few.set(ALAND, "few cases a year");
  const first = any;
  return {
    id, label, title, unit, kind, dark, values, few, national: first.national ?? null, fmt, note,
    src: (a) => { const v = (a && mv(a, key)) || first; return { kind, source_id: v.source_id, source_url: v.source_url, page: a ? v.page : null, read_by: v.read_by, period: v.period, quote: a ? v.quote : null,
      what: a ? `${title}, ${a.short_en}` : title, value: a ? fmt(v.value) : null }; },
  };
}

function asrLayer(g: Goal3, metric: "incidence_asr" | "mortality_asr", cancer: string): Layer | null {
  const rows = g.county.rows.filter((r) => r.metric === metric && r.cancer === cancer && typeof r.value === "number");
  if (rows.length < 2) return null;
  const c = CANCERS.find((x) => x[0] === cancer) ?? CANCERS[0];
  const meta = g.county.metrics[metric] ?? {};
  const inc = metric === "incidence_asr";
  const few = new Map<string, string>();
  rows.forEach((r) => { if (r.small_n) few.set(r.area_id, r.n != null ? `${int(r.n)} ${inc ? "cases" : "deaths"} in five years` : "few cases"); else if (r.area_id === ALAND) few.set(ALAND, `${int(r.n ?? 0)} ${inc ? "cases" : "deaths"} in five years`); });
  const title = inc ? `New ${c[2]} cases per 100,000 a year, age-standardised` : `Deaths from ${c[2]} per 100,000 a year, age-standardised`;
  return {
    id: inc ? "incidence" : "mortality", label: inc ? "New cases" : "Deaths", title, unit: "per 100,000", kind: "measured", dark: "high",
    values: new Map(rows.map((r) => [r.area_id, r.value as number])), few, national: rows.find((r) => r.national != null)?.national ?? null, fmt: one,
    note: inc ? "Age-standardised, so counties with older residents can be compared. Not adjusted for smoking or anything else."
      : "A death rate mixes how many people get the cancer with how long they live after diagnosis. Compare it with new cases before reading it as a gap in care.",
    src: (a) => ({ kind: "measured", source_id: meta.source_id, source_url: meta.source_url, period: meta.period, what: a ? `${title}, ${a.short_en}` : title,
      value: a ? one(rows.find((r) => r.area_id === a.id)?.value ?? null) : null }),
  };
}

export default function MapView({ onPick, openPlan }: { onPick: (id: string, section?: string) => void; openPlan: (id: string) => void; areas: AreaMeta[] }) {
  const ov = useAsync(api.overview, []);
  const geo = useAsync(api.geo, []);
  const funnel = useAsync(api.funnel, []);
  const goal3 = useAsync(api.goal3, []);
  const [picked, setLayer] = useState<string | null>(null);
  const [cancer, setCancer] = useState("lung");
  const [hot, setHot] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);

  const shapes = useMemo(() => {
    if (!geo.data) return null;
    const W = 440, H = 760;
    const proj = geoTransverseMercator().rotate([-26, 0]).fitExtent([[6, 6], [W - 6, H - 6]], geo.data);
    const path = geoPath(proj);
    const capital = { type: "FeatureCollection" as const, features: geo.data.features.filter((f) => CAPITAL.has(String((f.properties as any)?.id))) };
    const IW = 200, IH = 124;
    const iproj = geoTransverseMercator().rotate([-26, 0]).fitExtent([[3, 3], [IW - 3, IH - 3]], capital);
    const ipath = geoPath(iproj);
    const cb = path.bounds(capital);
    return {
      W, H, IW, IH, cb,
      main: geo.data.features.map((f) => ({ id: String((f.properties as any)?.id), d: path(f) ?? "" })),
      inset: capital.features.map((f) => ({ id: String((f.properties as any)?.id), d: ipath(f) ?? "" })),
    };
  }, [geo.data]);

  const layers = useMemo(() => {
    if (!ov.data) return [];
    const o = ov.data, g = goal3.data;
    return [
      measuredLayer(o, "curative", "curative_intent_pct", "Treated to cure", "Share of lung cancer patients given treatment that aims to cure", "%", "low", pct),
      g ? asrLayer(g, "incidence_asr", cancer) : null,
      g ? asrLayer(g, "mortality_asr", cancer) : null,
      measuredLayer(o, "dxdays", "dx_to_treatment_days", "Days to treatment", "Median days from lung cancer diagnosis to treatment start", "days", "high", (n) => mval(n),
        "Estimated weighted mix for the five university hospital areas, not a county measurement: registry medians by treatment type.", "estimated"),
      measuredLayer(o, "gp", "gp_wait_over_7d_pct", "GP wait", "Share of non-urgent GP visits that waited more than 7 days", "%", "high", pct),
    ].filter((x): x is Layer => !!x);
  }, [ov.data, goal3.data, cancer]);

  if (ov.error) return <Failed center message={ov.error} retry={ov.reload} />;
  // The skeleton has the first screen's own shape: the headline and the three dot grids, the two lines, the button and the path.
  if (!ov.data) return (
    <div className="mapview"><section className="hero" role="status" aria-label="Loading the national picture">
      <div className="skel" style={{ gridArea: "h1" }}><div className="skeleton" style={{ height: 34, width: "92%" }} /><div className="skeleton" style={{ height: 34, width: "70%" }} /></div>
      <div className="heroviz"><div className="dotcols home">{[0, 1, 2].map((i) => <div key={i}><div className="skeleton" style={{ height: 52, width: "60%", marginBottom: 12 }} /><div className="skeleton" style={{ aspectRatio: "1", maxWidth: 240 }} /></div>)}</div></div>
      <div className="skel real"><div className="skeleton" style={{ height: 16, width: "96%" }} /><div className="skeleton" style={{ height: 16, width: "60%" }} /></div>
      <div className="skel plan"><div className="skeleton" style={{ height: 16, width: "90%" }} /><div className="skeleton" style={{ height: 16, width: "74%" }} /></div>
      <div className="heroact"><div className="skeleton" style={{ height: 44, width: 300 }} /></div>
    </section></div>
  );
  const data: Overview = ov.data;
  const m = layers.find((x) => x.id === picked) ?? layers[0];
  const byId = new Map(data.areas.map((a) => [a.id, a]));
  const isAsr = m.id === "incidence" || m.id === "mortality";
  // Counties with few cases are drawn hatched and kept out of the colour scale and the order.
  const have = data.areas.filter((a) => m.values.has(a.id) && !m.few.has(a.id));
  const fewAreas = data.areas.filter((a) => m.values.has(a.id) && m.few.has(a.id));
  const missing = data.areas.filter((a) => !m.values.has(a.id));
  const val = (id: string) => m.values.get(id)!;
  const vals = have.map((a) => val(a.id));
  const breaks = vals.length ? niceBreaks(vals) : [];
  const steps = RAMPS[breaks.length + 1].map((i) => RAMP[i]);
  const ramp = m.dark === "high" ? steps : [...steps].reverse(); // indexed by value bin
  const colour = (v: number) => ramp[bin(v, breaks)];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const ranked = [...have].sort((a, b) => (m.dark === "high" ? val(b.id) - val(a.id) : val(a.id) - val(b.id)));
  const fill = (id: string) => (!m.values.has(id) ? "url(#nodata)" : m.few.has(id) ? "url(#fewcases)" : colour(val(id)));
  const hotArea = hot ? byId.get(hot) : null;
  const national = m.national;
  const barPct = (v: number) => (m.unit === "%" || lo > 0 ? (v / Math.max(hi, national ?? 0)) * 100 : ((v - lo) / (hi - lo || 1)) * 100);
  const unit = m.unit === "%" ? "" : ` ${m.unit}`;
  const say = (id: string) => (!m.values.has(id) ? "not published" : `${m.fmt(val(id))}${unit}${m.few.has(id) ? ` (${m.few.get(id)}: too few to compare)` : ""}`);

  const areaProps = (id: string) => ({
    className: "area" + (hot === id ? " hot" : ""), fill: fill(id), tabIndex: 0, role: "button",
    "aria-label": `${byId.get(id)?.short_en ?? id}: ${say(id)}. Open county.`,
    onMouseMove: (e: React.MouseEvent) => { setHot(id); setTip({ x: e.clientX, y: e.clientY }); },
    onMouseLeave: () => { setHot(null); setTip(null); },
    onFocus: () => setHot(id), onBlur: () => setHot(null),
    onClick: () => onPick(id),
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(id); } },
  });

  const legendVals = breaks; // ascending; the swatches follow the values, so the darkest end is always the worse one
  return (
    <div className="mapview">
      <Lead data={data} funnel={funnel.data} funnelLoading={funnel.loading} funnelRetry={funnel.reload} onPick={onPick} openPlan={openPlan} />
      {funnel.data && <FunnelPlot f={funnel.data} hot={hot} setHot={setHot} onPick={onPick} />}
      {funnel.data && <DistanceScatter f={funnel.data} hot={hot} setHot={setHot} onPick={onPick} />}

      <div className="where">
        <section className="panel mappanel" aria-label="Map of Finland by county">
          <header>
            <h2>{m.title}</h2>
            <div className="seg wrap" role="group" aria-label="What the map shows">
              {layers.map((x) => <button key={x.id} aria-pressed={m.id === x.id} onClick={() => setLayer(x.id)}>{x.label}</button>)}
            </div>
            {isAsr && (
              <div className="seg wrap" role="group" aria-label="Cancer">
                {CANCERS.map(([id, label]) => <button key={id} aria-pressed={cancer === id} onClick={() => setCancer(id)}>{label}</button>)}
              </div>
            )}
            <div className="maptitle">
              <SourceChip s={m.src(null)} />
              {data.fixture && <span className="tag sample">Sample data</span>}
              {m.note && <p className="small muted">{m.note}</p>}
            </div>
          </header>
          <div className="mapwrap">
            {geo.error ? <Failed message={geo.error} retry={geo.reload} /> : !shapes ? <Loading label="Drawing the map" /> : (
              <>
                <div className="legend num" aria-label={`Legend: ${m.title}. Darker is worse.`}>
                  <div className="cap">{m.label}{m.unit === "%" ? ", %" : `, ${m.unit}`}<span className="muted"> · darker is worse</span></div>
                  <div className="sw">{ramp.map((c) => <i key={c} style={{ background: c, width: SW }} />)}</div>
                  <div className="tk" style={{ width: ramp.length * SW }}>{legendVals.map((b, i) => <span key={b} style={{ left: (i + 1) * SW }}>{Number.isInteger(b) ? int(b) : one(b)}</span>)}</div>
                  {fewAreas.length > 0 && <div className="nd"><svg width="18" height="10" aria-hidden="true"><rect width="18" height="10" fill="url(#fewcases)" stroke="var(--line-strong)" /></svg>few cases, not compared ({fewAreas.map((a) => a.short_en).join(", ")})</div>}
                  {missing.length > 0 && <div className="nd"><svg width="18" height="10" aria-hidden="true"><rect width="18" height="10" fill="url(#nodata)" /></svg>not published ({missing.map((a) => a.short_en).join(", ")})</div>}
                </div>
                <div className="mapbox">
                  <svg className="fin" viewBox={`0 0 ${shapes.W} ${shapes.H}`} role="group" aria-label="Counties of Finland">
                    <defs>
                      <pattern id="nodata" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--sunken)" /><line x1="0" y1="0" x2="0" y2="6" stroke="var(--line-strong)" strokeWidth="1.5" /></pattern>
                      <pattern id="fewcases" width="5" height="5" patternUnits="userSpaceOnUse"><rect width="5" height="5" fill="var(--surface)" /><circle cx="2.5" cy="2.5" r="1.1" fill="var(--data)" /></pattern>
                    </defs>
                    {shapes.main.filter((s) => s.id !== hot).map((s) => <path key={s.id} d={s.d} {...areaProps(s.id)} />)}
                    {shapes.main.filter((s) => s.id === hot).map((s) => <path key={s.id} d={s.d} {...areaProps(s.id)} />)}
                    <rect x={shapes.cb[0][0] - 4} y={shapes.cb[0][1] - 4} width={shapes.cb[1][0] - shapes.cb[0][0] + 8} height={shapes.cb[1][1] - shapes.cb[0][1] + 8} fill="none" stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 2" pointerEvents="none" />
                  </svg>
                  <div className="inset">
                    <div className="cap">Capital region, enlarged</div>
                    <svg viewBox={`0 0 ${shapes.IW} ${shapes.IH}`} role="group" aria-label="Capital region counties">
                      {shapes.inset.filter((s) => s.id !== hot).map((s) => <path key={s.id} d={s.d} {...areaProps(s.id)} />)}
                      {shapes.inset.filter((s) => s.id === hot).map((s) => <path key={s.id} d={s.d} {...areaProps(s.id)} />)}
                    </svg>
                  </div>
                </div>
              </>
            )}
          </div>
        </section>

      <section className="panel rank" aria-label="Counties in order">
        <header><h2>Counties, worst first</h2><div className="spacer" /><button className="btn quiet sm" onClick={() => onPick("FI")}>All counties: who gets what</button></header>
        <div className="scroll">
          <table className="num">
            <thead><tr><th /><th>County</th><th className="vh">{m.unit === "%" ? "%" : m.unit}</th><th />{national != null ? <th>vs Finland</th> : null}</tr></thead>
            <tbody>
              {ranked.map((a, i) => {
                const v = val(a.id);
                return (
                  <tr key={a.id} className={hot === a.id ? "hot" : ""} onMouseEnter={() => setHot(a.id)} onMouseLeave={() => setHot(null)} onClick={() => onPick(a.id)}>
                    <td className="r">{i + 1}</td>
                    <td><button className="rowbtn" onClick={(e) => { e.stopPropagation(); onPick(a.id); }} onFocus={() => setHot(a.id)} onBlur={() => setHot(null)}>{a.short_en}</button></td>
                    <td className="v">{m.fmt(v).replace("%", "")}</td>
                    <td className="barcell"><div className="rbwrap"><div className="rb" style={{ width: `${Math.max(1, barPct(v))}%`, background: colour(v) }} />{national != null && <i className="ref" style={{ left: `${barPct(national)}%` }} />}</div></td>
                    {national != null ? <td className="iv">{v - national > 0 ? "+" : v - national < 0 ? "−" : ""}{one(Math.abs(v - national))}</td> : null}
                  </tr>
                );
              })}
              {fewAreas.map((a) => (
                <tr key={a.id} onClick={() => onPick(a.id)}><td className="r" /><td><button className="rowbtn" onClick={(e) => { e.stopPropagation(); onPick(a.id); }}>{a.short_en}</button></td><td className="v muted">{m.fmt(val(a.id)).replace("%", "")}</td><td className="muted" colSpan={3}>{m.few.get(a.id)}: too few to compare</td></tr>
              ))}
              {missing.map((a) => (
                <tr key={a.id} onClick={() => onPick(a.id)}><td className="r" /><td><button className="rowbtn" onClick={(e) => { e.stopPropagation(); onPick(a.id); }}>{a.short_en}</button></td><td className="v muted">–</td><td className="muted" colSpan={3}>not published</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        {national != null && <footer className="small muted num"><i className="refkey" />Finland: {m.fmt(national)}{unit}</footer>}
      </section>
      </div>

      {goal3.data ? <Scoreboard g={goal3.data} /> : goal3.error ? <Failed message={goal3.error} retry={goal3.reload} /> : null}

      {tip && hotArea && (
        <div className="tip num" style={{ left: Math.min(tip.x + 14, window.innerWidth - 290), top: Math.min(tip.y + 14, window.innerHeight - 120) }}>
          <b>{hotArea.short_en}</b>
          {!m.values.has(hotArea.id) ? "Not published for this county" : <>{m.fmt(val(hotArea.id))}{unit} <span>· {m.label.toLowerCase()} ({m.kind})</span></>}<br />
          {m.few.has(hotArea.id) && <><span>{m.few.get(hotArea.id)}: too few to compare</span><br /></>}
          {national != null && m.values.has(hotArea.id) && <><span>Finland {m.fmt(national)}{unit}</span><br /></>}
          {m.id !== "curative" && mv(hotArea, "curative_intent_pct") && <span>{pct(mv(hotArea, "curative_intent_pct")!.value)} given treatment that aims to cure (measured)</span>}
        </div>
      )}
    </div>
  );
}

/* ---------- the first screen: the gap, drawn; that it is real; what closing it costs; one button; the 90-second path ---------- */
const CHANCE: Record<string, string> = { "99.8": "less than once in 500", "95": "less than once in 20" };
function Lead({ data, funnel, funnelLoading = false, funnelRetry, onPick, openPlan }: { data: Overview; funnel: Funnel | null; funnelLoading?: boolean; funnelRetry?: () => void; onPick: (id: string, section?: string) => void; openPlan: (id: string) => void }) {
  const low = funnel?.lowest ?? null;
  // The one recommendation: what the plan for the lowest county costs and closes. Same optimiser answer as its county page and plan.
  const rec = useAsync(() => (low ? api.optimize(low.id, 1_000_000) : Promise.resolve(null)), [low?.id]);
  const src: SrcRef | null = funnel ? { kind: "measured", source_id: funnel.source_id, source_url: funnel.source_url, page: funnel.page, read_by: funnel.read_by, period: funnel.period, quote: funnel.quote,
    what: "Lung cancer patients given treatment that aims to cure (the registry's curative-intent treatment), by county", value: low ? `${low.short_en} ${one((low.k / low.n) * 100)}%, ${funnel.highest.short_en} ${one((funnel.highest.k / funnel.highest.n) * 100)}%` : null } : null;
  const r = rec.data;
  const fa = funnel && low ? funnel.areas.find((a) => a.id === low.id) : null;
  const odds = fa && fa.side === "below" ? CHANCE[fa.outside] : undefined;
  if (!funnel || !low) return (
    <section className="hero" aria-label="The gap">
      <div className="herotext"><h1>Lung cancer care in Finland, county by county.</h1>
        {funnelLoading ? <div className="heroline skeleton" style={{ height: 44 }} /> : <div className="heroline"><Failed message="The county comparison could not be loaded. The map below still opens every county." retry={funnelRetry} /></div>}</div>
    </section>
  );
  const lowPct = (low.k / low.n) * 100, highPct = (funnel.highest.k / funnel.highest.n) * 100;
  const cols: Col[] = [
    { name: low.short_en, cure: lowPct, op: null, gain: 0, main: true },
    { name: "Finland", cure: funnel.national.pct, op: null, gain: 0 },
    { name: funnel.highest.short_en, note: "highest county", cure: highPct, op: null, gain: 0 },
  ];
  return (
    <section className="hero" aria-label="The gap">
        <h1>In {low.short_en}, <b className="num">{low.per_100} of 100</b> lung cancer patients get treatment that aims to cure. In {funnel.highest.short_en}, <b className="num">{funnel.highest.per_100}</b>.</h1>
        <ExpertQuote />
        <GapChecks areaId={low.id} variant="line" />
        <div className="heroviz">
          <div className="dotcols home">{cols.map((c) => <Dots key={c.name} col={c} on={false} />)}</div>
        </div>
        <p className="heroline real">
          <b>It is not chance.</b>{" "}
          {odds ? <>With {int(low.n)} patients, {low.short_en} would fall this far below Finland by chance {odds}.</> : <>{low.short_en} is below Finland's {one(funnel.national.pct)}%.</>}{" "}
          {(() => { const k = funnel.areas.filter((a) => a.side === "below" && a.outside !== "none" && a.id !== low.id).length; return k > 0 ? <>{k} other {k === 1 ? "county is" : "counties are"} also below Finland beyond chance.</> : null; })()}
        </p>
        {data.national_lead && <div className="nationalresult" role="note">
          <span className="eyebrow">Finland, the result</span>
          <p>About <b className="num">{int(data.national_lead.patients_short_per_year)}</b> patients a year miss treatment that aims to cure; <b className="num">{int(data.national_lead.patients_short_in_seven_counties)}</b> are in seven counties.</p>
          <p><a href="#/plan/FI?budget=5000000&objective=gap">A national plan</a> spends <b className="num">{eurx(data.national_lead.plan_spent_eur)}</b> a year and reaches about <b className="num">{int(data.national_lead.plan_extra_curative_patients_per_year)}</b> patients (modelled).</p>
        </div>}
        {data.pathway?.note_en && <p className="heroline pathwayline"><b>Where public data points:</b> treatment is the clearest county gap; Finland does not publish county stage-at-diagnosis or lung-cancer referral-to-specialist times.</p>}
        {r && r.chosen.length > 0 ? (
          <p className="heroline plan">
            <b>The plan.</b> {r.chosen.length} actions for <span className="num">{eurx(r.totals.eur)}</span> a year: {lowerFirst(r.ui.strip.lead_en)}{r.ui.metric === "extra" ? ", by the model" : ""}. <a href={`#/monday/${low.id}`}>Who does what on Monday</a>: each action has an owner, a first step this week and what done looks like in 90 days.
          </p>
        ) : rec.loading ? <div className="heroline skeleton" style={{ height: 44 }} /> : rec.error ? <div className="heroline"><Failed message={rec.error} retry={rec.reload} /></div> : null}
        <div className="heroact">
          <button className="btn primary lg" onClick={() => onPick(low.id)}>See where {low.short_en} loses patients</button>
          {src && <span className="herosrc">Diagnosed {period(funnel.period)} <SourceChip s={src} short /></span>}
        </div>
        <ol className="path" aria-label="The 90-second path">
          <li><button type="button" onClick={() => onPick(low.id)}><span className="pn">1</span><span><b>The gap</b><small>{low.short_en} against Finland, patient by patient</small></span></button></li>
          <li><button type="button" onClick={() => onPick(low.id, "why")}><span className="pn">2</span><span><b>Why</b><small>Is it real, and where the patients are lost</small></span></button></li>
          <li><button type="button" onClick={() => openPlan(low.id)}><span className="pn">3</span><span><b>The plan and the ask</b><small>One page: actions, owners, cost, the pilot</small></span></button></li>
        </ol>
      {data.fixture && <span className="tag sample">Sample data</span>}
    </section>
  );
}
