// A screen capture inside the film: a framed browser view with a camera that zooms on the capture's own marks,
// a drawn cursor and click ripples. Nothing here knows pixel positions inside the app: boxes come from the
// capture's marks (film/shots.json → capture.py → src/data/captures/<id>.json). Re-capture and the zooms follow.
import React from 'react';
import {Img, interpolate, staticFile} from 'remotion';
import dots from './data/captures/dots.json';
import top from './data/captures/top.json';
import card from './data/captures/card.json';
import plan from './data/captures/plan.json';
import source from './data/captures/source.json';
import home from './data/captures/home.json';
import gap from './data/captures/gap.json';
import {C, clamp, ease} from './theme';

export type Box = [number, number, number, number];
type Mark = {name: string; t: number; box?: number[]};
export type Cap = {id: string; file: string; duration: number; viewport: number[]; cursor: number[][]; clicks: number[]; marks: Mark[]; api: Record<string, {t: number; json: any}>};

const CAPS: Record<string, Cap> = {home, dots, top, gap, card, plan, source} as any;
export const cap = (id: string) => {
	const c = CAPS[id];
	if (!c) throw new Error(`no capture ${id}`);
	return c;
};
// page size in CSS px of each capture (the video is recorded at viewport x scale)
const dims = (id: string) => ({VW: cap(id).viewport[0], VH: cap(id).viewport[1]});

/** a mark of a capture: its time and box (null box = the whole page). Missing marks fall back so a re-capture with
 *  a renamed mark still renders (and warns in the console). */
export const mark = (id: string, name: string): {t: number; box: Box | null} => {
	const m = cap(id).marks.find((x) => x.name === name);
	if (!m) {
		console.warn(`capture ${id} has no mark ${name}`);
		return {t: 0, box: null};
	}
	return {t: m.t, box: m.box ? (m.box as Box) : null};
};

/** Piecewise time map: from scene second `t` the capture plays from capture second `c` at `rate`. */
export type Seg = {t: number; c: number; rate?: number};
export const capTime = (segs: Seg[], t: number, dur: number) => {
	let s = segs[0];
	for (const x of segs) if (t >= x.t) s = x;
	return Math.min(dur - 0.04, Math.max(0, s.c + (t - s.t) * (s.rate ?? 1)));
};

/** Camera keyframe: at scene second `t` the camera starts moving to `box` (null = whole page) over `d` seconds. */
export type Key = {t: number; box: Box | null; d?: number; pad?: number; max?: number};
type Cam = {cx: number; cy: number; s: number};
const camFor = (VW: number, VH: number, box: Box | null, fw: number, fh: number, pad = 40, max = 2.4): Cam => {
	const base = Math.min(fw / VW, fh / VH);
	if (!box) return {cx: VW / 2, cy: VH / 2, s: base};
	const [x, y, w, h] = box;
	let s = Math.min(fw / (w + 2 * pad), fh / (h + 2 * pad));
	s = Math.max(base, Math.min(s, base * max));
	// keep the view inside the page
	const vw = fw / s;
	const vh = fh / s;
	const cx = Math.min(Math.max(x + w / 2, vw / 2), VW - vw / 2);
	const cy = Math.min(Math.max(y + h / 2, vh / 2), VH - vh / 2);
	return {cx, cy, s};
};
export const camAt = (VW: number, VH: number, keys: Key[], t: number, fw: number, fh: number): Cam => {
	let cur = camFor(VW, VH, keys[0]?.box ?? null, fw, fh, keys[0]?.pad, keys[0]?.max);
	for (let i = 1; i < keys.length; i++) {
		const k = keys[i];
		if (t < k.t) break;
		const nxt = camFor(VW, VH, k.box, fw, fh, k.pad, k.max);
		const p = interpolate(t, [k.t, k.t + (k.d ?? 0.9)], [0, 1], {...clamp, easing: ease.inOut});
		// zoom in log space so it feels even
		const s = Math.exp(Math.log(cur.s) + (Math.log(nxt.s) - Math.log(cur.s)) * p);
		cur = {cx: cur.cx + (nxt.cx - cur.cx) * p, cy: cur.cy + (nxt.cy - cur.cy) * p, s};
	}
	return cur;
};

const Cursor: React.FC<{x: number; y: number; k: number}> = ({x, y, k}) => (
	<svg width={26 / k} height={34 / k} viewBox="0 0 26 34" style={{position: 'absolute', left: x - 3 / k, top: y - 2 / k, overflow: 'visible', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.25))'}}>
		<path d="M3 2 L3 26 L9.5 20 L14 31 L18.5 29 L14 18.5 L23 18.5 Z" fill="#0B0D10" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
	</svg>
);

/**
 * The capture, framed. `x,y,w,h` is the frame on screen (16:9). `t` is scene seconds.
 * `hl` draws a ring and dims the rest around a box between t0 and t1. `overlay` gets a function that maps a capture
 * box to screen pixels at this moment, so callouts can stick to what the camera shows.
 */
