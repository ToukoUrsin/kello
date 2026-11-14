import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {FPS} from './timeline';
import film from './data/film.json';
import {C, MONO, SANS, ease, fi, ramp} from './theme';

export const MAP = film.map as {w: number; h: number; areas: {id: string; name: string; name_fi: string; d: string; c: number[]}[]};

/** Scene headline, top left: a small kicker and one line. */
export const Head: React.FC<{kicker?: string; title: React.ReactNode; t: number; x?: number; y?: number; size?: number}> = ({kicker, title, t, x = 120, y = 64, size = 46}) => (
	<div style={{position: 'absolute', left: x, top: y, opacity: ramp(t, 0.05, 0.5), translate: `0px ${(1 - ramp(t, 0.05, 0.6)) * 10}px`}}>
		{kicker ? <div style={{fontFamily: SANS, fontSize: 19, fontWeight: 600, letterSpacing: 2.2, color: C.dim, textTransform: 'uppercase', marginBottom: 12}}>{kicker}</div> : null}
		<div style={{fontFamily: SANS, fontSize: size, fontWeight: 700, color: C.ink, letterSpacing: -0.9, lineHeight: 1.12}}>{title}</div>
	</div>
);

/** Where the numbers on screen come from; bottom left, small but readable at 1080p. */
export const Source: React.FC<{children: React.ReactNode; t: number; at?: number; x?: number; y?: number}> = ({children, t, at = 0.6, x = 120, y = 934}) => (
	<div style={{position: 'absolute', left: x, top: y, fontFamily: SANS, fontSize: 19, color: C.dim, opacity: ramp(t, at, at + 0.5), letterSpacing: 0.1}}>{children}</div>
);

/** The app's own mark: a clock face. The hands settle as it appears. */
export const Clock: React.FC<{size: number; p?: number; color?: string}> = ({size, p = 1, color = C.ink}) => {
	const minute = -150 * (1 - p);
	const hour = -40 * (1 - p);
	return (
		<svg width={size} height={size} viewBox="0 0 32 32">
			<circle cx="16" cy="16" r="13" fill="none" stroke={color} strokeWidth="2.6" strokeDasharray={82} strokeDashoffset={82 * (1 - Math.min(1, p * 1.4))} transform="rotate(-90 16 16)" />
			<path d="M16 16V8" fill="none" stroke={color} strokeWidth="2.6" strokeLinecap="round" transform={`rotate(${minute} 16 16)`} />
			<path d="M16 16l6 4" fill="none" stroke={color} strokeWidth="2.6" strokeLinecap="round" transform={`rotate(${hour} 16 16)`} />
		</svg>
	);
};

export const Wordmark: React.FC<{size: number; p?: number}> = ({size, p = 1}) => (
	<div style={{display: 'flex', alignItems: 'center', gap: size * 0.2}}>
		<Clock size={size * 0.92} p={p} />
		<div style={{fontFamily: SANS, fontSize: size, fontWeight: 800, color: C.ink, letterSpacing: -size * 0.035, lineHeight: 1}}>Kello</div>
	</div>
);

/** Finland by wellbeing services county, from the app's own geometry. `fill` and `stroke` decide per county. */
export const FinlandMap: React.FC<{
	height: number;
	fill?: (id: string) => string;
	stroke?: (id: string) => string;
	strokeWidth?: number;
	opacity?: number;
	children?: React.ReactNode;
	style?: React.CSSProperties;
}> = ({height, fill = () => 'none', stroke = () => C.faint, strokeWidth = 1.2, opacity = 1, children, style}) => {
	const k = height / MAP.h;
	return (
		<svg width={MAP.w * k} height={height} viewBox={`0 0 ${MAP.w} ${MAP.h}`} style={{overflow: 'visible', opacity, ...style}}>
			{MAP.areas.map((a) => (
				<path key={a.id} d={a.d} fill={fill(a.id)} stroke={stroke(a.id)} strokeWidth={strokeWidth / k} strokeLinejoin="round" />
			))}
			{children}
		</svg>
	);
};
export const areaOf = (id: string) => {
	const a = MAP.areas.find((x) => x.id === id);
	if (!a) throw new Error(`no area ${id}`);
	return a;
};

