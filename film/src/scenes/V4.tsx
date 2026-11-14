// The v4 cut: one county's cancer care lead, one page of the app, one plan. Every app shot is the real page
// (film/shots.json → capture.py), near full frame so its text reads at 28+ px; every number comes from
// film.json (make-data.py, which reads the live API and stops if a spoken number moved).
import React from 'react';
import film from '../data/film.json';
import {at, scene, word} from '../timeline';
import {C, MONO, SANS, ease, fi, pop, ramp, span} from '../theme';
import {Fill, Num, Wordmark, useT} from '../ui';
import {FRAME, Screen, cropW, grow, mark, sync, union} from '../screen';

const F = film.facts as any;
const ORANGE = '#D9730D';
const eur = (n: number) => '€' + Math.round(n).toLocaleString('en-GB');

/** The headline band over every app shot: a small source line on top, one plain sentence under it. */
const Band: React.FC<{t: number; kicker: React.ReactNode; title: React.ReactNode; right?: React.ReactNode; at?: number}> = ({t, kicker, title, right, at: a0 = 0}) => {
	const a = ramp(t, a0, a0 + 0.5);
	return (
		<>
			<div style={{position: 'absolute', left: 64, top: 30, right: 64, opacity: a, translate: `0px ${(1 - a) * 8}px`}}>
				<div style={{fontFamily: SANS, fontSize: 22, fontWeight: 600, letterSpacing: 0.4, color: C.dim, marginBottom: 8, whiteSpace: 'nowrap'}}>{kicker}</div>
				<div style={{fontFamily: SANS, fontSize: 50, fontWeight: 750, color: C.ink, letterSpacing: -1.1, lineHeight: 1.06, whiteSpace: 'nowrap'}}>{title}</div>
			</div>
			{right ? <div style={{position: 'absolute', right: 64, top: 34, opacity: a}}>{right}</div> : null}
		</>
	);
};

/** Two headlines that swap at `when` (a quick cross-fade, the second slides up). */
const Swap: React.FC<{t: number; when: number; a: React.ReactNode; b: React.ReactNode}> = ({t, when, a, b}) => {
	const pa = ramp(t, when - 0.22, when, ease.in);
	const pb = ramp(t, when, when + 0.35);
	return (
		<span style={{position: 'relative', display: 'inline-block'}}>
			<span style={{opacity: 1 - pa, display: 'inline-block', translate: `0px ${-pa * 10}px`}}>{a}</span>
			<span style={{position: 'absolute', left: 0, top: 0, opacity: pb, translate: `0px ${(1 - pb) * 12}px`, whiteSpace: 'nowrap'}}>{b}</span>
		</span>
	);
};

const Pill: React.FC<{children: React.ReactNode; tone?: string; bg?: string}> = ({children, tone = C.ink2, bg = C.wash}) => (
	<div style={{fontFamily: SANS, fontSize: 22, fontWeight: 650, color: tone, background: bg, borderRadius: 999, padding: '9px 18px', whiteSpace: 'nowrap', letterSpacing: 0.2}}>{children}</div>
);

// ---------------------------------------------------------------- hook: the app's own dot chart, Lapland vs the best county
export const Hook: React.FC = () => {
	const t = useT();
	const lap = mark('dots', 'lap');
	const best = mark('dots', 'best');
	const chart = mark('dots', 'chart');
	const title = mark('dots', 'title');
	const tV = word('h3', 'Vantaa') - 0.35;
	const tSame = at('h4') - 0.2;
	const sw = mark('dots', 'switch').t;
	// the page is still before the switch: hold the Today frame (the cursor is hidden here)
	const segs = [{t: 0, c: Math.min(sw - 1.6, 2.4), rate: 0}];
	return (
		<Fill>
			<Band
				t={t}
				kicker={`Finnish Cancer Registry, patients diagnosed 2019–2023 · p. ${F.lapland.page} · as shown in Kello`}
				title={<Swap t={t} when={tV} a={<>Lapland: <b style={{color: C.blue}}>{F.lapland.of100}</b> of 100 lung cancer patients treated to cure</>} b={<>Lapland {F.lapland.of100} · Vantaa and Kerava <b style={{color: C.blue}}>{F.vantaa.of100}</b> · of 100 treated to cure</>} />}
			/>
			<Screen
				id="dots"
				t={t}
				segs={segs}
				{...FRAME.full}
				cursor={false}
				keys={[
					{t: 0, box: grow(lap.box, 10, 4), pad: 40, max: 2.3},
					{t: tV, box: grow(best.box, 10, 4), pad: 40, max: 2.3, d: 1.1},
					{t: tSame, box: union(title.box, chart.box), pad: 30, d: 1.2},
				]}
			/>
		</Fill>
	);
};

