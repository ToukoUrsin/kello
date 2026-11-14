import { useEffect, useMemo, useRef, useState } from "react";
import { Funnel, FunnelArea, one } from "./lib";

type Box = { x0: number; y0: number; x1: number; y1: number };
const hit = (a: Box, b: Box) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;

/**
 * One dot per county: distance to the nearest university hospital (across) against the share treated to cure (up).
 * Shown next to the funnel plot: the funnel says which counties differ, this says what they have in common.
 */
export default function DistanceScatter({ f, hot, setHot, onPick }: { f: Funnel; hot: string | null; setHot: (id: string | null) => void; onPick: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(0);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver((e) => setW(Math.round(e[0].contentRect.width)));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  const rows = useMemo(() => f.areas.filter((a) => a.km_to_university_hospital != null), [f]);
  const d = f.distance;
  const narrow = W > 0 && W < 520;
  const H = narrow ? 280 : 236;
  const M = { l: 40, r: narrow ? 14 : 92, t: 16, b: 40 };

  const g = useMemo(() => {
    if (!W || !rows.length) return null;
    const km = (a: FunnelArea) => a.km_to_university_hospital as number;
    const x1 = Math.ceil(Math.max(...rows.map(km)) / 50) * 50;
    const y0 = Math.floor(Math.min(...rows.map((a) => a.pct)) / 5) * 5, y1 = Math.ceil(Math.max(...rows.map((a) => a.pct)) / 5) * 5;
    const x = (v: number) => M.l + (v / x1) * (W - M.l - M.r);
    const y = (p: number) => M.t + (1 - (p - y0) / (y1 - y0)) * (H - M.t - M.b);
    const xt: number[] = [];
    for (let t = 0; t <= x1; t += narrow ? 100 : 50) xt.push(t);
    const yt: number[] = [];
    for (let t = y0; t <= y1; t += 10) yt.push(t);
    // Named: the counties furthest from Finland's share, and the distant ones that are not below it.
    const nat = f.national.pct;
    const named = rows.filter((a) => Math.abs(a.pct - nat) >= 6 || (km(a) >= 190 && a.pct >= nat)).sort((a, b) => Math.abs(b.pct - nat) - Math.abs(a.pct - nat));
    const dots: Box[] = rows.map((a) => ({ x0: x(km(a)) - 6, y0: y(a.pct) - 6, x1: x(km(a)) + 6, y1: y(a.pct) + 6 }));
    const placed: Box[] = [];
    const labels: { id: string; text: string; x: number; y: number; anchor: "start" | "end" | "middle" }[] = [];
    for (const a of named) {
      const cx = x(km(a)), cy = y(a.pct), w = a.short_en.length * (narrow ? 7.2 : 6.4) + 4;
      const cands: { x: number; y: number; anchor: "start" | "end" | "middle"; b: Box }[] = [
        { x: cx + 9, y: cy + 4, anchor: "start", b: { x0: cx + 8, y0: cy - 8, x1: cx + 9 + w, y1: cy + 8 } },
        { x: cx - 9, y: cy + 4, anchor: "end", b: { x0: cx - 9 - w, y0: cy - 8, x1: cx - 8, y1: cy + 8 } },
        { x: cx, y: cy + 20, anchor: "middle", b: { x0: cx - w / 2, y0: cy + 8, x1: cx + w / 2, y1: cy + 24 } },
        { x: cx, y: cy - 10, anchor: "middle", b: { x0: cx - w / 2, y0: cy - 23, x1: cx + w / 2, y1: cy - 7 } },
        { x: cx - 8, y: cy + 20, anchor: "end", b: { x0: cx - 8 - w, y0: cy + 8, x1: cx - 7, y1: cy + 24 } },
        { x: cx - 8, y: cy - 10, anchor: "end", b: { x0: cx - 8 - w, y0: cy - 23, x1: cx - 7, y1: cy - 7 } },
      ];
      const natY = y(nat);
      const ok = cands.find((c) => c.b.x0 >= M.l + 2 && c.b.x1 <= W - 2 && c.b.y0 >= 0 && c.b.y1 <= H - M.b && !(natY > c.b.y0 - 2 && natY < c.b.y1 + 2)
        && !placed.some((p) => hit(p, c.b)) && !dots.some((q, i) => rows[i].id !== a.id && hit(q, c.b)));
      if (ok) { placed.push(ok.b); labels.push({ id: a.id, text: a.short_en, x: ok.x, y: ok.y, anchor: ok.anchor }); }
    }
    // Least-squares line through the counties: a reading aid for the direction, nothing more.
    const n = rows.length, mx = rows.reduce((s, a) => s + km(a), 0) / n, my = rows.reduce((s, a) => s + a.pct, 0) / n;
    const slope = rows.reduce((s, a) => s + (km(a) - mx) * (a.pct - my), 0) / rows.reduce((s, a) => s + (km(a) - mx) ** 2, 0);
    const xa = Math.min(...rows.map(km)), xb = Math.max(...rows.map(km));
    const trend = { x1: x(xa), y1: y(my + slope * (xa - mx)), x2: x(xb), y2: y(my + slope * (xb - mx)) };
    return { x, y, x1, xt, yt, labels, km, trend };
  }, [W, H, f, rows, narrow]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!d || rows.length < 10) return null;
  const far = rows.filter((a) => (a.km_to_university_hospital as number) >= 190 && a.pct >= f.national.pct).map((a) => a.short_en);
  const hotArea = rows.find((a) => a.id === hot) ?? null;
  return (
    <section className="panel funnel distance" aria-label="Distance to a university hospital against the share treated to cure, by county">
      <div className="fhead">
        <h2><b>The further people live from a university hospital</b>, the fewer are treated to cure.</h2>
        <p className="small muted">Each dot is a county: average distance from home to the nearest university hospital (across) and the share treated to cure (up).
          Rank correlation {d.rho.toFixed(2).replace("-", "−")} across {d.n} counties{d.rho_given_age != null && <>; {d.rho_given_age.toFixed(2).replace("-", "−")} with the share of residents over 65 held fixed, because the distant counties are also the older ones</>}.
          {far.length > 0 && <> {far.join(" and ")} {far.length === 1 ? "is" : "are"} far away and still not below Finland, so distance is not fate.</>}</p>
      </div>
      <div className="fplot" ref={box}>
        {g && (
          <svg width={W} height={H} role="group" aria-label={`Counties further from a university hospital treat fewer lung cancer patients to cure: rank correlation ${d.rho} across ${d.n} counties`}>
            {g.yt.map((t) => <g key={t}><line x1={M.l} x2={W - M.r} y1={g.y(t)} y2={g.y(t)} className="grid" /><text x={M.l - 8} y={g.y(t) + 4} textAnchor="end" className="tick">{t}%</text></g>)}
            {g.xt.map((t) => <g key={t}><line x1={g.x(t)} x2={g.x(t)} y1={H - M.b} y2={H - M.b + 4} className="axis" /><text x={g.x(t)} y={H - M.b + 17} textAnchor="middle" className="tick">{t}</text></g>)}
            <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} className="axis" />
            <text x={M.l} y={H - 5} className="tick">{narrow ? "Kilometres to the nearest university hospital" : "Kilometres to the nearest university hospital, average for residents"}</text>
            <line x1={M.l} x2={W - M.r} y1={g.y(f.national.pct)} y2={g.y(f.national.pct)} className="nat" />
            <line {...g.trend} className="lim l95" />
            {!narrow && <g className="keys"><text x={W - M.r + 8} y={g.y(f.national.pct) + 4}>Finland {one(f.national.pct)}%</text></g>}
            {g.labels.map((l) => <text key={l.id} x={l.x} y={l.y} textAnchor={l.anchor} className={"lab" + (hot === l.id ? " on" : "")}>{l.text}</text>)}
            {rows.map((a) => (
              <g key={a.id}>
                <circle cx={g.x(g.km(a))} cy={g.y(a.pct)} r={hot === a.id ? 7 : 5} className={"dot " + (a.outside === "none" ? "in" : "out")} />
                <circle cx={g.x(g.km(a))} cy={g.y(a.pct)} r={14} className="hit" tabIndex={0} role="button"
                  aria-label={`${a.short_en}: ${Math.round(g.km(a))} km, ${one(a.pct)}% treated to cure. Open county.`}
                  onMouseEnter={() => setHot(a.id)} onMouseLeave={() => setHot(null)} onFocus={() => setHot(a.id)} onBlur={() => setHot(null)}
                  onClick={() => onPick(a.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(a.id); } }}><title>{`${a.short_en}: ${Math.round(g.km(a))} km, ${one(a.pct)}% treated to cure`}</title></circle>
              </g>
            ))}
          </svg>
        )}
      </div>
      <div className="ffoot">
        {hotArea
          ? <p className="small num" role="status"><b>{hotArea.short_en}</b>: {Math.round(hotArea.km_to_university_hospital as number)} km on average, {one(hotArea.pct)}% treated to cure.</p>
          : <span className="small"><b>What the plans do about it:</b> travel and hotel paid for treatment trips, and a weekly video review with the university hospital's specialists, so the decision does not depend on the trip.</span>}
        <span className="fkeys small muted"><span className="tag estimated">Estimated</span> distance: straight line from each municipality to the nearest university hospital, weighted by residents, times 1.3 for roads. A pattern between counties, not proof for any patient.</span>
      </div>
    </section>
  );
}
