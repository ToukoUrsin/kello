import React from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {FPS, SCENES, TOTAL} from './timeline';
import music from './data/music.json';
import {C, SANS, clamp} from './theme';
import {Hook, Reveal, Real, Switch, Card, Orders, Verify, Plan, Sources, Ask} from './scenes/V5';

const BY_ID: Record<string, React.FC> = {hook: Hook, reveal: Reveal, real: Real, switch: Switch, card: Card, orders: Orders, verify: Verify, plan: Plan, sources: Sources, ask: Ask};

/** Each scene fades in from white over a few frames; the cut stays crisp but never pops. */
const SceneWrap: React.FC<{children: React.ReactNode; frames: number; fade?: number}> = ({children, frames, fade = 7}) => {
	const f = useCurrentFrame();
	const o = Math.min(interpolate(f, [0, fade], [0, 1], clamp), interpolate(f, [frames - 4, frames], [1, 0], clamp));
	return <AbsoluteFill style={{opacity: o}}>{children}</AbsoluteFill>;
};

type Chunk = {text: string; s: number; e: number};
/** Captions: the voice-over text, in chunks of a few words that break at punctuation, timed by the TTS alignment. */
const chunks: Chunk[] = (() => {
	const out: Chunk[] = [];
	for (const sc of SCENES)
		for (const l of sc.lines) {
			if (!l.caption) continue;
			const base = sc.from / FPS + l.at;
			let cur: typeof l.words = [];
			const flush = () => {
				if (!cur.length) return;
				out.push({text: cur.map((w) => w.w).join(' '), s: base + cur[0].s, e: base + cur[cur.length - 1].e});
				cur = [];
			};
			l.words.forEach((w, i) => {
				cur.push(w);
				const punct = /[.,?!:;]$/.test(w.w);
				const left = l.words.length - i - 1;
				if ((punct && cur.length >= 3 && left >= 2) || cur.length >= 8 || (punct && /[.?!]$/.test(w.w) && left > 0)) flush();
			});
			flush();
		}
	// each chunk stays until the next one starts (or a short beat after its last word)
	return out.map((c, i) => ({...c, e: Math.min(out[i + 1]?.s ?? Infinity, c.e + 0.45)}));
})();

const Captions: React.FC = () => {
	const t = useCurrentFrame() / FPS;
	const c = chunks.find((x) => t >= x.s - 0.05 && t < x.e);
	if (!c) return null;
	const a = Math.min(interpolate(t, [c.s - 0.05, c.s + 0.08], [0, 1], clamp), interpolate(t, [c.e - 0.08, c.e], [1, 0], clamp));
	return (
		<div style={{position: 'absolute', left: 0, right: 0, top: 994, display: 'flex', justifyContent: 'center', opacity: a}}>
			<div style={{fontFamily: SANS, fontSize: 38, fontWeight: 600, color: C.ink, background: 'rgba(255,255,255,0.94)', padding: '6px 18px', borderRadius: 10, letterSpacing: -0.2, lineHeight: 1.2}}>{c.text}</div>
		</div>
	);
};

// the music bed (ElevenLabs Music, made for this film) sits under the voice and ducks while a line plays
const VO_WIN = SCENES.flatMap((s) => s.lines.map((l) => [s.from + l.at * FPS, s.from + (l.at + l.dur) * FPS]));
const musicVol = (f: number) => {
	const duck = Math.max(0, ...VO_WIN.map(([a, b]) => Math.min(interpolate(f, [a - 8, a], [0, 1], clamp), interpolate(f, [b, b + 12], [1, 0], clamp))));
	const fade = interpolate(f, [0, 20], [0, 1], clamp) * interpolate(f, [TOTAL - 75, TOTAL - 2], [1, 0], clamp);
	return fade * (0.26 - 0.16 * duck);
};

export const Film: React.FC<{audio: boolean; captions: boolean; music?: boolean}> = ({audio, captions, music: withMusic = true}) => (
	<AbsoluteFill style={{background: C.bg}}>
		{SCENES.map((s) => {
			const Comp = BY_ID[s.id];
			if (!Comp) throw new Error(`no component for scene ${s.id}`);
			return (
				<Sequence key={s.id} from={s.from} durationInFrames={s.frames} name={s.id}>
					<SceneWrap frames={s.frames} fade={s.id === 'hook' ? 12 : 7}>
						<Comp />
					</SceneWrap>
				</Sequence>
			);
		})}
		{audio
			? SCENES.flatMap((s) =>
					s.lines.map((l) => (
						<Sequence key={l.id} from={s.from + Math.round(l.at * FPS)} durationInFrames={Math.ceil((l.dur + 0.3) * FPS)} name={`vo ${l.id}`}>
							<Audio src={staticFile(l.file)} />
						</Sequence>
					)),
				)
			: null}
		{audio && withMusic && music.file ? <Audio src={staticFile(music.file)} volume={musicVol} /> : null}
		{captions ? <Captions /> : null}
	</AbsoluteFill>
);
