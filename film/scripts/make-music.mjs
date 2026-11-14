#!/usr/bin/env node
// Optional music bed via ElevenLabs Music (same paid plan as the voice; instrumental, made for this film, no stock).
//   ELEVENLABS_API_KEY=... node film/scripts/make-music.mjs [--force]
// Writes $KELLO_FILM_OUT/public/audio/music.mp3; the film uses it when src/data/music.json says so (render prop music).
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const film = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = process.env.KELLO_FILM_OUT || path.join(film, 'out');
const mf = path.join(OUT, 'public/audio/music.mp3');
const prompt =
	'Instrumental documentary score, calm and serious, about 76 BPM, felt piano and soft strings. ' +
	'0-13 s: a single sparse felt-piano motif over a low quiet string drone, grave and intimate, no percussion. ' +
	'At 13.5 s a gentle lift: a soft muted-piano pulse begins, curious and focused. ' +
	'At 28 s a warm opening chord, strings swell gently and resolve, hopeful, held through 44 s. ' +
	'44-96 s: quiet forward motion, a soft muted-piano ostinato with a light pulse, focused, never busy. ' +
	'96-108 s: warm and resolved, fuller strings. 108-112 s: one soft final piano chord that fades out. ' +
	'No vocals, no drum kit, no booms or trailer hits, understated, not sentimental, not corporate.';
if (fs.existsSync(mf) && !process.argv.includes('--force')) {
	console.log(`exists: ${mf}`);
} else {
	const KEY = process.env.ELEVENLABS_API_KEY;
	if (!KEY) throw new Error('ELEVENLABS_API_KEY missing');
	const r = await fetch('https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192', {
		method: 'POST',
		headers: {'xi-api-key': KEY, 'content-type': 'application/json'},
		body: JSON.stringify({prompt, music_length_ms: 112000, force_instrumental: true}),
	});
	if (!r.ok) throw new Error(`music ${r.status}: ${(await r.text()).slice(0, 300)}`);
	fs.mkdirSync(path.dirname(mf), {recursive: true});
	fs.writeFileSync(mf, Buffer.from(await r.arrayBuffer()));
	console.log(`written: ${mf}`);
}
fs.writeFileSync(path.join(film, 'src/data/music.json'), JSON.stringify({file: 'audio/music.mp3', prompt}, null, 1));
