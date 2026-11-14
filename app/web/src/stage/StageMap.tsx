import { memo, useEffect, useRef } from "react";
import { Cam, DotM, Layout, PlaceM, Shape } from "./model";

/** Moves the camera: writes --k, --ik, --tx, --ty on the stage, which the map and everything pinned to it read. */
export function useCamera(root: React.RefObject<HTMLElement>, target: Cam, layout: Layout, reduced: boolean) {
  const cur = useRef<Cam | null>(null);
  const raf = useRef(0);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const write = (c: Cam) => {
      cur.current = c;
      el.style.setProperty("--k", String(c.k)); el.style.setProperty("--ik", String(1 / c.k)); el.style.setProperty("--pk", String(Math.pow(c.k, -0.6)));
      el.style.setProperty("--tx", `${c.tx}px`); el.style.setProperty("--ty", `${c.ty}px`);
    };
    cancelAnimationFrame(raf.current);
    const from = cur.current;
    if (!from || reduced || (Math.abs(from.k - target.k) < 1e-3 && Math.abs(from.tx - target.tx) < 0.5 && Math.abs(from.ty - target.ty) < 0.5)) { write(target); return; }
    // Zoom around the middle of the free part of the stage: the point under it travels in a straight line, the scale geometrically.
    const cx = (layout.region[0] + layout.region[2]) / 2, cy = (layout.region[1] + layout.region[3]) / 2;
    const p0 = [(cx - from.tx) / from.k, (cy - from.ty) / from.k], p1 = [(cx - target.tx) / target.k, (cy - target.ty) / target.k];
    const t0 = performance.now(), ms = 900;
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 4);
      const k = from.k * Math.pow(target.k / from.k, e);
      const x = p0[0] + (p1[0] - p0[0]) * e, y = p0[1] + (p1[1] - p0[1]) * e;
      write(p >= 1 ? target : { k, tx: cx - k * x, ty: cy - k * y });
      if (p < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.k, target.tx, target.ty, reduced]);
}

const Places = memo(function Places({ places, on, focus, closer }: { places: PlaceM[]; on: boolean; focus: string | null; closer: Set<string> | null }) {
  const n = Math.max(1, places.length);
  return (
    <g className={"st-places" + (on ? " on" : "")} aria-hidden="true">
      {places.map((p) => (
        <circle key={p.id} r={p.r} transform-origin="0 0" className={(focus && p.county !== focus ? "far" : "") + (closer?.has(p.id) ? " closer" : "")} style={{ transform: `translate(${p.x}px, ${p.y}px) scale(var(--pk, 1))`, transitionDelay: `${Math.round((p.rank / n) * 700)}ms` }} />
      ))}
    </g>
  );
});

export interface Seg { id: string; x1: number; y1: number; x2: number; y2: number; cls?: string }
export interface MapProps {
  layout: Layout; shapes: Shape[]; mode: "gap" | "work"; fills: Map<string, string>; filled: Set<string> | null; focus: string | null; few: Set<string>;
  places: PlaceM[]; placesOn: boolean; closer: Set<string> | null;
  dots: DotM[]; dotCls: string[]; segs: Seg[];
  onHover?: (id: string | null, e?: React.MouseEvent) => void; onPick?: (id: string) => void; placing?: boolean; onPlace?: (bx: number, by: number) => void; cam: Cam; label: string;
}

export default function StageMap(p: MapProps) {
  const { layout: l, shapes } = p;
  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!p.placing || !p.onPlace) return;
    const r = e.currentTarget.getBoundingClientRect();
    p.onPlace((e.clientX - r.left - p.cam.tx) / p.cam.k, (e.clientY - r.top - p.cam.ty) / p.cam.k);
  };
  return (
    <svg className={`st-svg ${p.mode}` + (p.placing ? " placing" : "")} width={l.W} height={l.H} viewBox={`0 0 ${l.W} ${l.H}`} role="img" aria-label={p.label} onClick={click}>
      <defs>
        <pattern id="st-few" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#eeefec" /><rect width="1.4" height="6" fill="#b9bdb9" /></pattern>
        <pattern id="st-est" width="2.6" height="2.6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2.6" height="2.6" fill="#cde2fb" /><rect width="1.2" height="2.6" fill="#1c5cab" /></pattern>
      </defs>
      <g className="st-cam">
        <g className="st-areas">
          {shapes.map((s) => {
            const on = !p.filled || p.filled.has(s.id);
            const fill = p.mode === "gap" ? (on ? (p.few.has(s.id) ? "url(#st-few)" : p.fills.get(s.id) ?? "url(#st-few)") : undefined) : undefined;
            return (
              <path key={s.id} d={s.d} className={"st-area" + (on ? " on" : "") + (p.focus === s.id ? " focus" : "") + (p.onPick && !p.placing ? " pick" : "")} style={fill ? { fill } : undefined}
                onMouseMove={p.onHover ? (e) => p.onHover!(s.id, e) : undefined} onMouseLeave={p.onHover ? () => p.onHover!(null) : undefined} onClick={p.onPick && !p.placing ? () => p.onPick!(s.id) : undefined} />
            );
          })}
        </g>
        {p.places.length > 0 && <Places places={p.places} on={p.placesOn} focus={p.focus} closer={p.closer} />}
        <g className="st-segs" aria-hidden="true">
          {p.segs.map((s) => <path key={s.id} d={`M${s.x1},${s.y1}L${s.x2},${s.y2}`} pathLength={1} className={`st-seg ${s.cls ?? ""}`} />)}
        </g>
        <g className="st-dots" aria-hidden="true">
          {p.dots.map((d, i) => (
            <g key={d.id} style={{ transform: `translate(${d.x}px, ${d.y}px) scale(calc(var(--ik) * var(--dot, 1)))` }}>
              <circle r={3.7} className={`st-dot ${p.dotCls[i]}`} />
            </g>
          ))}
        </g>
      </g>
    </svg>
  );
}

/** Something pinned to a point of the map but drawn at screen size: it follows the camera through CSS variables. */
export function Pinned({ x, y, className, children, style, ...rest }: { x: number; y: number; className?: string; children?: React.ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={`st-pinned ${className ?? ""}`} style={{ ...style, ["--x" as string]: `${x}px`, ["--y" as string]: `${y}px` }}>{children}</div>;
}