export const Screen: React.FC<{
	id: string;
	t: number;
	segs: Seg[];
	keys: Key[];
	x: number;
	y: number;
	w: number;
	h: number;
	hl?: {t0: number; t1: number; box: Box | null}[];
	cursor?: boolean;
	opacity?: number;
	overlay?: (toScreen: (b: Box) => Box) => React.ReactNode;
}> = ({id, t, segs, keys, x, y, w, h, hl = [], cursor = true, opacity = 1, overlay}) => {
	const c = cap(id);
	const {VW, VH} = dims(id);
	const cam = camAt(VW, VH, keys, t, w, h);
	const ct = capTime(segs, t, c.duration);
	const tx = w / 2 - cam.cx * cam.s;
	const ty = h / 2 - cam.cy * cam.s;
	const toScreen = (b: Box): Box => [x + tx + b[0] * cam.s, y + ty + b[1] * cam.s, b[2] * cam.s, b[3] * cam.s];

	// cursor position at capture time ct
	let cx = c.cursor[0]?.[1] ?? VW / 2;
	let cy = c.cursor[0]?.[2] ?? VH / 2;
	for (const p of c.cursor) {
		if (p[0] > ct) break;
		cx = p[1];
		cy = p[2];
	}
	// the capture frame at capture time ct, as a still (scripts/frames.sh unpacks each capture to 30 fps JPEGs);
	// past the end of the capture its last frame holds
	const n = Math.max(1, Math.min(Math.floor((c.duration - 0.1) * 30), Math.round(ct * 30) + 1));
	const vids = <Img src={staticFile(`frames/${c.id}/f${String(n).padStart(5, '0')}.jpg`)} maxRetries={10} delayRenderTimeoutInMilliseconds={240000} style={{width: VW, height: VH, position: 'absolute', left: 0, top: 0}} />;

	const ring = hl
		.map((hh) => ({...hh, a: Math.min(interpolate(t, [hh.t0, hh.t0 + 0.4], [0, 1], clamp), interpolate(t, [hh.t1 - 0.3, hh.t1], [1, 0], clamp))}))
		.filter((hh) => hh.a > 0 && hh.box);
	const clickA = c.clicks.map((k) => ({k, p: (ct - k) / 0.55})).filter((q) => q.p >= 0 && q.p <= 1);
	return (
		<div style={{position: 'absolute', left: x, top: y, width: w, height: h, opacity}}>
			<div style={{position: 'absolute', inset: 0, borderRadius: 14, overflow: 'hidden', background: '#fff', boxShadow: '0 30px 80px rgba(11,13,16,0.14), 0 0 0 1px rgba(11,13,16,0.10)'}}>
				<div style={{position: 'absolute', left: 0, top: 0, width: VW, height: VH, transformOrigin: '0 0', transform: `translate(${tx}px, ${ty}px) scale(${cam.s})`}}>
					{vids}
					{ring.map((r, i) => {
						const [bx, by, bw, bh] = r.box as Box;
						const p = 10 / cam.s;
						return (
							<React.Fragment key={i}>
								<svg width={VW} height={VH} style={{position: 'absolute', left: 0, top: 0, opacity: r.a}}>
									<defs>
										<mask id={`m${i}`}>
											<rect width={VW} height={VH} fill="white" />
											<rect x={bx - p} y={by - p} width={bw + 2 * p} height={bh + 2 * p} rx={10 / cam.s} fill="black" />
										</mask>
									</defs>
									<rect width={VW} height={VH} fill="rgba(255,255,255,0.62)" mask={`url(#m${i})`} />
									<rect x={bx - p} y={by - p} width={bw + 2 * p} height={bh + 2 * p} rx={10 / cam.s} fill="none" stroke={C.blue} strokeWidth={3 / cam.s} />
								</svg>
							</React.Fragment>
						);
					})}
					{clickA.map((q) => (
						<div
							key={q.k}
							style={{
								position: 'absolute',
								left: cx - (40 * q.p) / cam.s,
								top: cy - (40 * q.p) / cam.s,
								width: (80 * q.p) / cam.s,
								height: (80 * q.p) / cam.s,
								borderRadius: '50%',
								border: `${3 / cam.s}px solid ${C.blue}`,
								opacity: 1 - q.p,
							}}
						/>
					))}
					{cursor ? <Cursor x={cx} y={cy} k={cam.s} /> : null}
				</div>
			</div>
			{overlay ? <div style={{position: 'absolute', left: -x, top: -y, width: 1920, height: 1080, pointerEvents: 'none'}}>{overlay(toScreen)}</div> : null}
		</div>
	);
};

/** Segments that pass through the given [scene second, capture second] points (speeds up or slows down between them). */
export const sync = (pts: [number, number][], tailRate = 1): Seg[] =>
	pts.map((p, i) => ({t: p[0], c: p[1], rate: i + 1 < pts.length ? Math.max(0.05, (pts[i + 1][1] - p[1]) / (pts[i + 1][0] - p[0])) : tailRate}));

/** The standard frames: `side` leaves a panel on the right, `wide` fills the middle. */
export const FRAME = {
	side: {x: 100, y: 196, w: 1200, h: 675},
	wide: {x: 260, y: 182, w: 1400, h: 788},
	// v4: the page near full frame under a headline band; captions sit below it
	full: {x: 48, y: 150, w: 1824, h: 822},
};
/** the smallest box that holds all the given boxes */
export const union = (...bs: (Box | null)[]): Box | null => {
	const v = bs.filter(Boolean) as Box[];
	if (!v.length) return null;
	const x0 = Math.min(...v.map((b) => b[0]));
	const y0 = Math.min(...v.map((b) => b[1]));
	const x1 = Math.max(...v.map((b) => b[0] + b[2]));
	const y1 = Math.max(...v.map((b) => b[1] + b[3]));
	return [x0, y0, x1 - x0, y1 - y0];
};
/** a box grown by dx, dy on each side */
export const grow = (b: Box | null, dx: number, dy = dx): Box | null => (b ? [b[0] - dx, b[1] - dy, b[2] + 2 * dx, b[3] + 2 * dy] : null);

/** keep the left part of a wide box (a full-width table row: label, value and the start of its bar) */
export const cropW = (b: Box | null, w: number): Box | null => (b ? [b[0], b[1], Math.min(b[2], w), b[3]] : null);