/** A grid of people as dots; the first `filled` are solid. */
export const Dots: React.FC<{
	n: number;
	cols: number;
	gap: number;
	r: number;
	appear: (i: number) => number; // 0..1 scale
	fill: (i: number) => number; // 0..1 how solid
	color?: string;
	extra?: (i: number) => number; // 0..1 ring for "would be treated"
}> = ({n, cols, gap, r, appear, fill, color = C.blue, extra}) => (
	<svg width={(cols - 1) * gap + 2 * r + 4} height={(Math.ceil(n / cols) - 1) * gap + 2 * r + 4} style={{overflow: 'visible', display: 'block'}}>
		{Array.from({length: n}, (_, i) => {
			const a = appear(i);
			if (a <= 0) return null;
			const f = fill(i);
			const x = (i % cols) * gap + r + 2;
			const y = Math.floor(i / cols) * gap + r + 2;
			const e = extra ? extra(i) : 0;
			return (
				<g key={i}>
					<circle cx={x} cy={y} r={r * a} fill={C.line} />
					{f > 0 ? <circle cx={x} cy={y} r={r * a * (0.4 + 0.6 * f)} fill={color} opacity={f} /> : null}
					{e > 0 ? <circle cx={x} cy={y} r={r * (1 + 0.5 * (1 - e))} fill="none" stroke={color} strokeWidth={2.5} opacity={e} /> : null}
				</g>
			);
		})}
	</svg>
);

export const Num: React.FC<{children: React.ReactNode; size: number; color?: string; style?: React.CSSProperties}> = ({children, size, color = C.ink, style}) => (
	<span style={{fontFamily: SANS, fontSize: size, fontWeight: 800, color, letterSpacing: -size * 0.04, lineHeight: 0.95, fontVariantNumeric: 'tabular-nums lining-nums', ...style}}>{children}</span>
);

export const Mono: React.FC<{children: React.ReactNode; size?: number; color?: string; style?: React.CSSProperties}> = ({children, size = 18, color = C.ink2, style}) => (
	<span style={{fontFamily: MONO, fontSize: size, color, ...style}}>{children}</span>
);

export const Fill: React.FC<{children?: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => <AbsoluteFill style={{background: C.bg, ...style}}>{children}</AbsoluteFill>;

/** seconds since the start of the current scene */
export const useT = () => useCurrentFrame() / FPS;

/** a number that counts up from `from` to `to` between a and b (seconds) */
export const count = (t: number, a: number, b: number, to: number, from = 0, d = 0) => {
	const v = from + (to - from) * ramp(t, a, b, ease.out);
	return d ? fi(v, d) : Math.round(v).toLocaleString('en-GB');
};

/** A white card with a big number and a line under it; slides in at `at`. */
export const StatCard: React.FC<{t: number; at: number; big: React.ReactNode; label: React.ReactNode; sub?: React.ReactNode; x: number; y: number; w?: number; tone?: string; size?: number}> = ({
	t,
	at,
	big,
	label,
	sub,
	x,
	y,
	w = 480,
	tone = C.ink,
	size = 84,
}) => {
	const a = ramp(t, at, at + 0.45);
	if (a <= 0) return null;
	return (
		<div
			style={{
				position: 'absolute',
				left: x,
				top: y,
				width: w,
				opacity: a,
				translate: `${(1 - a) * 24}px 0px`,
				background: '#fff',
				borderRadius: 16,
				padding: size < 70 ? '16px 24px 18px' : '22px 28px 24px',
				boxShadow: '0 18px 50px rgba(11,13,16,0.10), 0 0 0 1px rgba(11,13,16,0.08)',
			}}
		>
			<Num size={size} color={tone}>
				{big}
			</Num>
			<div style={{fontFamily: SANS, fontSize: size < 70 ? 25 : 27, fontWeight: 600, color: C.ink, marginTop: size < 70 ? 6 : 10, lineHeight: 1.2}}>{label}</div>
			{sub ? <div style={{fontFamily: SANS, fontSize: size < 70 ? 20 : 21, color: C.dim, marginTop: 6, lineHeight: 1.3}}>{sub}</div> : null}
		</div>
	);
};
