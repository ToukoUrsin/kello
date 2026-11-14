import {loadFont as loadSans} from '@remotion/google-fonts/PublicSans';
import {loadFont as loadMono} from '@remotion/google-fonts/IBMPlexMono';
import {Easing, interpolate} from 'remotion';

export const {fontFamily: SANS} = loadSans('normal', {weights: ['400', '500', '600', '700', '800'], subsets: ['latin', 'latin-ext']});
export const {fontFamily: MONO} = loadMono('normal', {weights: ['400', '500', '600'], subsets: ['latin', 'latin-ext']});

export const W = 1920;
export const H = 1080;

// white, black, greys and one blue (the app's own data blue) for "treated with the aim to cure"
export const C = {
	bg: '#FFFFFF',
	ink: '#0B0D10',
	ink2: '#3A3F47',
	dim: '#6E747D',
	faint: '#A9AEB6',
	line: '#E2E4E8',
	wash: '#F3F4F6',
	blue: '#1B5BD0',
	blueSoft: 'rgba(27,91,208,0.12)',
};

export const ease = {
	out: Easing.bezier(0.16, 1, 0.3, 1),
	inOut: Easing.bezier(0.65, 0, 0.35, 1),
	in: Easing.bezier(0.7, 0, 0.84, 0),
	lin: (t: number) => t,
};
export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** 0 → 1 between two times (seconds), eased */
export const ramp = (t: number, a: number, b: number, e: (x: number) => number = ease.out) => interpolate(t, [a, Math.max(b, a + 1e-4)], [0, 1], {...clamp, easing: e});
export const mix = (p: number, a: number, b: number) => a + (b - a) * p;
/** fade in at a, out at b (seconds) */
export const span = (t: number, a: number, b: number, fi = 0.35, fo = 0.3) => Math.min(ramp(t, a, a + fi), 1 - ramp(t, b - fo, b, ease.in));
/** overshoot pop for dots and marks */
export const pop = (t: number, a: number, d = 0.35) => {
	const p = interpolate(t, [a, a + d], [0, 1], clamp);
	return p <= 0 ? 0 : p >= 1 ? 1 : 1 + 2.2 * Math.pow(p - 1, 3) + 1.2 * Math.pow(p - 1, 2);
};
export const fi = (n: number, d = 1) => n.toLocaleString('en-GB', {minimumFractionDigits: d, maximumFractionDigits: d});
