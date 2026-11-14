// Scene and line timings come from the script and the synthesized voice: change a line, re-run make-vo, and
// every scene, caption and cue moves with it. Nothing here is typed by hand.
import script from '../script.json';
import voData from './data/vo.json';

export const FPS = 30;

type Word = {w: string; s: number; e: number};
export type Line = {id: string; scene: string; text: string; file: string; dur: number; words: Word[]; at: number; caption: boolean};
export type Scene = {id: string; dur: number; frames: number; from: number; lines: Line[]};
type ScriptLine = {id: string; text: string; gap?: number; caption?: boolean};
type ScriptScene = {id: string; lead: number; tail: number; min?: number; lines: ScriptLine[]};

const vo = voData as {voice: string; lines: {id: string; scene: string; text: string; file: string; dur: number; words: Word[]}[]};

let cursor = 0;
export const SCENES: Scene[] = (script.scenes as ScriptScene[]).map((sc) => {
	let t = sc.lead;
	const lines: Line[] = [];
	sc.lines.forEach((l, i) => {
		const v = vo.lines.find((x) => x.id === l.id);
		if (!v || v.text !== l.text) throw new Error(`voice-over for line ${l.id} is missing or stale: run scripts/make-vo.mjs`);
		if (i > 0) t += l.gap ?? script.gap;
		lines.push({...v, at: t, caption: l.caption !== false});
		t += v.dur;
	});
	const dur = Math.max(t + sc.tail, sc.min ?? 0);
	const frames = Math.round(dur * FPS);
	const s = {id: sc.id, dur: frames / FPS, frames, from: cursor, lines};
	cursor += frames;
	return s;
});
export const TOTAL = cursor;
export const scene = (id: string) => {
	const s = SCENES.find((x) => x.id === id);
	if (!s) throw new Error(`no scene ${id}`);
	return s;
};
const line = (id: string) => {
	for (const s of SCENES) for (const l of s.lines) if (l.id === id) return l;
	throw new Error(`no line ${id}`);
};
/** when a line starts, in seconds from the start of its scene */
export const at = (id: string) => line(id).at;
export const endOf = (id: string) => line(id).at + line(id).dur;
/** when a word of a line is spoken (seconds from the start of its scene); the first word that starts with `w` */
export const word = (id: string, w: string, nth = 0) => {
	const l = line(id);
	const hits = l.words.filter((x) => x.w.toLowerCase().replace(/[^a-zäö0-9-]/g, '').startsWith(w.toLowerCase()));
	if (!hits[nth]) throw new Error(`line ${id} has no word "${w}"`);
	return l.at + hits[nth].s;
};
