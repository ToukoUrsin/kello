import { useEffect, useRef, useState } from "react";
import { one } from "./lib";

/* ---------- 100 dots = 100 patients ---------- */
export interface Col { name: string; note?: string; cure: number; op: number | null; gain: number; main?: boolean }
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const still = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/* The plan's motion: each patient the plan moves leaves the grey "not treated to cure" pool at the top of the
   column and drops into the treated stack, one after another. Total under 900 ms for the largest gain shown. */
const STAGGER = 90; // ms between two travelling dots, shortened when many move so the whole stays under 900 ms
const FLIGHT = 540; // ms for one dot to travel
const LAND = 0.8; // share of the flight after which the dot is in its slot and its fill appears

/** A number that runs to its new value while the dots fill, so the figure and the picture arrive together. */
function useTween(target: number, ms: number) {
  const [v, setV] = useState(target);
  const at = useRef(target);
  useEffect(() => {
    const a = at.current, b = target;
    if (a === b) return;
    if (still()) { at.current = b; setV(b); return; }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms), x = a + (b - a) * (1 - Math.pow(1 - p, 3));
      at.current = x; setV(x);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

/** Ten by ten, filled from the bottom row up, so three areas side by side read as three levels on one baseline. */
export function Dots({ col, on }: { col: Col; on: boolean }) {
  const a = col.op ?? 0, c = col.cure, g = on ? col.gain : 0;
  const first = Math.floor(c), last = Math.ceil(c + col.gain) - 1;
  const moving = col.gain > 0 ? Math.max(0, last - first) : 0;
  const step = moving > 4 ? 360 / moving : STAGGER;
  const shown = useTween(c + g, moving * step + FLIGHT);
  const landAt = (i: number) => (i - first) * step + FLIGHT * LAND;
  return (
    <figure className={"dotcol" + (col.main ? " main" : "")}>
      <figcaption>
        <b>{col.name}</b>
        <span className="fig num"><strong>{one(c)}</strong>{col.gain > 0 ? <span className={"after" + (on ? " on" : "")} aria-hidden={!on}><span className="arrow" aria-hidden="true" /><strong>{one(shown)}</strong></span> : null}<span className="of">of 100{col.note ? <span className="nt">{col.note}</span> : null}</span></span>
      </figcaption>
      <div className={"dots" + (on && col.gain > 0 ? " flying" : "")} role="img" aria-label={`${col.name}: ${one(c)} of 100 lung cancer patients are treated to cure${col.op != null ? `, ${one(col.op)} of them operated` : ""}${col.gain > 0 && on ? `; with the plan ${one(c + col.gain)}` : ""}.`}>
        {Array.from({ length: 100 }, (_, i) => {
          const opW = clamp01(a - i), cuW = clamp01(c - i), gW = clamp01(c + g - i);
          const moved = col.gain > 0 && i >= first && i <= last;
          // On: the fill appears when the travelling dot lands. Off: the gain drains quickly, top dot first.
          const delay = `${on ? landAt(i) : (last - i) * 40}ms`;
          return (
            <i key={i} className={moved ? "g" + (on ? " on" : "") : undefined} style={moved ? { animationDelay: delay } : undefined}>
              {opW > 0 && <b className="s-op" style={{ width: `${opW * 100}%` }} />}
              {cuW > opW && <b className={col.op == null ? "s-cure" : "s-ot"} style={{ left: `${opW * 100}%`, width: `${(cuW - opW) * 100}%` }} />}
              {moved && <b className="s-gain" style={{ left: `${cuW * 100}%`, width: `${(gW - cuW) * 100}%`, transitionDelay: delay }} />}
            </i>
          );
        })}
        {/* The travellers: one per moved patient, drawn over the grid, starting in the top row of the same column. */}
        {on && col.gain > 0 && Array.from({ length: moving + 1 }, (_, k) => {
          const i = first + k, r = Math.floor(i / 10), cx = i % 10;
          return <span key={i} className="fly" aria-hidden="true" style={{ "--r": r, "--c": cx, "--rise": 9 - r, animationDelay: `${k * step}ms` } as React.CSSProperties} />;
        })}
      </div>
    </figure>
  );
}
