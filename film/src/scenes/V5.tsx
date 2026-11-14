// The v5 cut (v4 + the first screen, the gap checks, the before/after web check and the pilot ask): one county's cancer care lead, one page of the app, one plan. Every app shot is the real page
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

/** A ring with a big number tag that sticks to a box of the capture (follows the camera). */
const Tag: React.FC<{b: [number, number, number, number]; a: number; label: React.ReactNode; color: string}> = ({b, a, label, color}) => {
	const [x, y, w, h] = b;
	const s = 0.9 + 0.1 * a;
	return (
		<div style={{opacity: a}}>
			<div style={{position: 'absolute', left: x - 10, top: y - 10, width: w + 20, height: h + 20, border: `5px solid ${color}`, borderRadius: 16}} />
			<div style={{position: 'absolute', left: x + w / 2, top: y - 16, transform: `translate(-50%, -100%) scale(${s})`, transformOrigin: '50% 100%', background: color, color: '#fff', fontFamily: SANS, fontWeight: 800, fontSize: 44, padding: '6px 20px', borderRadius: 12, whiteSpace: 'nowrap', letterSpacing: -0.8}}>{label}</div>
		</div>
	);
};

// ---------------------------------------------------------------- hook: the app's first screen, Lapland vs the best county
export const Hook: React.FC = () => {
	const t = useT();
	const lap = mark('home', 'lap');
	const best = mark('home', 'best');
	const chart = mark('home', 'chart');
	const head = mark('home', 'head');
	const tL = word('h2', 'eighteen') - 0.45;
	const tV = word('h3', 'Vantaa') - 0.35;
	const tSame = at('h4') - 0.15;
	// the first screen is a still page: hold one frame (the cursor is hidden)
	const segs = [{t: 0, c: 1.0, rate: 0}];
	const both = ramp(t, tSame + 0.5, tSame + 1.0);
	return (
		<Fill>
			<Band
				t={t}
				kicker={`Kello · first screen · Finnish Cancer Registry, patients diagnosed 2019–2023, p. ${F.lapland.page}`}
				title={<Swap t={t} when={tSame + 0.3} a={<>Lung cancer: how many are treated to cure?</>} b={<>Lapland <b style={{color: C.ink}}>{F.lapland.of100}</b> · Vantaa and Kerava <b style={{color: C.blue}}>{F.vantaa.of100}</b> · of 100 treated to cure</>} />}
			/>
			<Screen
				id="home"
				t={t}
				segs={segs}
				{...FRAME.full}
				cursor={false}
				keys={[
					{t: 0, box: union(head.box, chart.box), pad: 24},
					{t: tL, box: grow(lap.box, 8, 4), pad: 70, max: 2.2, d: 1.0},
					{t: tV, box: grow(best.box, 8, 4), pad: 70, max: 2.2, d: 0.8},
					{t: tSame, box: grow(chart.box, 0, 20), pad: 40, d: 0.9},
				]}
				overlay={(S) => (
					<>
						<Tag b={S(lap.box!)} a={Math.max(span(t, tL + 0.7, tV + 0.2), both)} label={`${F.lapland.of100} of 100`} color={C.ink} />
						<Tag b={S(best.box!)} a={Math.max(span(t, tV + 0.6, tSame + 0.4), both)} label={`${F.vantaa.of100} of 100`} color={C.blue} />
					</>
				)}
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
				kicker={<Swap t={t} when={tWait} a={<>Kello · Lapland's page</>} b={<>Diagnosis to treatment: Oulu university hospital area, 2018–mid 2022 · Cancer Registry p. {D.page}</>} />}
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

// ---------------------------------------------------------------- real: is the gap real? five checks on Lapland's page
export const Real: React.FC = () => {
	const t = useT();
	const head = mark('gap', 'head');
	const strip = mark('gap', 'strip');
	const c = [0, 1, 2, 3, 4].map((i) => mark('gap', `c${i}`).box);
	const tChance = word('q1', 'chance') - 0.3;
	const tAge = word('q1', 'age') - 0.3;
	const tRec = word('q1', 'records') - 0.9;
	const tStage = at('q2') - 0.2;
	const tAudit = word('q2', 'audit') - 0.6;
	const dur = scene('real').dur;
	const G = F.gap.checks as {id: string; verdict: string}[];
	const ok = G.filter((g) => g.verdict !== 'cannot_tell').length;
	return (
		<Fill>
			<Band
				t={t}
				kicker={<>Kello · Lapland's page · "Is this gap real?" · Cancer Registry, Kello's own checks</>}
				title={
					<Swap
						t={t}
						when={tStage + 0.2}
						a={<><span style={{color: C.blue}}>{ok} of {G.length}</span> checks say the gap is real</>}
						b={<>Stage: an <span style={{color: ORANGE}}>8-week, €8,000</span> records audit settles it</>}
					/>
				}
			/>
			<Screen
				id="gap"
				t={t}
				segs={[{t: 0, c: 1.0, rate: 0}]}
				{...FRAME.full}
				cursor={false}
				keys={[
					{t: 0, box: union(head.box, strip.box), pad: 30},
					{t: tChance, box: union(c[0], c[1]), pad: 40, max: 2.4, d: 0.8},
					{t: tRec, box: union(c[3], c[4]), pad: 40, max: 2.4, d: 0.8},
					{t: tStage, box: grow(c[2], 40, 10), pad: 40, max: 2.4, d: 0.8},
					{t: tAudit, box: union(head.box, strip.box), pad: 30, d: 0.9},
				]}
				hl={[
					{t0: tChance + 0.2, t1: tAge, box: c[0]},
					{t0: tAge, t1: tRec + 0.2, box: c[1]},
					{t0: tRec + 0.4, t1: tStage, box: union(c[3], c[4])},
					{t0: tStage + 0.4, t1: tAudit, box: c[2]},
					{t0: tAudit + 0.6, t1: dur + 1, box: head.box},
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
				title={<>Each action is an order: cost, first step, owner</>}
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

// ---------------------------------------------------------------- verify: the live web check, before and after
export const Verify: React.FC = () => {
	const t = useT();
	const askpre = mark('card', 'askpre');
	const owner = mark('card', 'owner');
	const click = mark('card', 'click');
	const live = mark('card', 'live_box');
	const trace = mark('card', 'trace');
	const done = mark('card', 'done');
	const vd = mark('card', 'vdiff');
	const was = mark('card', 'was');
	const now = mark('card', 'now');
	const ask = mark('card', 'ask');
	const quote = mark('card', 'quote');
	const tClick = word('v1', 'checks');
	const tDone = at('v3') - 0.5;
	const tMorning = at('v3');
	const tLive = word('v3', 'live') - 0.2;
	const tOulu = word('v3', 'Oulu') - 0.4;
	const tAsk = word('v3', 'Ask') - 0.2;
	const speed = (done.t - click.t) / (tDone - tClick);
	// before the click the capture holds on the card with its stored answer (askpre), then plays to the click
	const segs = [
		...sync([
			[0, Math.max(0, click.t - tClick)],
			[tClick, click.t],
			[tDone, done.t],
			[tDone + 0.9, vd.t],
		]),
		{t: tDone + 0.9, c: vd.t, rate: 0},
		{t: tOulu - 0.9, c: vd.t, rate: (ask.t - vd.t) / 0.9},
		{t: tOulu, c: ask.t, rate: 0},
	];
	const dur = scene('verify').dur;
	const secs = Math.round(done.t - click.t);
	const clock = Math.min(secs, Math.max(0, (t - tClick) * speed));
	const running = t >= tClick && t < tDone;
	const pre = askpre.box ?? owner.box;
	return (
		<Fill>
			<Band
				t={t}
				kicker={
					<Swap
						t={t}
						when={tDone}
						a={<>Live web check through the Oxylabs Web API · searches and page reads shown as they happen</>}
						b={<Swap t={t} when={tOulu} a={<>Before: the stored answer from this morning · After: this live run</>} b={<>Quote from the hospital's own page · Oulu University Hospital (OYS)</>} />}
					/>
				}
				title={
					<Swap
						t={t}
						when={tDone}
						a={<>Is it already running in Lapland?</>}
						b={<Swap t={t} when={tOulu} a={<>Before and after: the same answer</>} b={<>Oulu University Hospital already offers it: <span style={{color: '#9A5B00'}}>ask first</span></>} />}
					/>
				}
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
					{t: 0, box: union(pre, click.box), pad: 40, max: 2.2},
					{t: tClick + 0.2, box: cropW(live.box, 700), pad: 30, max: 2.4, d: 1.0},
					{t: tClick + 3.5, box: cropW(trace.box, 700), pad: 30, max: 2.4, d: 1.2},
					{t: tDone + 0.1, box: vd.box ?? union(was.box, now.box), pad: 50, max: 2.4, d: 0.8},
					{t: tOulu - 0.9, box: cropW(ask.box, 840), pad: 30, max: 2.4, d: 0.9},
				]}
				hl={[
					{t0: 0.3, t1: tClick - 0.2, box: pre},
					{t0: tAsk, t1: dur + 1, box: quote.box ?? ask.box},
				]}
				overlay={(S) =>
					was.box && now.box ? (
						<>
							<Tag b={S(was.box)} a={span(t, tMorning - 0.1, tOulu - 0.6)} label="BEFORE · this morning" color={C.ink} />
							<Tag b={S(now.box)} a={span(t, tLive, tOulu - 0.6)} label="AFTER · live, just now" color={C.blue} />
						</>
					) : null
				}
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
	const Pi = F.pilot;
	const tA1 = word('a2', 'chest') - 0.3;
	const tA2 = word('a2', 'those') - 0.3;
	const tGoal = word('a3', 'eighteen') - 0.3;
	const tTo = word('a3', 'twenty') - 0.3;
	const dur = scene('ask').dur;
	const g = ramp(t, tTo, tTo + 0.6);
	const row = (n: number, a: number, text: React.ReactNode) => (
		<div style={{display: 'flex', alignItems: 'baseline', gap: 22, opacity: a, translate: `${(1 - a) * 24}px 0px`}}>
			<span style={{fontFamily: SANS, fontSize: 34, fontWeight: 800, color: '#fff', background: ORANGE, borderRadius: 999, width: 52, height: 52, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: 'none', translate: '0px 6px'}}>{n}</span>
			<span style={{fontFamily: SANS, fontSize: 44, fontWeight: 650, color: C.ink, letterSpacing: -0.8}}>{text}</span>
		</div>
	);
	return (
		<Fill>
			<div style={{position: 'absolute', left: 160, top: 84, opacity: ramp(t, 0.1, 0.7)}}>
				<Wordmark size={56} p={ramp(t, 0.1, 1.2)} />
			</div>
			<div style={{position: 'absolute', left: 160, top: 196, width: 1640}}>
				<div style={{fontFamily: SANS, fontSize: 26, fontWeight: 650, letterSpacing: 2, color: C.dim, textTransform: 'uppercase', opacity: ramp(t, 0.3, 0.8)}}>The ask</div>
				<div style={{fontFamily: SANS, fontSize: 68, fontWeight: 800, color: C.ink, letterSpacing: -2.2, lineHeight: 1.06, marginTop: 12, opacity: ramp(t, 0.5, 1.0)}}>
					A {Pi.months}-month pilot: Lapland and the Oulu university hospital area
				</div>
				<div style={{display: 'flex', flexDirection: 'column', gap: 18, marginTop: 40}}>
					{row(1, ramp(t, tA1, tA1 + 0.5), <>A chest surgeon reviews every decision not to operate</>)}
					{row(2, ramp(t, tA2, tA2 + 0.5), <>Patients who cannot be operated are referred for precise radiotherapy</>)}
				</div>
				<div style={{display: 'flex', alignItems: 'baseline', gap: 26, marginTop: 46, opacity: ramp(t, tGoal, tGoal + 0.5)}}>
					<Num size={124} color={C.ink}>{fi(Pi.now, 1)}%</Num>
					<span style={{fontFamily: SANS, fontSize: 80, color: C.faint, fontWeight: 300}}>→</span>
					<Num size={124} color={ORANGE} style={{opacity: g}}>{fi(Pi.after, 1)}%</Num>
					<span style={{fontFamily: SANS, fontSize: 42, fontWeight: 650, color: C.ink, marginLeft: 10}}>treated to cure by {Pi.by_year}</span>
				</div>
				<div style={{fontFamily: SANS, fontSize: 38, fontWeight: 550, color: C.dim, marginTop: 26, opacity: ramp(t, tTo + 1.0, tTo + 1.6)}}>
					In six months: about <b style={{color: C.ink}}>{Pi.patients} patients</b> seen, <b style={{color: C.ink}}>{Pi.reviews} decisions</b> not to operate reviewed
				</div>
			</div>
			<div style={{position: 'absolute', left: 160, top: 930, fontFamily: SANS, fontSize: 26, color: C.dim, opacity: ramp(t, dur - 3.0, dur - 2.3)}}>
				Kello · Junction 2026 · AstraZeneca challenge "Equal Care Across Finland" · pilot target modelled by Kello, compared with Vantaa and Kerava
			</div>
		</Fill>
	);
};
