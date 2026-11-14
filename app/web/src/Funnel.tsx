import { useEffect, useMemo, useRef, useState } from "react";
import { Funnel, FunnelArea, int, one, period } from "./lib";
import { SourceChip } from "./Source";

/** Width of the element, so the chart is drawn at its real size and text never scales. */
function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(Math.round(e[0].contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const where = (a: FunnelArea) => (a.outside === "none" ? "Inside the limits" : `${a.side === "below" ? "Below" : "Above"} the ${a.outside}% limit`);
const names = (xs: FunnelArea[]) => xs.map((a) => a.short_en).join(", ");

/**
 * Funnel plot: one dot per county, x = patients, y = share treated with the aim to cure.
 * The national share is the line; the dashed and dotted curves are where chance alone would keep a county of that size.
 */
export default function FunnelPlot({ f, hot, setHot, onPick }: { f: Funnel; hot: string | null; setHot: (id: string | null) => void; onPick: (id: string) => void }) {
  const [box, W] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const touch = useRef(false);
  const armed = useRef<string | null>(null);   // touch: the first tap shows the numbers, the second opens the county
  const firstTap = useRef(false);
  const narrow = W > 0 && W < 520;
  const H = narrow ? 300 : 248;
  const M = { l: 40, r: narrow ? 14 : 92, t: 20, b: 40 };

  const g = useMemo(() => {
    if (!W) return null;
    const x0 = f.limits[0].n, x1 = f.limits[f.limits.length - 1].n;
    const lows = [...f.areas.map((a) => a.pct), f.limits[0].lo998], highs = [...f.areas.map((a) => a.pct), f.limits[0].hi998];
    const y0 = Math.floor(Math.min(...lows) / 5) * 5, y1 = Math.ceil(Math.max(...highs) / 5) * 5;
    const x = (n: number) => M.l + ((n - x0) / (x1 - x0)) * (W - M.l - M.r);
    const y = (p: number) => M.t + (1 - (p - y0) / (y1 - y0)) * (H - M.t - M.b);
    const curve = (k: "lo95" | "hi95" | "lo998" | "hi998") => f.limits.map((l, i) => `${i ? "L" : "M"}${x(l.n).toFixed(1)},${y(l[k]).toFixed(1)}`).join("");
    const xt = [250, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000].filter((t) => t > x0 && t < x1 && (!narrow || t % 500 === 0));
    const yt: number[] = [];
    for (let t = y0; t <= y1; t += 10) yt.push(t);

    // Direct labels only for counties outside the 95% limits; greedy placement that avoids dots and other labels.
    type Box = { x0: number; y0: number; x1: number; y1: number };
    const hit = (a: Box, b: Box) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
    const dots: Box[] = f.areas.map((a) => ({ x0: x(a.n) - 6, y0: y(a.pct) - 6, x1: x(a.n) + 6, y1: y(a.pct) + 6 }));
    const placed: Box[] = [];
    const at = (px: number) => { const n = x0 + ((px - M.l) / (W - M.l - M.r)) * (x1 - x0); return f.limits.reduce((b, l) => (Math.abs(l.n - n) < Math.abs(b.n - n) ? l : b)); };
    const struck = (b: Box) => {
      const inside = (py: number) => py > b.y0 + 2 && py < b.y1 - 2;
      let n = inside(y(f.national.pct)) ? 2 : 0;
      for (const px of [b.x0, b.x0 + (b.x1 - b.x0) / 4, (b.x0 + b.x1) / 2, b.x1 - (b.x1 - b.x0) / 4, b.x1]) { const l = at(px); for (const k of ["lo95", "hi95", "lo998", "hi998"] as const) if (inside(y(l[k]))) n++; }
      return n;
    };
    const labels: { id: string; text: string; x: number; y: number; anchor: "start" | "end" | "middle" }[] = [];
    const out = f.areas.filter((a) => a.outside !== "none").sort((a, b) => Math.abs(b.pct - f.national.pct) - Math.abs(a.pct - f.national.pct));
    for (const a of out) {
      const cx = x(a.n), cy = y(a.pct), w = a.short_en.length * (narrow ? 7.2 : 6.4) + 4;
      const up = a.side === "above";
      const cands: { x: number; y: number; anchor: "start" | "end" | "middle"; b: Box }[] = [
        { x: cx + 9, y: cy + 4, anchor: "start", b: { x0: cx + 8, y0: cy - 8, x1: cx + 9 + w, y1: cy + 8 } },
        { x: cx - 9, y: cy + 4, anchor: "end", b: { x0: cx - 9 - w, y0: cy - 8, x1: cx - 8, y1: cy + 8 } },
        { x: cx, y: up ? cy - 10 : cy + 20, anchor: "middle", b: { x0: cx - w / 2, y0: up ? cy - 23 : cy + 8, x1: cx + w / 2, y1: up ? cy - 7 : cy + 24 } },
        { x: cx, y: up ? cy + 20 : cy - 10, anchor: "middle", b: { x0: cx - w / 2, y0: up ? cy + 8 : cy - 23, x1: cx + w / 2, y1: up ? cy + 24 : cy - 7 } },
      ];
      // On a phone the plot is narrow and names are long: also try the corners above and below the dot.
      if (narrow) for (const dy of [-12, 22]) for (const [dx, anchor] of [[8, "start"], [-8, "end"]] as const)
        cands.push({ x: cx + dx, y: cy + dy, anchor, b: { x0: dx > 0 ? cx + dx - 1 : cx + dx - w, y0: cy + dy - 12, x1: dx > 0 ? cx + dx + w : cx + dx + 1, y1: cy + dy + 4 } });
      const free = cands.filter((c) => c.b.x0 >= M.l + 2 && c.b.x1 <= W - M.r - 2 && c.b.y0 >= 2 && c.b.y1 <= H - M.b && !placed.some((p) => hit(p, c.b)) && !dots.some((d, i) => f.areas[i].id !== a.id && hit(d, c.b)));
      // Among the free spots, take the one the national line and the limit curves cross least, so no name is struck through.
      const ok = free.map((c) => ({ c, n: struck(c.b) })).sort((p, q) => p.n - q.n)[0]?.c;
      // On a phone a name that a line would strike through is left off; tapping the dot still names the county.
      if (ok && !(narrow && struck(ok.b) > 0)) { placed.push(ok.b); labels.push({ id: a.id, text: a.short_en, x: ok.x, y: ok.y, anchor: ok.anchor }); }
    }
    return { x, y, x0, x1, y0, y1, xt, yt, curve, labels };
  }, [W, H, f, narrow]); // eslint-disable-line react-hooks/exhaustive-deps

  const hotArea = f.areas.find((a) => a.id === (hot ?? pinned)) ?? null;
  const exp = Math.max(1, Math.round(f.expected_outside_95));
  const below = f.areas.filter((a) => a.side === "below").sort((a, b) => a.pct - b.pct), above = f.areas.filter((a) => a.side === "above").sort((a, b) => b.pct - a.pct);
  const flagged = f.areas.filter((a) => a.recording_flag);
  const src = { kind: "measured" as const, source_id: f.source_id, source_url: f.source_url, page: f.page, read_by: f.read_by, period: f.period, quote: f.quote,
    what: "Lung cancer patients and patients treated to cure (curative-intent treatment), by county (counts)", note: undefined };

  return (
    <section className="panel funnel" aria-label="Funnel plot: share treated with the aim to cure, by county">
      <div className="fhead">
        <h2><b>{f.observed_outside_95} of {f.n_areas} counties</b> are further from Finland than chance explains. Chance alone would put about {exp} there.</h2>
        <p className="small muted">Each dot is a county: its number of lung cancer patients (across) and the share treated to cure (up). Small counties swing more by chance, so the bands are wider on the left. Chance keeps a county inside the inner band 19 times in 20, and inside the outer band 499 times in 500. {f.observed_outside_95} of {f.n_areas} are outside the inner band; {f.observed_outside_998} of those are outside the outer band too.</p>
      </div>
      <div className="fplot" ref={box}>
        {g && (
          <svg width={W} height={H} role="group" aria-label={`${f.observed_outside_95} of ${f.n_areas} counties are outside the 95% limits around the national share of ${one(f.national.pct)}%`}>
            {g.yt.map((t) => <g key={t}><line x1={M.l} x2={W - M.r} y1={g.y(t)} y2={g.y(t)} className="grid" /><text x={M.l - 8} y={g.y(t) + 4} textAnchor="end" className="tick">{t}%</text></g>)}
            {g.xt.map((t) => <g key={t}><line x1={g.x(t)} x2={g.x(t)} y1={H - M.b} y2={H - M.b + 4} className="axis" /><text x={g.x(t)} y={H - M.b + 17} textAnchor="middle" className="tick">{int(t)}</text></g>)}
            <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} className="axis" />
            <text x={M.l} y={H - 5} className="tick">Lung cancer patients diagnosed {period(f.period)}</text>
            <path d={g.curve("lo998")} className="lim l998" /><path d={g.curve("hi998")} className="lim l998" />
            <path d={g.curve("lo95")} className="lim l95" /><path d={g.curve("hi95")} className="lim l95" />
            <line x1={M.l} x2={W - M.r} y1={g.y(f.national.pct)} y2={g.y(f.national.pct)} className="nat" />
            {!narrow && (
              <g className="keys">
                <text x={W - M.r + 8} y={g.y(f.national.pct) + 4}>Finland {one(f.national.pct)}%</text>
                <text x={W - M.r + 8} y={g.y(f.limits[f.limits.length - 1].hi95) - 6}>chance, 95%</text>
                <text x={W - M.r + 8} y={g.y(f.limits[f.limits.length - 1].hi998) - 16}>chance, 99.8%</text>
              </g>
            )}
            {hotArea && <line x1={g.x(hotArea.n)} x2={g.x(hotArea.n)} y1={g.y(hotArea.hi)} y2={g.y(hotArea.lo)} className="whisk" />}
            {g.labels.map((l) => <text key={l.id} x={l.x} y={l.y} textAnchor={l.anchor} className={"lab" + (hot === l.id ? " on" : "")}>{l.text}</text>)}
            {f.areas.map((a) => {
              const on = (hot ?? pinned) === a.id;
              return (
                <g key={a.id}>
                  <circle cx={g.x(a.n)} cy={g.y(a.pct)} r={on ? 7 : 5} className={"dot " + (a.outside === "none" ? "in" : "out") + (a.recording_flag ? " hollow" : "")} />
                  <circle cx={g.x(a.n)} cy={g.y(a.pct)} r={14} className="hit" tabIndex={0} role="button"
                    aria-label={`${a.short_en}: ${int(a.k)} of ${int(a.n)} patients, ${one(a.pct)}% (95% interval ${one(a.lo)} to ${one(a.hi)}). ${where(a)}.${a.recording_flag ? " Recording caveat: the share may be understated." : ""} Open county.`}
                    onPointerDown={(e) => { touch.current = e.pointerType !== "mouse"; firstTap.current = touch.current && armed.current !== a.id; armed.current = a.id; }}
                    onMouseMove={(e) => { if (!touch.current) { setHot(a.id); setTip({ x: e.clientX, y: e.clientY }); } }}
                    onMouseLeave={() => { setHot(null); setTip(null); }}
                    onFocus={() => setPinned(a.id)} onBlur={() => { setPinned(null); armed.current = null; }}
                    onClick={() => { if (firstTap.current) { firstTap.current = false; setPinned(a.id); return; } onPick(a.id); }}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(a.id); } }} />
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <div className="ffoot">
        {pinned && hotArea ? (
          <p className="small num" role="status"><b>{hotArea.short_en}</b>: {int(hotArea.k)} of {int(hotArea.n)} patients, {one(hotArea.pct)}% (95% interval {one(hotArea.lo)}–{one(hotArea.hi)}). {where(hotArea)}.{hotArea.recording_flag ? ` Recording caveat: ${hotArea.recording_flag.text_en}` : ""}{" "}
            <button className="btn quiet sm" onClick={() => onPick(hotArea.id)}>Open {hotArea.short_en}</button></p>
        ) : (
          <>
            <SourceChip s={src} />
            <span className="fkeys small muted" aria-hidden="true"><i className="kd out" />beyond chance<i className="kd in" />within chance{flagged.length > 0 && <><i className="kd hollow" />hollow: treatment may be under-recorded</>}{narrow && <><i className="kl l95" />95%<i className="kl l998" />99.8%</>}</span>
            <span className="small"><b>Below Finland beyond chance:</b> {names(below)}. <b>Above:</b> {names(above)}.</span>
            <details className="more flat">
              <summary>How to read this plot</summary>
              <div className="prose">
                <p>Not adjusted for stage or age: the plot shows where to look, not why.{f.missing?.length ? ` ${f.missing.join(", ")}: too few patients to publish.` : ""}</p>
                {flagged.length > 0 && <p>Hollow dots ({names(flagged)}): the registry's own figures suggest some treatment given there is missing from the records, so the share may be understated.</p>}
              </div>
            </details>
          </>
        )}
      </div>
      {tip && hotArea && !pinned && (
        <div className="tip num" style={{ left: Math.min(tip.x + 14, window.innerWidth - 280), top: Math.max(8, tip.y - 96) }}>
          <b>{hotArea.short_en}</b>
          {int(hotArea.k)} of {int(hotArea.n)} patients · {one(hotArea.pct)}%<br />
          <span>95% interval {one(hotArea.lo)}–{one(hotArea.hi)}% · {where(hotArea).toLowerCase()}</span><br />
          {hotArea.recording_flag && <><span>Treatment may be under-recorded here</span><br /></>}
          <span>Select to open the county</span>
        </div>
      )}
    </section>
  );
}