// ---------------------------------------------------------------- reveal: top of Lapland's page
export const Reveal: React.FC = () => {
	const t = useT();
	const head = mark('top', 'head');
	const wait = mark('top', 'wait');
	const tWait = word('r1', 'Lapland') - 0.3;
	const tFewer = at('r2') - 0.2;
	const tTwelve = word('r2', 'twelve') - 0.4;
	const dur = scene('reveal').dur;
	const segs = [{t: 0, c: 2.6, rate: 0}];
	const D = F.days;
	return (
		<Fill>
			<Band
				t={t}
				kicker={<Swap t={t} when={tWait} a={<>Kello · Lapland's page</>} b={<>Diagnosis to treatment: Northern Finland (OYS) area, 2018–mid 2022 · Cancer Registry p. {D.page}</>} />}
				title={<Swap t={t} when={tFewer} a={<>Not slower: {Math.round(D.area)} days to treatment, {Math.round(D.fi)} in Finland</>} b={<>Fewer are treated to cure: about {F.lapland.per_year_round} patients a year</>} />}
				right={<div style={{opacity: ramp(t, 0.2, 0.8)}}><Wordmark size={46} p={ramp(t, 0.2, 1.4)} /></div>}
			/>
			<Screen
				id="top"
				t={t}
				segs={segs}
				{...FRAME.full}
				cursor={false}
				keys={[
					{t: 0, box: union(grow(head.box, 0, 22), wait.box), pad: 34},
					{t: tWait, box: cropW(wait.box, 760), pad: 30, max: 2.6},
					{t: tTwelve, box: grow(head.box, 4, 22), pad: 34, max: 2.6},
					{t: dur - 0.6, box: grow(head.box, 4, 22), pad: 34, max: 2.6},
				]}
				hl={[
					{t0: tWait + 0.3, t1: tTwelve - 0.1, box: wait.box},
					{t0: tTwelve + 0.4, t1: dur + 1, box: grow(head.box, 4, 22)},
				]}
			/>
		</Fill>
	);
};

// ---------------------------------------------------------------- switch: the dots move into "treated to cure"
export const Switch: React.FC = () => {
	const t = useT();
	const sw = mark('dots', 'switch');
	const lapA = mark('dots', 'lap_after');
	const toggle = mark('dots', 'toggle');
	const chart = mark('dots', 'chart');
	const miss = mark('dots', 'miss');
	const tClick = word('s1', 'plan') + 0.05;
	const tMiss = at('s2') + 1.2;
	const scrollStart = miss.t - 1.15;
	// under: the pointer travels to "With the plan" and the Today frame holds; over: the settled plan frame,
	// faded in like the app fades its dots, then the scroll down to the missing-patients bar
	const under = [
		{t: 0, c: Math.max(0, sw.t - tClick), rate: 1},
		{t: tClick, c: sw.t - 0.02, rate: 0},
	];
	const over = sync([
		[0, sw.t + 1.8],
		[tMiss, sw.t + 1.8],
		[tMiss + 1.15, miss.t],
	]).map((x, i) => (i === 0 ? {...x, rate: 0} : x));
	const fade = ramp(t, tClick + 0.35, tClick + 1.0, ease.inOut);
	const dur = scene('switch').dur;
	const keys = [
		{t: 0, box: union(toggle.box, lapA.box), pad: 30, max: 2.2},
		{t: tClick + 0.25, box: grow(lapA.box, 10, 4), pad: 36, max: 2.3, d: 1.0},
		{t: tMiss - 0.3, box: chart.box, pad: 30, d: 0.6},
		{t: tMiss + 1.0, box: miss.box, pad: 30, max: 2.2, d: 0.6},
	];
	return (
		<Fill>
			<Band
				t={t}
				kicker="Kello's plan for Lapland, switched on · modelled"
				title={
					<Swap
						t={t}
						when={tMiss}
						a={<Swap t={t} when={tClick + 1.1} a={<>Switch on the plan</>} b={<><span style={{color: ORANGE}}>Orange: +{fi(F.plan.moved_of100, 1)} of 100</span> move into "treated to cure"</>} />}
						b={<>{F.plan.n_actions} actions, <span style={{color: ORANGE}}>{eur(F.plan.eur)}</span> a year: {fi(F.plan.extra, 1)} of {fi(F.plan.shortfall, 1)} patients</>}
					/>
				}
			/>
			{fade < 1 ? <Screen id="dots" t={t} segs={under} {...FRAME.full} keys={keys} /> : null}
			{fade > 0 ? <Screen id="dots" t={t} segs={over} {...FRAME.full} keys={keys} opacity={fade} cursor={false} hl={[{t0: tMiss + 1.4, t1: dur + 1, box: miss.box}]} /> : null}
		</Fill>
	);
};

// ---------------------------------------------------------------- card: the number that stays
export const Card: React.FC = () => {
	const t = useT();
	const P = F.plan;
	const tFive = word('c1', 'five') - 0.1;
	const tPct = word('c1', 'Forty-three') - 0.1;
	const short = P.short_round; // 12
	const closes = P.closes_round; // 5
	const r = 34;
	const gap = 104;
	return (
		<Fill>
			<div style={{position: 'absolute', left: 160, top: 120, fontFamily: SANS, fontSize: 24, fontWeight: 600, letterSpacing: 0.4, color: C.dim, opacity: ramp(t, 0.1, 0.6)}}>
				Lapland, against the Finnish average · Kello plan at a €1M ceiling, 14 Nov 2026
			</div>
			<div style={{position: 'absolute', left: 160, top: 176}}>
				<svg width={gap * (short - 1) + 2 * r + 8} height={2 * r + 8} style={{overflow: 'visible'}}>
					{Array.from({length: short}, (_, i) => {
						const a = pop(t, 0.15 + i * 0.05);
						const on = ramp(t, tFive + i * 0.12, tFive + i * 0.12 + 0.35) * (i < closes ? 1 : 0);
						const cx = i * gap + r + 4;
						return (
							<g key={i} transform={`translate(${cx} ${r + 4}) scale(${a})`}>
								<circle r={r} fill={C.line} />
								<circle r={r * (0.5 + 0.5 * on)} fill={ORANGE} opacity={on} />
							</g>
						);
					})}
				</svg>
			</div>
			<div style={{position: 'absolute', left: 160, top: 300, width: 1600}}>
				<div style={{fontFamily: SANS, fontSize: 92, fontWeight: 800, color: C.ink, letterSpacing: -3, lineHeight: 1.04, opacity: ramp(t, 0.2, 0.7)}}>
					{short} patients a year short.
				</div>
				<div style={{fontFamily: SANS, fontSize: 92, fontWeight: 800, color: ORANGE, letterSpacing: -3, lineHeight: 1.04, opacity: ramp(t, tFive, tFive + 0.5)}}>
					This plan closes {closes} of them ({P.pct}%)
				</div>
				<div style={{fontFamily: SANS, fontSize: 92, fontWeight: 800, color: C.ink, letterSpacing: -3, lineHeight: 1.04, opacity: ramp(t, tPct, tPct + 0.5)}}>
					for {eur(P.eur)} a year.
				</div>
				<div style={{fontFamily: SANS, fontSize: 28, color: C.dim, marginTop: 34, lineHeight: 1.35, opacity: ramp(t, tPct + 0.4, tPct + 0.9)}}>
					Modelled: {fi(P.extra, 1)} of {fi(P.shortfall, 1)} patients a year, range {fi(P.extra_lo, 0)} to {fi(P.extra_hi, 1)} · shortfall from the Cancer Registry 2019–2023, p. {F.lapland.page}
				</div>
			</div>
		</Fill>
	);
};

// ---------------------------------------------------------------- orders: one action as an order
export const Orders: React.FC = () => {
	const t = useT();
	const title = mark('card', 'title');
	const cost = mark('card', 'cost');
	const first = mark('card', 'first');
	const owner = mark('card', 'owner');
	const tTitle = at('o2') - 0.1;
	const tThirty = word('o2', 'thirty') - 0.3;
	const tStep = word('o2', 'First') - 0.3;
	const tOwner = word('o2', 'Owner') - 0.3;
	const dur = scene('orders').dur;
	// Hold the first step while it is spoken; the capture's scroll down to the owner line plays at real speed just
	// before "Owner", while the camera follows. Older captures have no owner_scrolled mark: their scroll ran 14.85-15.7 s.
	const os = mark('card', 'owner_scrolled');
	const sc1 = os.t > 0 ? os.t : 15.7;
	const sc0 = os.t > 0 ? os.t - 0.95 : 14.85;
	const tScroll = tOwner - 0.15 - (sc1 - sc0);
	const segs = [
		...sync([
			[0, Math.max(0, title.t - tTitle)],
			[tTitle, title.t],
			[tThirty, cost.t],
			[tStep, first.t],
		]).slice(0, 3),
		{t: tStep, c: first.t, rate: 0},
		{t: tScroll, c: sc0, rate: 1},
		{t: tOwner - 0.15, c: sc1, rate: (owner.t - sc1) / 0.8},
		{t: tOwner + 0.65, c: owner.t, rate: 0},
	];
	return (
		<Fill>
			<Band
				t={t}
				kicker={`Action 1 of ${F.plan.n_actions} in Lapland's plan · ${F.sbrt.group_en}`}
				title={<Swap t={t} when={tTitle + 0.3} a={<>Each action is an order</>} b={<>Owner, cost and a first step</>} />}
			/>
			<Screen
				id="card"
				t={t}
				segs={segs}
				{...FRAME.full}
				keys={[
					{t: 0, box: union(title.box, cost.box), pad: 30, max: 2.3},
					{t: tTitle, box: grow(title.box, 0, 30), pad: 30, max: 2.3},
					{t: tThirty, box: cost.box, pad: 40, max: 2.3},
					{t: tStep, box: first.box, pad: 30, max: 2.3},
					{t: tScroll, box: owner.box, pad: 40, max: 2.3, d: sc1 - sc0},
				]}
				hl={[
					{t0: tTitle + 0.3, t1: tThirty, box: grow(title.box, 0, 4)},
					{t0: tThirty + 0.4, t1: tStep, box: cost.box},
					{t0: tStep + 0.4, t1: tScroll, box: first.box},
					{t0: tOwner + 0.6, t1: dur + 1, box: owner.box},
				]}
			/>
		</Fill>
	);
};

// ---------------------------------------------------------------- verify: the live web check, and what it changes
export const Verify: React.FC = () => {
	const t = useT();
	const click = mark('card', 'click');
	const live = mark('card', 'live_box');
	const trace = mark('card', 'trace');
	const done = mark('card', 'done');
	const ask = mark('card', 'ask');
	const quote = mark('card', 'quote');
	const tClick = word('v1', 'checks');
	const tDone = at('v3') - 0.6;
	const askScrollEnd = ask.t;
	const speed = (done.t - click.t) / (tDone - tClick);
	const segs = sync([
		[0, click.t - tClick],
		[tClick, click.t],
		[tDone, done.t],
		[tDone + 1.2, askScrollEnd],
	]);
	const tChange = word('v3', 'changes') - 0.3;
	const dur = scene('verify').dur;
	const secs = Math.round(done.t - click.t);
	const clock = Math.min(secs, Math.max(0, (t - tClick) * speed));
	const running = t >= tClick && t < tDone;
	return (
		<Fill>
			<Band
				t={t}
				kicker={<Swap t={t} when={tDone} a={<>Live web check through the Oxylabs Web API · searches and page reads shown as they happen</>} b={<>Result of the web check, {F.check.day} · quote from the hospital's own page</>} />}
				title={<Swap t={t} when={tDone} a={<>Is it already running in Lapland?</>} b={<>Oulu University Hospital already offers it: <span style={{color: '#9A5B00'}}>ask first</span></>} />}
				right={
					<div style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10, opacity: span(t, tClick, tDone + 0.4)}}>
						<Pill tone="#fff" bg={C.ink}>REAL RUN · {F.check.day.toUpperCase()}</Pill>
						<Pill>
							<span style={{fontFamily: MONO}}>{String(Math.floor(clock)).padStart(2, '0')} s</span> · sped up {fi(speed, 1)}×
						</Pill>
					</div>
				}
			/>
			<Screen
				id="card"
				t={t}
				segs={segs}
				{...FRAME.full}
				cursor={!running || t < tClick + 0.8}
				keys={[
					{t: 0, box: union(mark('card', 'owner').box, click.box), pad: 40, max: 2.2},
					{t: tClick + 0.2, box: cropW(live.box, 700), pad: 30, max: 2.4, d: 1.0},
					{t: tClick + 3.5, box: cropW(trace.box, 700), pad: 30, max: 2.4, d: 1.2},
					{t: tDone + 0.2, box: cropW(ask.box, 840), pad: 30, max: 2.4, d: 1.0},
					{t: tChange, box: cropW(ask.box, 840), pad: 30, max: 2.4},
				]}
				hl={[{t0: tDone + 1.2, t1: tChange, box: quote.box}, {t0: tChange + 0.2, t1: dur + 1, box: ask.box}]}
			/>
		</Fill>
	);
};

// ---------------------------------------------------------------- plan: the change, in the one-page plan
export const Plan: React.FC = () => {
	const t = useT();
	const row = mark('plan', 'row');
	const note = mark('plan', 'note');
	const fiM = mark('plan', 'fi');
	const tfi = mark('plan', 'title_fi');
	const tFin = word('p1', 'Finnish') - 0.6;
	const dur = scene('plan').dur;
	const segs = sync([
		[0, row.t + 0.2],
		[tFin - 0.6, row.t + 1.4],
		[tFin, fiM.t - 0.5],
		[tFin + 1.6, tfi.t],
	]);
	return (
		<Fill>
			<Band
				t={t}
				kicker="Kello · the one-page plan for Lapland, written by Claude from the plan's own numbers"
				title={<Swap t={t} when={tFin + 0.8} a={<>The web check is now in the plan</>} b={<>One page, in English or Finnish</>} />}
			/>
			<Screen
				id="plan"
				t={t}
				segs={segs}
				{...FRAME.full}
				cursor={t > tFin - 0.6 && t < tFin + 1.2}
				keys={[
					{t: 0, box: row.box, pad: 26, max: 2.3},
					{t: tFin - 0.6, box: null, d: 0.5},
					{t: tFin + 1.2, box: grow(tfi.box, 10, 20), pad: 30, max: 2.3, d: 0.8},
				]}
				hl={[{t0: 0.3, t1: tFin - 0.6, box: note.box}]}
			/>
		</Fill>
	);
};

// ---------------------------------------------------------------- sources: every number opens its source
export const Sources: React.FC = () => {
	const t = useT();
	const chip = mark('source', 'chip');
	const focus = mark('source', 'focus');
	const quote = mark('source', 'quote');
	const read = mark('source', 'read');
	const tClick = word('g1', 'opens');
	const tGem = word('g1', 'Gemini') - 0.3;
	const tPage = word('g1', 'page') - 0.3;
	const dur = scene('sources').dur;
	const segs = sync([
		[0, chip.t - tClick],
		[tClick, chip.t],
		[tGem, read.t - 0.9],
		[tGem + 0.9, read.t],
	]);
	return (
		<Fill>
			<Band
				t={t}
				kicker={`${F.read.count} values read from registry reports by ${F.read.model} · ${F.read.ok} re-confirmed in the source, ${F.read.flagged} flagged`}
				title={<>Every number opens its source</>}
			/>
			<Screen
				id="source"
				t={t}
				segs={segs}
				{...FRAME.full}
				keys={[
					{t: 0, box: grow(chip.box, 0, 30), pad: 30, max: 2.2},
					{t: tClick + 0.5, box: focus.box, pad: 24, max: 2.3, d: 0.9},
					{t: tGem, box: read.box, pad: 40, max: 2.3},
					{t: tPage, box: union(quote.box, read.box), pad: 30, max: 2.3},
				]}
				hl={[
					{t0: tClick + 1.2, t1: tGem, box: quote.box},
					{t0: tGem + 0.5, t1: dur + 1, box: read.box},
				]}
			/>
		</Fill>
	);
};

// ---------------------------------------------------------------- ask: the pilot
export const Ask: React.FC = () => {
	const t = useT();
	const tGoal = at('a2') - 0.2;
	const dur = scene('ask').dur;
	const P = F.plan;
	const g = ramp(t, word('a2', 'twenty-two') - 0.3, word('a2', 'twenty-two') + 0.6);
	return (
		<Fill>
			<div style={{position: 'absolute', left: 160, top: 120, opacity: ramp(t, 0.1, 0.7)}}>
				<Wordmark size={64} p={ramp(t, 0.1, 1.2)} />
			</div>
			<div style={{position: 'absolute', left: 160, top: 260, width: 1600}}>
				<div style={{fontFamily: SANS, fontSize: 26, fontWeight: 650, letterSpacing: 2, color: C.dim, textTransform: 'uppercase', opacity: ramp(t, 0.3, 0.8)}}>The ask</div>
				<div style={{fontFamily: SANS, fontSize: 76, fontWeight: 800, color: C.ink, letterSpacing: -2.4, lineHeight: 1.06, marginTop: 14, opacity: ramp(t, 0.5, 1.0)}}>
					A six-month pilot with Lapland
					<br />
					and the Oulu university hospital area
				</div>
				<div style={{display: 'flex', alignItems: 'baseline', gap: 26, marginTop: 56, opacity: ramp(t, tGoal, tGoal + 0.5)}}>
					<Num size={120} color={C.ink}>{fi(P.share_now, 1)}%</Num>
					<span style={{fontFamily: SANS, fontSize: 80, color: C.faint, fontWeight: 300}}>→</span>
					<Num size={120} color={ORANGE} style={{opacity: g}}>{fi(P.share_after, 1)}%</Num>
					<span style={{fontFamily: SANS, fontSize: 40, fontWeight: 650, color: C.ink, marginLeft: 10}}>treated to cure by {P.target_year}</span>
				</div>
				<div style={{fontFamily: SANS, fontSize: 40, fontWeight: 500, color: C.dim, marginTop: 48, opacity: ramp(t, word('a2', 'twenty-two') + 0.8, word('a2', 'twenty-two') + 1.4)}}>
					{P.short_round} patients a year short · this plan closes {P.closes_round} of them ({P.pct}%) for €{P.eur.toLocaleString('en-US')} a year
				</div>
			</div>
			<div style={{position: 'absolute', left: 160, top: 930, fontFamily: SANS, fontSize: 26, color: C.dim, opacity: ramp(t, dur - 3.4, dur - 2.6)}}>
				Kello · Junction 2026 · AstraZeneca challenge "Equal Care Across Finland" · target from Kello's plan for Lapland, modelled
			</div>
		</Fill>
	);
};

