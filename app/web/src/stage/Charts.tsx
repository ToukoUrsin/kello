import { useState } from "react";
import { eur, one } from "../lib";
import { BudgetCurve, SimPlan } from "./data";

const nice = (lo: number, hi: number, n = 4): number[] => {
  const span = Math.max(1e-9, hi - lo), raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
};

/** Share treated to cure by year: the plan against no plan, the spread of the simulated years, and Finland's share. */
export function SimChart({ sim, upto, w, nat = true, scope }: { sim: SimPlan; upto: number; w: number; nat?: boolean; scope?: string }) {
  const [hot, setHot] = useState<number | null>(null);
  const h = 176, m = { l: 34, r: 76, t: 12, b: 24 };
  const n = sim.band.length;
  const all = sim.band.flatMap((b) => [b.p10, b.p90, b.no_plan_p10, b.no_plan_p90]).concat(sim.national_pct ?? []);
  const ticks = nice(Math.min(...all) - 0.5, Math.max(...all) + 0.5, 4);
  const y0 = Math.min(ticks[0], Math.min(...all)), y1 = Math.max(ticks[ticks.length - 1], Math.max(...all));
  const X = (i: number) => m.l + (i / Math.max(1, n - 1)) * (w - m.l - m.r), Y = (v: number) => m.t + (1 - (v - y0) / (y1 - y0)) * (h - m.t - m.b);
  const line = (f: (i: number) => number) => sim.band.map((_, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(f(i)).toFixed(1)}`).join("");
  const band = (lo: (i: number) => number, hi: (i: number) => number) => `${line(hi)}${sim.band.map((_, i) => `L${X(n - 1 - i).toFixed(1)},${Y(lo(n - 1 - i)).toFixed(1)}`).join("")}Z`;
  const B = sim.band, last = B[n - 1];
  // One number per scope: the line is the model's expected share (the plan page shows the same figure); the band is the spread of the simulated years.
  const plan = (i: number) => B[i].expected ?? B[i].p50;
  const none = (i: number) => (B[i].expected != null ? sim.baseline_pct : B[i].no_plan_p50);
  const what = scope ?? "the plan";
  const label = (i: number) => (i === 0 ? sim.baseline_period?.replace("-", "–").replace(/–20/, "–") ?? String(B[0].year) : String(B[i].year));
  const clipW = X(Math.max(0, Math.min(n - 1, upto))) + 3;
  const show = hot ?? Math.max(0, Math.min(n - 1, upto));
  // Three labels at the right edge: keep them apart.
  const natOn = nat && sim.national_pct != null;
  const ends = [{ k: "plan", y: Y(plan(n - 1)), t: `plan ${one(plan(n - 1))}` }, { k: "none", y: Y(none(n - 1)), t: `no plan ${one(none(n - 1))}` }, ...(natOn ? [{ k: "nat", y: Y(sim.national_pct as number), t: `Finland ${one(sim.national_pct)}` }] : [])].sort((a, b) => a.y - b.y);
  for (let pass = 0; pass < 4; pass++) for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) { const mid = (ends[i].y + ends[i - 1].y) / 2; ends[i - 1].y = mid - 6.5; ends[i].y = mid + 6.5; }
  return (
    <figure className="st-chart">
      <figcaption>Share treated to cure, %, with {what} <span className="tag estimated">estimated</span></figcaption>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Share treated to cure by year in ${sim.runs_total ?? ""} simulated runs: ${one(plan(n - 1))}% with ${what} in ${last.year}, ${one(none(n - 1))}% without.`}
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const i = Math.round(((e.clientX - r.left - m.l) / (w - m.l - m.r)) * (n - 1)); setHot(Math.max(0, Math.min(n - 1, i))); }} onMouseLeave={() => setHot(null)}>
        <defs><clipPath id="st-sim-clip"><rect x={0} y={0} width={clipW} height={h} style={{ transition: "width 700ms cubic-bezier(0.16,1,0.3,1)" }} /></clipPath></defs>
        {ticks.map((t) => <g key={t}><line x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} className="st-grid" /><text x={m.l - 6} y={Y(t) + 4} textAnchor="end" className="st-tick">{t}</text></g>)}
        {B.map((_, i) => <text key={i} x={X(i)} y={h - 6} textAnchor="middle" className={"st-tick" + (i === show ? " hot" : "")}>{label(i)}</text>)}
        {natOn && <line x1={m.l} x2={w - m.r} y1={Y(sim.national_pct as number)} y2={Y(sim.national_pct as number)} className="st-nat" />}
        <g clipPath="url(#st-sim-clip)">
          <path d={band((i) => B[i].no_plan_p10, (i) => B[i].no_plan_p90)} className="st-band none" />
          <path d={band((i) => B[i].p10, (i) => B[i].p90)} className="st-band plan" />
          {(sim.runs ?? []).slice(0, 40).map((r, k) => <path key={k} d={r.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(Math.max(y0, Math.min(y1, v))).toFixed(1)}`).join("")} className="st-runline" />)}
          <path d={line(none)} className="st-line none" />
          <path d={line(plan)} className="st-line plan" />
          {B.map((_, i) => i > 0 && <circle key={i} cx={X(i)} cy={Y(plan(i))} r={3.5} className="st-pt" />)}
        </g>
        {ends.filter((e) => e.k === "nat" || upto >= n - 1).map((e) => <text key={e.k} x={w - m.r + 6} y={e.y + 4} className={"st-lab " + e.k}>{e.t}</text>)}
        {hot != null && <line x1={X(hot)} x2={X(hot)} y1={m.t} y2={h - m.b} className="st-cross" />}
      </svg>
      <p className="st-read num" aria-live="off">
        <b>{label(show)}</b> with {what} {one(plan(show))}% <span className="muted">({one(B[show].p10)} to {one(B[show].p90)})</span> · no plan {one(none(show))}% <span className="muted">({one(B[show].no_plan_p10)} to {one(B[show].no_plan_p90)})</span>
      </p>
      <p className="st-fine on">Line: what the model expects. Band: 8 of 10 simulated years.{sim.plan_above_no_plan_in_100 != null && upto >= n - 1 ? ` In ${sim.plan_above_no_plan_in_100} of 100 simulated ${last.year}s the share with the plan is above the share without.` : ""}</p>
    </figure>
  );
}

/** Patients reached against euros a year: every step is an action the optimiser buys; past the flat point money buys nothing. */
export function BudgetChart({ curve, budget, w, numbers, unit }: { curve: BudgetCurve; budget: number; w: number; numbers: Map<string, number>; unit: string }) {
  const h = 170, m = { l: 30, r: 12, t: 14, b: 24 };
  const pts = [...curve.points].sort((a, b) => a.budget_eur - b.budget_eur);
  const maxB = pts[pts.length - 1]?.budget_eur ?? 1, maxY = Math.max(1, ...pts.map((p) => p.hi), curve.max_extra);
  const ticks = nice(0, maxY, 4);
  const X = (b: number) => m.l + (b / maxB) * (w - m.l - m.r), Y = (v: number) => m.t + (1 - v / Math.max(maxY, ticks[ticks.length - 1])) * (h - m.t - m.b);
  // A plan changes at a budget, not between two: the curve is a staircase.
  const stair = (f: (p: (typeof pts)[number]) => number) => pts.map((p, i) => (i === 0 ? `M${X(p.budget_eur).toFixed(1)},${Y(f(p)).toFixed(1)}` : `H${X(p.budget_eur).toFixed(1)}V${Y(f(p)).toFixed(1)}`)).join("");
  const area = `${stair((p) => p.hi)}V${Y(0).toFixed(1)}H${X(0).toFixed(1)}Z`;
  const at = [...pts].reverse().find((p) => p.budget_eur <= budget + 0.5) ?? pts[0];
  const flat = curve.flat_from_eur;
  // One numbered mark per action, where the plan first buys it; two bought at the same budget sit side by side.
  const marks = [...curve.steps].sort((a, b) => a.at_eur - b.at_eur).map((s) => ({ id: s.intervention_id + s.at_eur, n: numbers.get(s.intervention_id) ?? "", name: s.name_en, x: X(s.at_eur), y: Y((pts.find((q) => q.budget_eur >= s.at_eur - 0.5) ?? at).extra) }));
  marks.forEach((k, i) => { const prev = marks[i - 1]; if (prev && k.x - prev.x < 15 && Math.abs(k.y - prev.y) < 15) k.x = prev.x + 15; });
  return (
    <figure className="st-chart">
      <figcaption>{unit} against euros a year <span className="tag estimated">estimated</span></figcaption>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`The plan at each budget. At ${eur(at.spent_eur)} it reaches about ${one(at.extra)}, range ${one(at.lo)} to ${one(at.hi)}.`}>
        {ticks.map((t) => <g key={t}><line x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} className="st-grid" /><text x={m.l - 6} y={Y(t) + 4} textAnchor="end" className="st-tick">{t}</text></g>)}
        {[0, maxB / 2, maxB].map((b, i) => <text key={i} x={X(b)} y={h - 6} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} className="st-tick">{eur(Math.round(b / 1000) * 1000)}</text>)}
        {flat != null && flat < maxB && <rect x={X(flat)} y={m.t} width={X(maxB) - X(flat)} height={h - m.t - m.b} className="st-flat" />}
        <path d={area} className="st-band plan" />
        <path d={stair((p) => p.extra)} className="st-line plan" />
        {marks.map((s) => <g key={s.id} transform={`translate(${s.x.toFixed(1)},${s.y.toFixed(1)})`}><circle r={7.5} className="st-stepdot" /><text y={3.5} textAnchor="middle" className="st-stepn">{s.n}</text><title>{s.name}</title></g>)}
        <line x1={X(Math.min(budget, maxB))} x2={X(Math.min(budget, maxB))} y1={m.t} y2={h - m.b} className="st-cross" />
        <circle cx={X(Math.min(budget, maxB))} cy={Y(at.extra)} r={4.5} className="st-pt" />
      </svg>
      {flat != null && flat < maxB && <p className="st-fine on">Shaded: more money buys nothing here: the limit is the reachable shortfall.</p>}
    </figure>
  );
}
