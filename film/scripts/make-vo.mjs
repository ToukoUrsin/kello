#!/usr/bin/env node
// Voice-over for the film from film/script.json, one file per line, via ElevenLabs (a stock voice).
//   ELEVENLABS_API_KEY=... node film/scripts/make-vo.mjs      (only changed lines are synthesized)
//   node film/scripts/make-vo.mjs --print                                     (the script with word counts, no API call)
// Audio goes to $KELLO_FILM_OUT/public/audio/ (outside the repo); src/data/vo.json keeps each line's length
// and word timings, which set the scene lengths and the burned-in captions.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const film = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = process.env.KELLO_FILM_OUT || path.join(film, 'out');
const S = JSON.parse(fs.readFileSync(path.join(film, 'script.json'), 'utf8'));
// what the voice is sent: script.json "say_map" swaps words for phonetic spellings (Finnish names); captions keep "text"
const SAY = S.say_map || {};
const say = (t) => t.split(/(\s+)/).map((tok) => { const m = tok.match(/^(.*?)([.,:;!?]*)$/); return SAY[m[1]] ? SAY[m[1]] + m[2] : tok; }).join('');
const flat = S.scenes.flatMap((sc) => sc.lines.map((l) => ({...l, scene: sc.id})));
if (process.argv.includes('--print')) {
	let n = 0;
	for (const l of flat) {
		n += l.text.split(/\s+/).length;
		console.log(`${l.scene.padEnd(11)} ${l.id.padEnd(4)} ${l.text}`);
	}
	console.log(`${n} words, ${flat.reduce((a, l) => a + l.text.length, 0)} characters`);
	process.exit(0);
}
const KEY = process.env.ELEVENLABS_API_KEY;
if (!KEY) throw new Error('ELEVENLABS_API_KEY missing (set it in the environment)');
const dir = path.join(OUT, 'public/audio');
fs.mkdirSync(dir, {recursive: true});
const lines = [];
let spent = 0;
for (let i = 0; i < flat.length; i++) {
	const l = flat[i];
	// neighbours in the same scene keep the delivery continuous across separately made lines
	const prev = flat[i - 1]?.scene === l.scene ? say(flat[i - 1].text) : undefined;
	const next = flat[i + 1]?.scene === l.scene ? say(flat[i + 1].text) : undefined;
	const sig = crypto.createHash('sha1').update(JSON.stringify([l.text, S.voice, prev, next, say(l.text)])).digest('hex').slice(0, 10);
	const mp3 = path.join(dir, `vo-${l.id}.mp3`);
	const metaF = path.join(dir, `vo-${l.id}.json`);
	let m = fs.existsSync(metaF) ? JSON.parse(fs.readFileSync(metaF, 'utf8')) : null;
	if (!m || m.sig !== sig || !fs.existsSync(mp3)) {
		const r = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${S.voice.id}/with-timestamps?output_format=mp3_44100_192`, {
			method: 'POST',
			headers: {'xi-api-key': KEY, 'content-type': 'application/json'},
			body: JSON.stringify({text: say(l.text), model_id: S.voice.model, voice_settings: S.voice.settings, previous_text: prev, next_text: next}),
		});
		if (!r.ok) throw new Error(`TTS ${r.status}: ${(await r.text()).slice(0, 300)}`);
		const j = await r.json();
		fs.writeFileSync(mp3, Buffer.from(j.audio_base64, 'base64'));
		const al = j.alignment;
		const ws = [];
		let cur = null;
		al.characters.forEach((ch, k) => {
			if (/\s/.test(ch)) {
				if (cur) ws.push(cur);
				cur = null;
				return;
			}
			if (!cur) cur = {w: '', s: al.character_start_times_seconds[k], e: 0};
			cur.w += ch;
			cur.e = al.character_end_times_seconds[k];
		});
		if (cur) ws.push(cur);
		// captions show the written words, not the phonetic ones
		const cap = l.text.split(/\s+/).filter(Boolean);
		if (cap.length === ws.length) cap.forEach((w, k) => (ws[k].w = w));
		else console.warn(`vo ${l.id}: ${ws.length} spoken words vs ${cap.length} caption words`);
		m = {sig, text: l.text, dur: al.character_end_times_seconds.at(-1), words: ws.map((w) => ({w: w.w, s: +w.s.toFixed(3), e: +w.e.toFixed(3)}))};
		fs.writeFileSync(metaF, JSON.stringify(m));
		spent += l.text.length;
		console.log(`vo ${l.id} (${m.dur.toFixed(2)} s): ${l.text}`);
	}
	lines.push({id: l.id, scene: l.scene, text: l.text, file: `audio/vo-${l.id}.mp3`, dur: +m.dur.toFixed(3), words: m.words});
}
fs.writeFileSync(path.join(film, 'src/data/vo.json'), JSON.stringify({voice: S.voice.name, lines}, null, 1));
const total = lines.reduce((a, l) => a + l.dur, 0);
console.log(`vo.json: ${lines.length} lines, ${total.toFixed(1)} s of speech, ${spent} characters synthesized this run`);
