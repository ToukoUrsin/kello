import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, AreaMeta, eur, eurx, int, one, openSource, SrcRef, TraceStep, useAsync, VerifyResult, when } from "../lib";
import { stepLabel, useLiveRun } from "../WebCheck";
import { largestRemainder, relaxBoxes, shortName, SiteKind, stageApi, whole } from "./data";
import { Activity, buildCounties, buildCountyPins, buildDots, buildPins, buildPlaces, Cam, checkOf, CheckM, figureIn, fitCam, hospitalFor, Layout, makeLayout, PinM, project, srcOfFunnel } from "./model";
import { ACTS, countAt, LAST, progress, reached, T, useReducedMotion, useRun } from "./timeline";
import StageMap, { Pinned, Seg, useCamera } from "./StageMap";
import { CarePathCard, effectText, Fly, Ledger, LedgerRow, PageCard, StudyCard } from "./Cards";
import { SimChart } from "./Charts";
import { ProofLine } from "../OutsideProof";
import Explore, { SITE, Tool } from "./Explore";
import "./stage.css";

type Open = (view: "county" | "plan" | "monday" | "review" | "map", section?: string) => void;
const SEQ = ["var(--seq-5)", "var(--seq-4)", "var(--seq-3)", "var(--seq-2)", "var(--seq-1)"];   // dark = fewer treated to cure
const NATIONAL: Cam = { k: 1, tx: 0, ty: 0 };
const WHERE: Record<string, string> = { detection: "finding it early", referral: "the referral", diagnosis: "the wait for treatment", treatment: "the treatment decision" };
const FOUND: Record<string, string> = { yes: "already in place", partly: "partly in place", planned: "planned", no_evidence: "not found" };
const FEATURED = "sbrt_pathway";
/** "The server has no such answer" is an answer. A dropped connection is not: that one is asked again. */
const definite = (e: unknown): null => { if (e instanceof ApiError && e.status >= 400 && e.status < 500) return null; throw e; };
const short = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
/** One step of a live check, as a line of the log: what it searched for, which page it is reading. */
const liveLine = (t: TraceStep): string => {
  const tool = t.tool ?? "", input = typeof t.input === "string" ? t.input : "";
  if (/search/i.test(tool)) return `Searching: ${input}`;
  if (/scrape|read|fetch|open/i.test(tool)) return `Reading ${short(t.url ?? input)}`;
  return stepLabel(t) ? `${stepLabel(t)}${input ? `: ${input}` : ""}` : tool || "Working";
};

function initial() {
  const q = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const a = Number(q.get("act")), t = q.get("t");
  const act = Number.isInteger(a) && a >= 1 && a <= ACTS.length ? a - 1 : null;
  return { explore: q.get("explore") === "1", tool: (q.get("tool") as Tool | null) ?? "budget",
    clock: act == null ? (q.get("play") === "1" ? { act: 0, t: 0, playing: true, started: true } : undefined) : { act, t: t != null ? Number(t) * 1000 : ACTS[act].ms, playing: q.get("play") === "1", started: true } };
}

export default function StageView({ scope, areas, open, openSources }: { scope: string; areas: AreaMeta[]; open: Open; openSources: () => void }) {
  const isFI = scope === "FI";
  const init = useMemo(initial, []);
  const root = useRef<HTMLDivElement>(null), box = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const run = useRun(init.clock);

  /* ---------- what the server knows ---------- */
  const geo = useAsync(api.geo, []);
  const ov = useAsync(api.overview, []);
  const funnel = useAsync(api.funnel, []);
  const stage = useAsync(stageApi.stage, []);
  const area = useAsync(() => (isFI ? Promise.resolve(null) : api.area(scope)), [scope]);
  const ivs = useAsync(api.interventions, []);
  const [exclude, setExclude] = useState<string[]>([]);
  const budget0 = isFI ? 5_000_000 : 1_000_000, objective = isFI ? "gap" : null;
  const opt = useAsync(() => api.optimize(scope, budget0, objective, exclude), [scope, exclude.join(",")]);
  // A county with too few patients to compare has no plan to simulate: do not ask.
  const noSim = stage.loading || !!stage.data?.counties.find((c) => c.area_id === scope)?.too_few;
  const sim = useAsync(() => (noSim ? Promise.resolve(null) : stageApi.simulate(scope, budget0, exclude).catch(definite)), [scope, exclude.join(","), noSim]);
  const curve = useAsync(() => stageApi.budgetCurve(scope, objective, exclude).catch(definite), [scope, exclude.join(",")]);
  const planAreas = isFI ? (opt.data?.ui.by_county ?? []).map((b) => b.area_id).join(",") : scope;
  const checks = useAsync(async () => {
    const ids = planAreas ? planAreas.split(",") : [];
    const got = await Promise.all(ids.map((id) => stageApi.checks(id)));
    return new Map(ids.map((id, i) => [id, got[i]]));
  }, [planAreas]);

  /* ---------- explore ---------- */
  const [explore, setExplore] = useState(init.explore);
  const [tool, setTool] = useState<Tool>(init.tool);
  const [budget, setBudget] = useState<number | null>(null);
  const [siteKind, setSiteKind] = useState<SiteKind | null>(init.explore && init.tool === "site" ? "radiotherapy" : null);
  const [sites, setSites] = useState<{ lat: number; lon: number; kind: SiteKind }[]>([]);
  const [siteCost, setSiteCost] = useState<number | null>(null);
  const [level, setLevel] = useState<null | "national" | "best">(null);
  const [unrec, setUnrec] = useState<number | null>(null);
  const scenario = useAsync(() => (sites.length ? stageApi.scenario(sites, siteCost).catch(() => null) : Promise.resolve(null)), [JSON.stringify(sites), siteCost]);
  const [sel, setSel] = useState<string | null>(null);
  const [evIdx, setEvIdx] = useState(0);
  const [tip, setTip] = useState<{ id: string; x: number; y: number } | null>(null);

  /* ---------- the picture ---------- */
  const [size, setSize] = useState<{ W: number; H: number } | null>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const read = () => { const r = el.getBoundingClientRect(); setSize((p) => (p && p.W === Math.round(r.width) && p.H === Math.round(r.height) ? p : { W: Math.round(r.width), H: Math.round(r.height) })); };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const l: Layout | null = useMemo(() => (size ? makeLayout(size.W, size.H) : null), [size]);
  const P = useMemo(() => (geo.data && l ? project(geo.data, l) : null), [geo.data, l]);
  const counties = useMemo(() => (ov.data && P && !stage.loading ? buildCounties(ov.data, stage.data, P.proj, P.shapes) : []), [ov.data, stage.data, stage.loading, P]);
  const places = useMemo(() => (P ? buildPlaces(stage.data, P.proj) : []), [stage.data, P]);
  const focus = isFI ? null : scope;
  const dots = useMemo(() => (P ? buildDots(counties, places, P.shapes, focus) : []), [counties, places, P, focus]);
  const me = counties.find((c) => c.id === scope) ?? null;
  const name = isFI ? "Finland" : me?.name ?? areas.find((a) => a.id === scope)?.short_en ?? "";
  const total = counties.reduce((a, c) => a + c.dots, 0);
  const myDots = isFI ? total : me?.dots ?? 0;
  const tooFew = !isFI && !!me && me.pct == null;
  const natPct = funnel.data?.national.pct ?? stage.data?.counties.find((c) => c.national_pct != null)?.national_pct ?? null;

  /* ---------- nothing plays until the whole stored run is here ---------- */
  const ready = !!(l && P && ov.data && !stage.loading && !stage.error);
  const settled = (x: { loading: boolean; error: string | null }) => !x.loading && !x.error;
  const checksOk = settled(checks) && !!checks.data && (!isFI || (!!opt.data && checks.data.size === (opt.data.ui.by_county ?? []).length));
  const planOk = !!opt.data && !!ivs.data && (isFI || !!area.data) && checksOk && settled(sim);
  const loaded = ready && !!geo.data && settled(funnel) && (tooFew || planOk);
  const loads = [geo, ov, funnel, stage, area, ivs, opt, sim, checks];
  const failed = loads.map((x, i) => (x.error && !x.loading ? i : -1)).filter((i) => i >= 0).join(",");
  const again = useRef<() => void>(() => undefined), tries = useRef(0);
  again.current = () => loads.forEach((x) => { if (x.error && !x.loading) x.reload(); });
  // A load that failed is asked again on its own, sooner when the network comes back. The run waits; it never plays with holes in it.
  useEffect(() => {
    if (!failed) { if (loaded) tries.current = 0; return; }
    const id = window.setTimeout(() => { tries.current++; again.current(); }, Math.min(8000, 1500 * 2 ** tries.current));
    const on = () => again.current();
    window.addEventListener("online", on);
    return () => { window.clearTimeout(id); window.removeEventListener("online", on); };
  }, [failed, loaded]);
  useEffect(() => { run.hold(!loaded); }, [loaded, run.hold]);

  const hosp = useMemo(() => { const h = hospitalFor(me ?? undefined, stage.data); const xy = h && P ? P.proj([h.lon, h.lat]) : null; return h && xy ? { ...h, x: xy[0], y: xy[1] } : null; }, [me, stage.data, P]);
  const hospitals = useMemo(() => (P ? (stage.data?.hospitals ?? []).map((h) => { const xy = P.proj([h.lon, h.lat]) ?? [0, 0]; return { ...h, x: xy[0], y: xy[1] }; }) : []), [stage.data, P]);
  const shape = P?.shapes.find((s) => s.id === scope) ?? null;
  const apart = !!me?.seat && !!hosp && Math.hypot(me.seat.x - hosp.x, me.seat.y - hosp.y) > 14;
  const focusCam: Cam = useMemo(() => {
    if (!l || !shape) return NATIONAL;
    const pts: [number, number][] = [shape.b[0], shape.b[1]];
    if (hosp) pts.push([hosp.x, hosp.y]);
    // Room for the pins that hang under the hospital or the county seat, whichever is lowest.
    const low = hosp && hosp.y >= shape.b[1][1] - 6;
    return fitCam(pts, l, l.phone ? 5 : 6, l.phone ? [0, 0, 0, 14] : [0, 0, 0, low ? 92 : 0]);
  }, [l, shape, hosp]);

  /* ---------- the plan, its checks, its studies ---------- */
  const deaths = opt.data?.ui.metric === "deaths";
  const basePins = useRef<PinM[]>([]);
  const pins: PinM[] = useMemo(() => {
    if (!opt.data || !P) return [];
    if (isFI) { const ps = buildCountyPins(opt.data, counties, P.shapes); relaxBoxes(ps, 132, 27); return ps; }
    const ps = buildPins(opt.data, me?.seat ? [me.seat.x, me.seat.y] : null, hosp ? [hosp.x, hosp.y] : null, [shape?.cx ?? 0, shape?.cy ?? 0]);
    // The action on the road slides along it until its label covers none of the county's patients.
    const road = ps.filter((p) => p.group === "line");
    if (road.length && me?.seat && hosp) {
      const k = focusCam.k, s = me.seat, mine = dots.filter((d) => d.county === scope && !d.extra);
      const at = (t: number) => [s.x + (hosp.x - s.x) * t, s.y + (hosp.y - s.y) * t];
      const t = [0.62, 0.7, 0.78, 0.54, 0.46].find((t) => { const [x, y] = at(t); return !mine.some((d) => { const dx = (d.x - x) * k, dy = (d.y - y) * k; return dx > -230 && dx < 6 && dy > -24 && dy < 42 * road.length - 6; }); });
      if (t != null) road.forEach((p) => { [p.x, p.y] = at(t); });
    }
    if (!exclude.length) basePins.current = ps;
    // Actions taken out in Explore stay on the map, struck through, so they can be put back.
    const gone = basePins.current.filter((b) => exclude.includes(b.id) && !ps.some((p) => p.id === b.id));
    return [...ps, ...gone];
  }, [opt.data, P, isFI, counties, me, hosp, shape, exclude, dots, focusCam.k, scope]);
  const checkOfPin = useCallback((p: PinM, featured: boolean, live?: VerifyResult | null): CheckM => {
    const m = checks.data;
    if (!isFI) return checkOf(p.id, live && live.intervention_id === p.id ? live : m?.get(scope)?.find((v) => v.intervention_id === p.id), featured);
    const mine = (opt.data?.chosen ?? []).filter((c) => c.area_id === p.area).map((c) => m?.get(p.area ?? "")?.find((v) => v.intervention_id === c.intervention_id)).filter(Boolean) as VerifyResult[];
    const some = mine.filter((v) => v.in_use_here && v.in_use_here !== "no_evidence").length;
    const fresh = live && live.area_id === p.area ? live : null;
    const lead = fresh ?? mine.find((v) => v.intervention_id === FEATURED && (v.sources ?? []).length) ?? mine.find((v) => (v.sources ?? []).some((s) => s.quote));
    const base = checkOf(p.id, lead ?? null, featured);
    return { ...base, label: mine.length ? `${some} of ${mine.length}` : null, title: mine.length ? `${some} of ${mine.length} actions at least partly in place` : undefined, tone: some ? "partly" : "none", advice: null, sub: lead?.intervention_id };
  }, [checks.data, isFI, scope, opt.data]);

  const live = useLiveRun<VerifyResult>();
  const [liveState, setLiveState] = useState<"idle" | "running" | "stored" | "done" | "failed">("idle");
  const [liveResult, setLiveResult] = useState<VerifyResult | null>(null);
  const [liveSec, setLiveSec] = useState(0);
  const liveTimer = useRef<number>();

  const featuredId = useMemo(() => {
    const live = pins.filter((p) => !exclude.includes(p.id));
    const has = (p: PinM) => checkOfPin(p, false).pages.some((x) => x.quotes.length);
    const named = live.find((p) => (isFI ? p.area === "21" : p.id === FEATURED));
    if (named && (has(named) || liveResult)) return named.id;
    // The named check is not stored right now: play the strongest stored one in full instead.
    return (live.find((p) => has(p) && checkOfPin(p, false).tone !== "none") ?? live.find(has) ?? live[0])?.id ?? null;
  }, [pins, exclude, checkOfPin, isFI, liveResult]);
  // The check that "Run it live" runs: the named action when the plan has it, else the featured one.
  const liveTarget = useMemo(() => {
    const pin = pins.find((p) => !exclude.includes(p.id) && (isFI ? p.area === "21" : p.id === FEATURED)) ?? pins.find((p) => p.id === featuredId);
    if (!pin) return null;
    const id = isFI ? (opt.data?.chosen.find((c) => c.area_id === pin.area && c.intervention_id === FEATURED) ?? opt.data?.chosen.find((c) => c.area_id === pin.area))?.intervention_id : pin.id;
    return id ? { pin, id, area: isFI ? pin.area! : scope } : null;
  }, [pins, exclude, isFI, featuredId, opt.data, scope]);
  const pinChecks = useMemo(() => new Map(pins.map((p) => [p.id, checkOfPin(p, p.id === featuredId, liveResult)])), [pins, checkOfPin, featuredId, liveResult]);
  const featured = featuredId ? pinChecks.get(featuredId) ?? null : null;
  const ivOf = useCallback((pinId: string | null) => {
    const id = isFI ? pinChecks.get(pinId ?? "")?.sub ?? (opt.data?.chosen.find((c) => c.area_id === pinId)?.intervention_id) : pinId;
    return ivs.data?.interventions.find((i) => i.id === id) ?? null;
  }, [isFI, pinChecks, opt.data, ivs.data]);

  /* ---------- time ---------- */
  const v = explore ? { act: LAST, t: ACTS[LAST].ms } : { act: run.act, t: run.t };
  const a = v.act;
  const nPins = pins.filter((p) => !exclude.includes(p.id)).length;
  const every = Math.min(T.plan.every, 6600 / Math.max(1, nPins));
  const pinsOn = countAt(v, 2, T.plan.first, every, nPins);
  const curvePt = useMemo(() => {
    if (!explore || tool !== "budget" || budget == null || !curve.data) return null;
    return [...curve.data.points].sort((x, y) => x.budget_eur - y.budget_eur).reverse().find((p) => p.budget_eur <= budget + 0.5) ?? null;
  }, [explore, tool, budget, curve.data]);
  const pinOn = (p: PinM, i: number) => !exclude.includes(p.id) && (curvePt?.actions?.length || (curvePt && !isFI) ? !!curvePt.actions?.includes(p.id) : i < pinsOn);
  const landed = pins.filter(pinOn);
  const sumExtra = deaths ? 0 : curvePt ? curvePt.extra : landed.reduce((s, p) => s + p.extra, 0);
  const sumEur = curvePt ? curvePt.spent_eur : landed.reduce((s, p) => s + p.eur, 0);
  const tot = opt.data?.totals;
  const full = pinsOn >= nPins && !curvePt;
  const planExtra = full && tot ? tot.shown.extra : sumExtra;
  // What the web check does to the plan: an action with no public sign of it stays whole, an action found partly in place is paid only for what is missing.
  const narrow = useMemo(() => {
    const o = opt.data, m = checks.data;
    if (!o || !m) return null;
    const z = () => ({ n: 0, eur: 0, extra: 0 });
    const g = { fresh: z(), part: z(), open: z() };
    for (const c of o.chosen) {
      const at = isFI ? c.area_id ?? "" : scope;
      const lv = liveResult && liveResult.intervention_id === c.intervention_id && (liveResult.area_id ?? at) === at ? liveResult : null;
      const use = (lv ?? m.get(at)?.find((x) => x.intervention_id === c.intervention_id))?.in_use_here;
      const k = !use ? "open" : use === "no_evidence" ? "fresh" : "part";
      g[k].n++; g[k].eur += c.eur; g[k].extra += deaths ? c.shown.deaths : c.shown.extra;
    }
    const n = o.chosen.length, high = o.totals.eur;
    return { ...g, n, high, low: Math.max(0, high - g.part.eur) };
  }, [opt.data, checks.data, isFI, scope, liveResult, deaths]);

  // Which dots the plan reaches: in a county the first ones, in Finland each county's share of the whole plan.
  const reachedIds = useMemo(() => {
    const out = new Set<string>();
    if (deaths) return out;
    if (!isFI) { dots.filter((d) => d.county === scope && !d.extra).slice(0, Math.min(myDots, Math.round(planExtra))).forEach((d) => out.add(d.id)); return out; }
    const by = opt.data?.ui.by_county ?? [];
    const share = largestRemainder(by.map((b) => b.extra), Math.round(tot?.shown.extra ?? 0));
    const scale = tot?.shown.extra ? Math.min(1, planExtra / tot.shown.extra) : 0;
    by.forEach((b, i) => {
      if (!curvePt && !landed.some((p) => p.area === b.area_id)) return;
      dots.filter((d) => d.county === b.area_id && !d.extra).slice(0, Math.round(share[i] * (curvePt ? scale : 1))).forEach((d) => out.add(d.id));
    });
    return out;
  }, [deaths, isFI, dots, scope, myDots, planExtra, opt.data, tot, landed.length, curvePt]);   // eslint-disable-line react-hooks/exhaustive-deps
  const years = sim.data?.years.slice(1) ?? [];
  const yearIdx = countAt(v, 5, T.sim.year0, T.sim.yearEvery, years.length);
  const ramp = sim.data?.ramp ?? [];
  const treatedN = a < 5 ? 0 : Math.round(reachedIds.size * (yearIdx > 0 ? ramp[yearIdx - 1] ?? 1 : 0));

  /* ---------- cues ---------- */
  const order = useMemo(() => [...counties].filter((c) => c.pct != null).sort((x, y) => (y.pct ?? 0) - (x.pct ?? 0)), [counties]);
  const fillN = run.started ? Math.round(order.length * progress(v, 0, 200, T.gap.fillEnd)) : order.length;
  const filled = useMemo(() => new Set(order.slice(0, fillN).map((c) => c.id).concat(counties.filter((c) => c.pct == null).map((c) => c.id))), [order, fillN, counties]);
  const dropped = Math.round(total * progress(v, 0, T.gap.dotsFrom, T.gap.dotsEnd));
  const pcts = order.map((c) => c.pct as number), pMin = Math.min(...pcts), pMax = Math.max(...pcts);
  const fills = useMemo(() => {
    const m = new Map<string, string>();
    const bin = (p: number) => SEQ[Math.max(0, Math.min(4, Math.floor(((p - pMin) / Math.max(0.1, pMax - pMin)) * 5)))];
    const lift = explore && tool === "level" && level ? (level === "best" ? stage.data?.counties.find((c) => c.best_quarter_pct != null)?.best_quarter_pct ?? null : natPct) : null;
    counties.forEach((c) => { if (c.pct != null) m.set(c.id, bin(lift != null ? Math.max(c.pct, lift) : c.pct)); });
    return m;
  }, [counties, pMin, pMax, explore, tool, level, stage.data, natPct]);
  const few = useMemo(() => new Set(counties.filter((c) => c.pct == null).map((c) => c.id)), [counties]);
  const levelling = explore && tool === "level";
  const mode: "gap" | "work" = a === 0 || levelling ? "gap" : "work";
  const zoomed = !isFI && a >= 1 && !levelling && !tooFew;
  const cam = zoomed ? focusCam : NATIONAL;
  useCamera(root, cam, l ?? makeLayout(1200, 800), reduced);
  /** How far the county's own dots reach around a point of the map, in screen pixels. A label or a pin stack starts outside them, so no person is drawn over. */
  const around = useCallback((x: number, y: number) => {
    const out = { up: 0, left: 0, right: 0 };
    if (!zoomed) return out;
    const k = focusCam.k, r = 8;
    for (const d of dots) {
      if (d.county !== scope || d.extra) continue;
      const dx = (d.x - x) * k, dy = (d.y - y) * k;
      if (Math.abs(dx) < 52 && dy < r && dy > -44) out.up = Math.max(out.up, r - dy);
      if (dy > -24 && dy < 96 && dx > -r && dx < 36) out.right = Math.max(out.right, dx + r);
      if (dy > -24 && dy < 96 && dx < r && dx > -36) out.left = Math.max(out.left, r - dx);
    }
    return out;
  }, [dots, scope, zoomed, focusCam.k]);
  const recN = explore && tool === "records" && !isFI ? unrec ?? Math.round(me?.hidden ?? 0) : 0;
  const dotCls = useMemo(() => {
    let mine = 0;
    return dots.map((d) => {
      const isMine = !isFI && d.county === scope && !d.extra;
      const k = isMine ? mine++ : -1;
      const on = d.extra ? levelling && level === "best" : d.order < dropped;
      const state = levelling ? (level ? "level" : "lost") : k >= 0 && k >= myDots - recN ? "unrec" : reachedIds.has(d.id) ? (a >= 5 && [...reachedIds].indexOf(d.id) < treatedN ? "treated" : "reached") : "lost";
      return `${on ? "on" : ""} ${state}${zoomed && d.county !== scope ? " dim" : ""}`;
    });
  }, [dots, isFI, scope, levelling, level, dropped, myDots, recN, reachedIds, a, treatedN, zoomed]);

  const sc = scenario.data;
  const closer = useMemo(() => (explore && tool === "site" && sc ? new Set(sc.places.filter((p) => p.km_after < p.km_before - 0.5).map((p) => p.id)) : null), [explore, tool, sc]);
  const sitePts = useMemo(() => (explore && tool === "site" && sc && P ? sc.sites.map((s, i) => { const xy = P.proj([s.lon, s.lat]) ?? [0, 0]; return { ...s, i, x: xy[0], y: xy[1] }; }) : []), [explore, tool, sc, P]);
  const lineOn = reached(v, 1, T.where.line) && apart && zoomed;
  const segs: Seg[] = useMemo(() => {
    const out: Seg[] = [];
    if (me?.seat && hosp && apart) out.push({ id: "road", x1: me.seat.x, y1: me.seat.y, x2: hosp.x, y2: hosp.y, cls: (lineOn ? "on" : "") + (sitePts.length ? " old" : "") });
    // A new site pulls a line from every municipality that gets closer to treatment.
    const to = sitePts[sitePts.length - 1];
    if (closer && to) for (const pl of places) {
      if (closer.has(pl.id) && Math.hypot(pl.x - to.x, pl.y - to.y) > 2) out.push({ id: `site-${pl.id}`, x1: pl.x, y1: pl.y, x2: to.x, y2: to.y, cls: "on new" });
    }
    return out;
  }, [me, hosp, apart, lineOn, sitePts, closer, places]);

  /* ---------- care path ---------- */
  const steps = (isFI ? ov.data?.pathway ?? ov.data?.national.pathway : area.data?.pathway)?.steps ?? [];
  const stepsOn = T.where.step.filter((at) => reached(v, 1, at)).length;
  const mp = area.data?.care_path?.missing_patients;
  const split = useMemo(() => {
    if (!mp || !myDots) return [];
    const ns = largestRemainder(mp.by_modality.map((m) => m.per_year), myDots);
    const words: Record<string, string> = { surgery: "not operated", radiotherapy: "not given curative radiotherapy" };
    return mp.by_modality.map((m, i) => ({ label: words[m.id] ?? m.id, n: ns[i], note: m.note_en }));
  }, [mp, myDots]);

  /* ---------- the check ---------- */
  const shownCheck = (sel && a >= 3 ? pinChecks.get(sel) : null) ?? featured;
  const isFeat = shownCheck === featured;
  const shownPin = shownCheck ? pins.find((p) => p.id === shownCheck.pin) ?? null : null;
  const pages = (shownCheck?.pages ?? []).slice(0, l && l.H < 700 ? 2 : 3);
  const queriesOn = countAt(v, 3, T.check.query0, T.check.queryEvery, Math.min(4, shownCheck?.queries.length ?? 0));
  const pagesOn = liveState === "running" ? 0 : isFeat ? countAt(v, 3, T.check.page0, T.check.pageEvery, pages.length) : pages.length;
  const quotesOn = isFeat ? countAt(v, 3, T.check.page0 + T.check.quoteAfter, T.check.pageEvery, pages.length) : pages.length;
  const others = pins.filter((p) => p.id !== featuredId);
  const restEvery = Math.min(T.check.restEvery, T.check.restSpan / Math.max(1, others.length));
  const restEnd = T.check.rest0 + others.length * restEvery;
  // The moment the plan narrows: every action has its answer.
  const narrowOn = !!narrow && narrow.part.n > 0 && reached(v, 3, restEnd + T.check.narrowAfter);
  const verdictOn = (p: PinM) => (p.id === featuredId ? reached(v, 3, T.check.verdict) : reached(v, 3, T.check.rest0 + others.indexOf(p) * restEvery));
  const adviceOn = (p: PinM) => (p.id === featuredId ? reached(v, 3, T.check.advice) : verdictOn(p));

  const startLive = useCallback(async () => {
    if (!liveTarget || liveState === "running") return;
    const { id, area: at, pin } = liveTarget;
    run.pause(); setSel(pin.id === featuredId ? null : pin.id); setLiveState("running"); setLiveSec(0);
    window.clearInterval(liveTimer.current);
    const t0 = performance.now();
    liveTimer.current = window.setInterval(() => {
      const s = Math.floor((performance.now() - t0) / 1000);
      setLiveSec(s);
      // The server answers within 20 seconds, from the stored check if the live one is not in. If nothing came, say so.
      if (s >= 24) setLiveState((x) => (x === "running" ? "stored" : x));
    }, 250);
    await stageApi.demoFresh(id, at);
    live.start(() => api.verifyStart(id, at), (r) => {
      window.clearInterval(liveTimer.current);
      setLiveResult(r); setSel(null);
      setLiveState(r.live_slow_s != null || r.live_outcome === "failed" || r.live_outcome === "kept" || r.from_cache ? "stored" : "done");
      checks.reload();
    });
  }, [liveTarget, featuredId, liveState, live, run, checks]);
  useEffect(() => { if (live.error) { window.clearInterval(liveTimer.current); setLiveState((x) => (x === "running" || x === "stored" ? "failed" : x)); } }, [live.error]);
  useEffect(() => () => window.clearInterval(liveTimer.current), []);

  /* ---------- the evidence ---------- */
  const evId = useMemo(() => {
    if (isFI) return featuredId;
    const good = (p: PinM) => { const iv = ivs.data?.interventions.find((i) => i.id === p.id); return !!iv && iv.effect.value !== 0 && iv.evidence.some((e) => e.quote); };
    const live = pins.filter((p) => !exclude.includes(p.id));
    return (live.find((p) => p.id === FEATURED && good(p)) ?? live.find((p) => p.id === featuredId && good(p)) ?? live.find(good) ?? live[0])?.id ?? null;
  }, [isFI, featuredId, pins, exclude, ivs.data]);
  const studyIv = ivOf(sel && a >= 4 ? sel : evId);
  const featIv = ivOf(evId);
  const fig = featIv?.evidence[0] ? figureIn(featIv.evidence[0].claim, featIv.evidence[0].quote) : null;
  const flying = !explore && run.playing && a === 4 && v.t >= T.evidence.fly && v.t < T.evidence.value && studyIv === featIv && evIdx === 0 && !!fig;
  const effectOn = (p: PinM) => (a < 4 ? 0 : p.id === evId ? (reached(v, 4, T.evidence.kind) ? 3 : reached(v, 4, T.evidence.range) ? 2 : reached(v, 4, T.evidence.value) ? 1 : 0) : reached(v, 4, T.evidence.kind) ? 3 : 0);
  useEffect(() => { setEvIdx(0); }, [sel, evId]);

  const rows: LedgerRow[] = pins.map((p, i) => {
    const iv = isFI ? null : ivOf(p.id), e = iv && (iv.effect.value !== 0 || iv.effect.hi !== 0) ? effectText(iv.effect) : null;
    return { pin: p, on: pinOn(p, i), off: exclude.includes(p.id), check: pinChecks.get(p.id), checkOn: a >= 3 && adviceOn(p), missOn: a === 3, effect: e && iv ? { ...e, kind: iv.effect.kind ?? "assumption", basis: iv.effect.basis } : null, effectOn: effectOn(p) };
  });
  const rangeOn = reached(v, 2, T.plan.range) || !!curvePt;

  /* ---------- words ---------- */
  const askOn = !explore && reached(v, 5, T.sim.ask);
  // The national plan the map shows (the gap objective under a €5M ceiling), for the last sentence of a county's run.
  const lead = ov.data?.national_lead, nat = lead?.plan_extra_curative_patients_per_year != null && lead.plan_spent_eur != null && lead.plan_counties
    ? { extra: lead.plan_extra_curative_patients_per_year, eur: lead.plan_spent_eur, n: lead.plan_counties, lo: lead.plan_extra_lo ?? 0, hi: lead.plan_extra_hi ?? null } : null;
  const pilot = opt.data?.pilot ?? opt.data?.ui.pilot ?? null;
  const ask = pilot ? [pilot.six_months?.patients_seen?.expected != null ? `about ${whole(pilot.six_months.patients_seen.expected)} patients` : null, pilot.six_months?.no_surgery_decisions_reviewed?.expected != null ? `about ${whole(pilot.six_months.no_surgery_decisions_reviewed.expected)} decisions not to operate reviewed` : null].filter(Boolean).join(", ") || `${pilot.actions.length} actions` : null;
  // What the pilot does, per action: the part the web check did not find in place.
  const pilotParts = (pilot?.actions ?? []).map((id) => { const m = pilot?.missing?.find((x) => x.intervention_id === id), p = pins.find((x) => x.id === id); return p ? { id, name: p.short, missing: pinChecks.get(id)?.missing ?? m?.missing_short_en ?? null, found: m?.in_use_here ?? null } : null; }).filter(Boolean) as { id: string; name: string; missing: string | null; found: string | null }[];
  const unitWord = deaths ? "deaths avoided" : "patients";
  const found = useMemo(() => {
    const n = new Map<string, number>();
    const all = isFI ? [...(checks.data?.entries() ?? [])].flatMap(([id, vs]) => vs.filter((x) => opt.data?.chosen.some((c) => c.area_id === id && c.intervention_id === x.intervention_id))) : pins.map((p) => pinChecks.get(p.id)?.v).filter(Boolean) as VerifyResult[];
    all.forEach((x) => { const w = FOUND[x.in_use_here ?? "no_evidence"] ?? "not found"; n.set(w, (n.get(w) ?? 0) + 1); });
    const out = [...n].sort((x, y) => y[1] - x[1]).map(([w, k]) => `${k} ${w}`);
    const open = isFI ? 0 : pins.filter((p) => !exclude.includes(p.id) && !pinChecks.get(p.id)?.v).length;
    return open && out.length ? [...out, `${open} not checked yet`] : out;
  }, [isFI, checks.data, opt.data, pins, pinChecks, exclude]);

  const cardW = Math.max(220, (l?.colW ?? 380) - (l?.phone ? 0 : 34));
  const ledger = (part?: "head" | "rows") => (
    <Ledger rows={rows} total={sumEur} reached={deaths ? landed.reduce((s, p) => s + p.extra, 0) : planExtra} of={deaths ? null : myDots || null} lo={tot ? (deaths ? tot.deaths_avoided_per_year.lo : tot.extra_curative_patients_per_year.lo) : 0} hi={tot ? (deaths ? tot.deaths_avoided_per_year.hi : tot.extra_curative_patients_per_year.hi) : 0}
      rangeOn={rangeOn} unit={deaths ? "deaths" : "extra"} compact={isFI} sel={sel} onSel={tapPin} flyTo={evId} narrow={narrowOn || (a > 3 && !!narrow && narrow.part.n > 0) ? narrow : null} part={part} />
  );
  // The records check of "Is this gap real?", in the same words; when it cannot tell, the Run says so before it names a step.
  const recCheck = isFI ? null : area.data?.gap_checks?.find((c) => c.id === "records") ?? null;
  const recUnsure = recCheck?.verdict === "cannot_tell";
  const drug = isFI ? null : area.data?.pathway?.drug_finding?.drug ?? null;
  const drugLow = drug && drug.value != null && drug.national != null && drug.value < drug.national - 5 ? drug : null;
  // The ask is made once, in the county the run starts in: the one with the most people short.
  const askFor = !isFI && ask && pilot && !deaths && hosp && counties.length && counties.every((c) => c.dots <= (me?.dots ?? 0)) ? hosp.name_en : null;
  let head: React.ReactNode = null, headKey = `${a}`;
  if (explore) {
    const t = tool === "actions" || tool === "records" ? (isFI ? "budget" : tool) : tool;
    if (t === "budget") head = curvePt ? <>{eurx(curvePt.spent_eur)} a year reaches about {whole(curvePt.extra)}{myDots ? ` of the ${myDots}` : ""}.</> : <>Drag the budget. The map shows who the plan reaches.</>;
    else if (t === "actions") head = tot ? <>{nPins} actions, {eurx(tot.eur)} a year, reach about {whole(tot.shown.extra)} of the {myDots}.</> : <>Take an action out of the plan.</>;
    else if (t === "site") { const s = sc?.sites[sc.sites.length - 1]; head = sc && s ? <>{SITE[s.kind]} in {s.place?.name ?? "this place"}: about {+sc.totals.extra_per_year.median.toFixed(1)} more a year treated to cure, range {+sc.totals.extra_per_year.lo.toFixed(1)} to {+sc.totals.extra_per_year.hi.toFixed(1)}.</> : <>Put a new treatment site on the map.</>; }
    else if (t === "level") head = level ? <>Every county at {level === "best" ? "the best quarter" : "the national share"}: {level === "best" ? counties.reduce((s, c) => s + c.dotsBQ, 0) : total} more people a year treated to cure.</> : <>What if every county did as well as the rest?</>;
    else head = myDots ? <>If {recN} of {name}'s {myDots} were treated but not recorded, the real gap is {myDots - recN}.</> : <>{name} has no gap to question.</>;
  }
  else if (tooFew) head = <>{name}: too few patients to compare.</>;
  else if (!ready || !total) head = <>Loading the stored run.</>;
  else if (a === 0) {
    // No number counts up here: a frame of the run must never show a figure that is not the real one.
    const beat = !run.started || v.t >= T.gap.headline ? 2 : v.t >= T.gap.dotsFrom ? 1 : 0;
    headKey = `0${beat}`;
    head = beat === 0 ? <>The share of lung cancer patients treated to cure, county by county.</>
      : beat === 1 ? <>One dot for each person a year who misses treatment that aims to cure.</>
      : <><span className="num">{total}</span> people a year miss treatment that aims to cure.{!isFI && (myDots > 0 ? <> <span className="num">{myDots}</span> of them in {name}.</> : <> None of them in {name}.</>)}</>;
  } else if (a === 1) {
    if (isFI) { const below = funnel.data?.areas.filter((x) => x.side === "below") ?? []; head = funnel.data ? <>{counties.filter((c) => c.dots > 0).length} counties sit below the national share, {below.filter((x) => x.outside !== "none").length} of them beyond chance.</> : <>Where the patients are lost.</>; }
    else {
      const here = steps.filter((s) => s.verdict === "here"), maybe = steps.filter((s) => s.verdict === "possibly_here");
      const wait = steps.find((s) => s.id === "diagnosis")?.verdict === "not_behind";
      head = here.length && recUnsure ? <>On paper {name} loses them at {here.map((s) => WHERE[s.id] ?? s.label_en).join(" and ")}. Missing records could explain most of it.</>
        : here.length ? <>{wait && here.some((s) => s.id === "treatment") ? "Not the wait. " : ""}{name} loses them at {here.map((s) => WHERE[s.id] ?? s.label_en).join(" and ")}.{maybe.length ? ` ${maybe.map((s) => WHERE[s.id] ?? s.label_en).join(" and ").replace(/^./, (c) => c.toUpperCase())} may add to it.` : ""}</>
        : maybe.length ? <>A possible weak point in {name}: {maybe.map((s) => WHERE[s.id] ?? s.label_en).join(" and ")}.</>
        : steps.length ? <>No step of the care path stands out in {name}.</> : <>Where {name} loses them.</>;
    }
  } else if (a === 2) {
    const n = isFI ? opt.data?.chosen.length ?? 0 : landed.length;
    head = !opt.data ? <>Loading the plan.</> : n === 0 ? <>Which actions close the most of the gap for the money?</> : deaths ? <>{myDots === 0 ? "No one is short here, so the plan is ranked by deaths avoided. " : ""}{n} {n === 1 ? "action" : "actions"}, {eurx(sumEur)} a year: about {one(landed.reduce((s, p) => s + p.extra, 0))} a year.</>
      : <>{n} {n === 1 ? "action" : "actions"}{isFI ? ` in ${pins.length} counties` : ""}, {eurx(sumEur)} a year, {n === 1 ? "reaches" : "reach"} about {whole(planExtra)} of the {myDots}.</>;
  } else if (a === 3) {
    if (narrowOn) headKey = "3n";
    head = !checksOk ? <>Loading the stored web checks.</> : !found.length ? <>No stored web check for this plan.</>
      : narrowOn && narrow ? <>{narrow.part.n} of {narrow.n} actions already partly run. The plan pays only for what is missing: {eurx(narrow.low)} to {eurx(narrow.high)} a year.</>
      : reached(v, 3, restEnd) ? <>Each action checked on the web: {found.join(", ")}.</> : <>Is each action already in place? Reading the public pages.</>;
  }
  else if (a === 4) { const e = featIv ? effectText(featIv.effect) : null; const p = pins.find((x) => x.id === evId); head = featIv && e ? <>{isFI ? shortName(featIv.id, featIv.name_en) : p?.short}: {e.value}, range {e.range}. {featIv.effect.kind === "measured" ? "Measured in" : `An ${featIv.effect.kind ?? "assumption"} from`} {featIv.evidence.length} {featIv.evidence.length === 1 ? "study" : "studies"}.</> : <>The studies behind the plan.</>; }
  else if (deaths && tot) head = <>{myDots === 0 ? "At or above the national share: the" : "The"} plan avoids about {one(tot.shown.deaths)} deaths a year.</>;
  else if (askOn && ask && pilot?.audit && pilot.six_months?.no_surgery_decisions_reviewed?.expected != null && sim.data) {
    // The run ends on one sentence: what is counted here first, then the same run at the scale of the country.
    headKey = "5a";
    const worst = counties.reduce((m, c) => (c.dots > (m?.dots ?? -1) ? c : m), counties[0]);
    head = nat && nat.n > 1 ? <>Six months in {name}{worst?.id === scope ? " first" : ", counted"}, then the same run in all {nat.n} counties: about {whole(nat.extra)} of the {total} a year for {eurx(nat.eur)}.</>
      : <>Six months in {name}: {pilot.audit.charts} charts and about {whole(pilot.six_months.no_surgery_decisions_reviewed.expected)} decisions counted, in place of the model's {whole(sim.data.reached.median)} a year.</>;
  }
  else if (isFI && askOn && nat && nat.n > 1 && nat.hi != null && sim.data) {
    headKey = "5a";
    const worst = counties.reduce((m, c) => (c.dots > (m?.dots ?? -1) ? c : m), counties[0]);
    head = <>The same run in all {nat.n} counties: about {whole(nat.extra)} of the {total} a year for {eurx(nat.eur)}, range {whole(nat.lo)} to {whole(nat.hi)}{worst ? <>, {worst.name} first</> : null}.</>;
  }
  else head = sim.data && yearIdx < years.length ? <>The plan played forward, year by year, to {years[years.length - 1]}.</>
    : sim.data ? (narrow && narrow.part.n > 0 ? <>If the hospital confirms all {narrow.n} are missing in full: about {whole(sim.data.reached.median)} more a year treated to cure by {years[years.length - 1]}, range {whole(sim.data.reached.lo)} to {whole(sim.data.reached.hi)}.</>
      : <>By {years[years.length - 1]}, about {whole(sim.data.reached.median)} more a year treated to cure, range {whole(sim.data.reached.lo)} to {whole(sim.data.reached.hi)}.</>)
    : <>The plan, year by year.</>;

  /* ---------- the activity line ---------- */
  const log = useMemo(() => {
    const out: Activity[] = [], f = funnel.data, fa = f?.areas.find((x) => x.id === scope);
    if (f) out.push({ act: 0, at: 0, text: `Reading registry report${f.page ? `, page ${f.page}` : ""}: Finland ${int(f.national.k)} of ${int(f.national.n)} = ${one(f.national.pct)}%`, src: { kind: "measured", source_id: f.source_id, source_url: f.source_url, page: f.page, read_by: f.read_by, period: f.period, quote: f.quote, what: f.label_en, value: `${one(f.national.pct)}%` } });
    if (f && fa) out.push({ act: 0, at: 1400, text: `Reading registry report, page ${fa.page ?? f.page}: ${name} ${int(fa.k)} of ${int(fa.n)} = ${one(fa.pct)}%`, src: srcOfFunnel(f, scope, name) });
    if (total) out.push({ act: 0, at: T.gap.dotsFrom, text: `Shortfall against the national share: ${total} people a year in ${counties.filter((c) => c.dots > 0).length} counties${me && myDots ? `, ${one(me.missing)} in ${name}` : ""}` });
    if (me && hosp && me.km != null) out.push({ act: 1, at: T.where.line, text: `Distance to ${hosp.name_en}: ${int(Math.round(me.km))} km (straight line x 1.3, by where people live)` });
    steps.forEach((s, i) => { const g = s.figures.find((x) => x.value != null && x.national != null); if (g) out.push({ act: 1, at: T.where.step[Math.min(i, 3)], text: `${g.label_en}: ${one(g.value)} here, ${one(g.national)} in Finland${g.page ? ` (page ${g.page})` : ""}`, src: { kind: g.kind, source_id: g.source_id, source_url: g.source_url, page: g.page, quote: g.quote, read_by: g.read_by, period: g.period, what: g.label_en } }); });
    const o = opt.data;
    if (o) {
      out.push({ act: 2, at: 0, text: `Optimiser: ${o.chosen.length} of ${o.chosen.length + o.not_chosen.length} actions bought, ${eurx(o.totals.eur)} a year` });
      pins.forEach((p, i) => out.push({ act: 2, at: T.plan.first + i * every, text: isFI ? `${p.short}: ${p.count} actions, ${eurx(p.eur)} a year` : `${p.name}: ${eurx(p.eur)} a year` }));
    }
    const fc = featured;
    if (fc?.v) {
      fc.queries.slice(0, 4).forEach((q, i) => out.push({ act: 3, at: T.check.query0 + i * T.check.queryEvery, text: `Searching: ${q}` }));
      fc.pages.slice(0, 3).forEach((p, i) => {
        out.push({ act: 3, at: T.check.page0 + i * T.check.pageEvery, text: `Reading ${p.domain}: ${p.title}`, url: p.url });
        if (p.quotes.length) out.push({ act: 3, at: T.check.page0 + i * T.check.pageEvery + T.check.quoteAfter, text: `Quote found word for word on ${p.domain}`, url: p.url });
      });
      if (fc.label) out.push({ act: 3, at: T.check.verdict, text: `${fc.label}${fc.advice ? `. Advice: ${fc.advice.toLowerCase()}` : ""} (stored check of ${when(fc.v.checked_at)})` });
      others.forEach((p, i) => { const c = pinChecks.get(p.id); if (c?.v && c.label) out.push({ act: 3, at: T.check.rest0 + i * restEvery, text: `${p.short}: ${c.searches} searches, ${c.pages.length} pages read. ${c.label}`, url: c.pages[0]?.url }); });
    }
    if (narrow && narrow.part.n > 0) out.push({ act: 3, at: restEnd + T.check.narrowAfter, text: `Plan narrowed: ${eurx(narrow.low)} for the ${narrow.n - narrow.part.n} with no public sign, up to ${eurx(narrow.part.eur)} more for what is missing in the other ${narrow.part.n}` });
    const ev = featIv?.evidence[0];
    if (featIv && ev) {
      const e = effectText(featIv.effect);
      out.push({ act: 4, at: 0, text: `Study: ${[ev.design, ev.year, ev.n != null ? `n = ${int(ev.n)}` : null].filter(Boolean).join(", ")}`, url: ev.url ?? undefined });
      out.push({ act: 4, at: T.evidence.value, text: `Effect in the plan: ${e.value}, range ${e.range} (${featIv.effect.kind ?? "assumption"})` });
    }
    const s = sim.data;
    if (s) {
      out.push({ act: 5, at: 0, text: `${int(s.runs_total ?? 0)} simulated runs of ${s.years[1]} to ${s.years[s.years.length - 1]}, ${int(s.patients_per_year)} patients a year` });
    }
    // The run ends on what the pilot counts, not on what the model expects.
    if (ask && pilot) out.push({ act: 5, at: T.sim.ask, text: `Six months, counted: ${ask}` });
    return out.sort((x, y) => x.act - y.act || x.at - y.at);
  }, [funnel.data, scope, name, total, counties, me, myDots, hosp, steps, opt.data, pins, every, isFI, featured, others, pinChecks, restEvery, featIv, sim.data, narrow, ask, pilot]);   // eslint-disable-line react-hooks/exhaustive-deps
  const liveStep = live.steps[live.steps.length - 1];
  const now: Activity | null = liveState === "running" || (liveState === "stored" && live.running)
    ? { act: 3, at: 0, text: liveStep ? `Live: ${liveLine(liveStep)}` : "Live: starting the check", url: liveStep?.url ?? undefined }
    : explore || !run.started ? null : [...log].reverse().find((e) => reached(v, e.act, e.at)) ?? null;

  /* ---------- lines from the pin to the pages it was checked against ---------- */
  const [links, setLinks] = useState<string[]>([]);
  const linkPin = pins.find((p) => p.id === (shownCheck?.pin ?? ""));
  useLayoutEffect(() => {
    const r = root.current;
    if (!r || !l || l.phone || explore || a !== 3 || !linkPin) { setLinks((p) => (p.length ? [] : p)); return; }
    const o = r.getBoundingClientRect(), x2 = cam.k * linkPin.x + cam.tx, y2 = cam.k * linkPin.y + cam.ty;
    const out: string[] = [];
    r.querySelectorAll<HTMLElement>(".st-page.on").forEach((el) => {
      const b = el.getBoundingClientRect(), x1 = b.right - o.left, y1 = b.top - o.top + Math.min(26, b.height / 2), dx = Math.max(40, (x2 - x1) * 0.5);
      out.push(`M${x1.toFixed(1)},${y1.toFixed(1)}C${(x1 + dx).toFixed(1)},${y1.toFixed(1)} ${(x2 - dx).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`);
    });
    setLinks((p) => (p.join("|") === out.join("|") ? p : out));
  }, [l, explore, a, linkPin, cam, pagesOn, shownCheck]);

  /* ---------- keys ---------- */
  const leave = useCallback(() => { setExplore(false); setBudget(null); setSites([]); setSiteKind(null); setLevel(null); setUnrec(null); setExclude([]); }, []);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (!loaded && e.key !== "Escape") return;
      if (e.key === " ") { e.preventDefault(); if (!tooFew) { leave(); run.toggle(); } }
      else if (e.key === "ArrowRight" && !tooFew) { leave(); run.next(); }
      else if (e.key === "ArrowLeft" && !tooFew) { leave(); run.prev(); }
      else if (e.key === "Escape") { setSel(null); setSiteKind(null); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [run.toggle, run.next, run.prev, leave, tooFew, loaded]);

  const tapPin = (id: string) => {
    if (explore && tool === "actions" && !isFI) { setExclude((x) => (x.includes(id) ? x.filter((y) => y !== id) : [...x, id])); return; }
    setSel((s) => (s === id ? null : id));
  };
  const place = (bx: number, by: number) => {
    const ll = P?.proj.invert?.([bx, by]);
    if (!ll || !siteKind) return;
    setSites((s) => [...s, { lon: +ll[0].toFixed(4), lat: +ll[1].toFixed(4), kind: siteKind }]);
    setSiteKind(null);
  };
  const runFor = (id: string, play = false) => { window.location.hash = `#/run/${id}${play ? "?play=1" : ""}`; };
  // The counties with the most people missing, as one-tap runs: the same steps, a different county, a different plan.
  const moreRuns = [...counties].filter((c) => c.id !== scope && c.dots > 0).sort((x, y) => y.dots - x.dots || x.name.localeCompare(y.name)).slice(0, 4);
  const otherRuns = (label: string) => moreRuns.length > 0 && (
    <div className="st-others on">
      <span>{label}</span>
      {moreRuns.map((c) => <button key={c.id} className="btn sm" onClick={() => runFor(c.id, true)}>{c.name} <small className="num">{c.dots}</small></button>)}
      {!isFI && <button className="btn sm" onClick={() => runFor("FI", true)}>Finland <small className="num">{total}</small></button>}
    </div>
  );
  const B3: [string, string][] = [["detection", "Found late"], ["referral", "Referred slowly"], ["diagnosis", "Treated slowly"]];
  const B3V: Record<string, string> = { not_behind: "no", here: "yes, here", possibly_here: "possibly", cannot_tell: "cannot tell: not published by county" };
  const pickCounty = a === 0 && !explore ? (id: string) => { window.location.hash = `#/run/${id}`; } : undefined;

  /* ---------- pins grouped by where they stand ---------- */
  const groups = useMemo(() => {
    const by = new Map<string, { key: string; x: number; y: number; pins: PinM[] }>();
    pins.forEach((p) => { const key = isFI ? p.id : p.group; const g = by.get(key) ?? { key, x: p.x, y: p.y, pins: [] }; g.pins.push(p); by.set(key, g); });
    return [...by.values()];
  }, [pins, isFI]);
  const midX = l ? (l.region[0] + l.region[2]) / 2 : 0;
  const numbers = useMemo(() => new Map(pins.map((p) => [p.id, p.n])), [pins]);

  const fatal = !ready ? geo.error ?? ov.error ?? stage.error : null;
  // One-line pins once the check is over (the words have moved to the plan card), and always on a short screen.
  const cls = `st a${a}${l?.phone ? " phone" : l && l.H < 700 ? " short" : ""}${l && !l.phone && (l.H < 700 || (!explore && a >= 4)) ? " slim" : ""}${explore ? " explore" : ""}${run.playing ? " playing" : ""}${zoomed ? " zoomed" : ""}${reduced ? " reduced" : ""}`;
  const hot = tip ? counties.find((c) => c.id === tip.id) : null;
  const lr = liveResult, storedAt = when(lr?.checked_at ?? featured?.v?.checked_at);
  const liveNote = liveState === "running" ? `Checking live, ${liveSec} s`
    : liveState === "done" ? "Live answer, checked just now."
    : liveState === "failed" ? `The live check failed${featured?.v ? `. Stored answer of ${storedAt} shown` : ""}.`
    : liveState === "stored" ? (!lr ? `No answer in 20 s${featured?.v ? `. Stored answer of ${storedAt} shown` : ""}.` : lr.live_slow_s != null ? `Stored answer of ${storedAt}: the live check took longer than ${lr.live_slow_s} s.` : lr.live_outcome === "kept" ? (lr.live_pinned ? `Live run done. The plan keeps the stored answer of ${storedAt}.` : `Stored answer of ${storedAt}: this run found less.`) : `Stored answer of ${storedAt}: the live check did not finish.`)
    : null;
  const liveSteps = liveState === "running" ? live.steps.slice(-5) : [];

  return (
    <div ref={root} className={cls} style={{ ["--col" as string]: `${l?.colW ?? 380}px`, ["--pad" as string]: `${l?.pad ?? 24}px` }}>
      <div ref={box} className="st-mapbox">
        {!ready && !fatal && <div className="st-skel" role="status" aria-label="Loading the map"><svg viewBox="0 0 120 220" aria-hidden="true"><path d="M52 4l14 6 6 20-4 16 12 22-2 26 14 30-8 34-22 30-26 8-20-10-8-26 10-30-4-28 16-26-2-30 10-24z" /></svg></div>}
        {fatal && <p className="st-quiet st-fatal" role="alert">The connection dropped. Trying again. <button className="btn sm" onClick={() => again.current()}>Try now</button></p>}
        {ready && l && P && (
          <>
            <StageMap layout={l} shapes={P.shapes} mode={mode} fills={fills} filled={a === 0 && !explore ? filled : null} focus={zoomed ? scope : null} few={few} places={places} placesOn={(reached(v, 1, T.where.places) && !levelling) || false} closer={closer}
              dots={dots} dotCls={dotCls} segs={segs} cam={cam} placing={!!siteKind} onPlace={place} onPick={pickCounty}
              onHover={mode === "gap" ? (id, e) => setTip(id && e ? { id, x: e.clientX, y: e.clientY } : null) : undefined}
              label={`Map of Finland by wellbeing services county. ${total} people a year miss treatment that aims to cure${!isFI && myDots ? `, ${myDots} of them in ${name}` : ""}.`} />
            {links.length > 0 && <svg className="st-links" width={l.W} height={l.H} aria-hidden="true">{links.map((d, i) => <path key={i} d={d} pathLength={1} />)}</svg>}
            <div className="st-over">
              {mode === "work" && hospitals.filter((h) => isFI || !zoomed || h.id === hosp?.id).map((h) => {
                // Where the county's own patients sit around the hospital, its name goes above them.
                const up = !isFI && h.id === hosp?.id ? around(h.x, h.y).up : 0;
                return (
                  <Pinned key={h.id} x={h.x} y={h.y} className={"st-hosp" + ((isFI ? a === 1 : h.id === hosp?.id) ? " lead" : "") + (up ? " over" : "") + (reached(v, 1, T.where.places) ? " on" : "")} style={up ? { ["--up" as string]: `${Math.round(up)}px` } : undefined}>
                    <i title={h.name_en} /><span>{h.city}{!isFI && h.id === hosp?.id ? " University Hospital" : ""}</span>
                  </Pinned>
                );
              })}
              {zoomed && me?.seat && apart && !sitePts.some((s) => Math.hypot(s.x - me.seat!.x, s.y - me.seat!.y) < 3) && (
                <Pinned x={me.seat.x} y={me.seat.y} className={"st-seat" + (reached(v, 1, T.where.places) ? " on" : "")} style={{ ["--up" as string]: `${Math.round(around(me.seat.x, me.seat.y).up)}px` }}>
                  <i />
                  <span>
                    <b>{me.seat.name}</b>
                    {hosp && me.km != null && !sitePts.length && <em className={"st-km num" + (reached(v, 1, T.where.lineLabel) ? " on" : "")} title={stage.data?.notes?.places_en}>{int(Math.round(me.km))} km to {hosp.city} on average</em>}
                  </span>
                </Pinned>
              )}
              {sitePts.map((s) => <Pinned key={s.i} x={s.x} y={s.y} className="st-site on"><i className={s.kind} /><span title={s.place?.name ?? undefined}>{SITE[s.kind]}</span></Pinned>)}
              {a >= 2 && (!explore || tool === "budget" || tool === "actions" || (isFI && tool === "records")) && groups.map((g) => {
                const left = !isFI && (g.key === "line" || cam.k * g.x + cam.tx > midX + 60);
                // The stack starts clear of the patients drawn around its place.
                const room = isFI || g.key === "line" ? 0 : around(g.x, g.y)[left ? "left" : "right"];
                return (
                <Pinned key={g.key} x={g.x} y={g.y} className={"st-stack" + (left ? " left" : "") + (isFI ? " fi" : "") + ` g-${g.key}`} style={room ? { ["--off" as string]: `${Math.round(room + (l.phone ? 2 : 8))}px` } : undefined}>
                  {g.pins.map((p) => {
                    const i = pins.indexOf(p), c = pinChecks.get(p.id), vOn = !explore && a >= 3 && !!c?.label && verdictOn(p);
                    const said = vOn ? `${p.name}. ${c!.label}.${c!.missing ? ` Missing: ${c!.missing}.` : ""}` : p.name;
                    return (
                      <button key={p.id} className={"st-pin" + (pinOn(p, i) ? " on" : "") + (exclude.includes(p.id) ? " off" : "") + (sel === p.id ? " sel" : "") + (p.id === featuredId && a === 3 ? " feat" : "")} onClick={() => tapPin(p.id)} title={said} aria-pressed={explore && tool === "actions" ? !exclude.includes(p.id) : sel === p.id}>
                        <i className="num">{exclude.includes(p.id) ? "–" : p.count ?? p.n}</i>
                        <span className="st-pin-t">
                          <b className={isFI ? "num" : undefined}>{isFI ? eur(p.eur) : p.short}</b>
                          {!isFI && (vOn ? <em className={`st-chip ${c!.tone}`}><u aria-hidden="true" />{c!.label}</em> : !explore && a >= 3 && !c?.v && checks.data ? <em>Not checked yet</em> : <em className="num">{eurx(p.eur)}/yr · {+p.extra.toFixed(1)} {deaths ? "deaths avoided" : "patients"}/yr</em>)}
                          {!isFI && vOn && c!.missing && <em className="st-miss">Missing: {c!.missing}</em>}
                          {isFI && vOn && <em className={`st-chip num ${c!.tone}`} title={c!.title}><u aria-hidden="true" />{c!.label}</em>}
                        </span>
                      </button>
                    );
                  })}
                </Pinned>
                );
              })}
            </div>
          </>
        )}
      </div>

      <section className="st-left" aria-live="polite">
        <p className="st-kicker">{explore ? "Explore" : <><span className="num">{a + 1}</span> {ACTS[a].label}</>}
          <label className="st-pick">Run for
            <select value={scope} onChange={(e) => runFor(e.target.value)} aria-label="Choose the county to run">
              <option value="FI">Finland</option>
              {[...areas].sort((x, y) => (x.short_en ?? "").localeCompare(y.short_en ?? "")).map((x) => <option key={x.id} value={x.id}>{x.short_en}</option>)}
            </select>
          </label>
        </p>
        {head && <h1 className="st-h on" key={headKey}>{head}</h1>}
        {/* On a phone the sum and its range follow the headline; the rows come after the pages. */}
        {l?.phone && !explore && a >= 2 && a <= 4 && opt.data && ledger("head")}

        {!explore && a === 0 && ready && (
          <div className="st-gap">
            {natPct != null && (
              <div className="st-stats">
                <button onClick={() => funnel.data && openSource({ kind: "measured", source_id: funnel.data.source_id, source_url: funnel.data.source_url, page: funnel.data.page, read_by: funnel.data.read_by, period: funnel.data.period, quote: funnel.data.quote, what: funnel.data.label_en, value: `${one(natPct)}%` })}><b className="num">{one(natPct)}%</b><span>treated to cure in Finland</span></button>
                {!isFI && me?.pct != null && <button onClick={() => { const s = srcOfFunnel(funnel.data, scope, name); if (s) openSource(s); }}><b className="num">{one(me.pct)}%</b><span>in {name}</span></button>}
              </div>
            )}
            {!isFI && me && me.pct != null && myDots === 0 && <p className="st-fine on">At or above the national share.</p>}
            {/* How to read the map: one group, so it is not three loose notes. */}
            <div className="st-mapkey">
              {pcts.length > 0 && (
                <div className="st-legend" aria-label={`Counties coloured by share treated to cure, from ${one(pMin)}% (dark) to ${one(pMax)}% (light)`}>
                  <span className="num">{one(pMin)}%</span>{SEQ.map((c) => <i key={c} style={{ background: c }} />)}<span className="num">{one(pMax)}%</span>
                  <em>fewer treated to cure → more</em>
                </div>
              )}
              <p className="st-fine on"><i className="st-key lost" /> one person a year short of the national share.</p>
              {stage.data?.notes?.patients_en && <details className="st-more"><summary>How the dots are placed</summary><p>{stage.data.notes.patients_en}</p></details>}
            </div>
            {/* What this run is and where else it goes: at the foot of the column, next to Run. */}
            <div className="st-foot">
              <p className="st-fine on"><b>Why lung cancer.</b> It is one of the cancers in Goal 3 of the national cancer strategy, and the Cancer Registry publishes treatment by county for it.</p>
              {otherRuns("Every county gets its own run. Tap one on the map, or:")}
            </div>
          </div>
        )}

        {explore && ready && (
          <p className="st-fine on st-keys">
            {tool === "level" ? level ? <><i className="st-key level" style={{ marginLeft: 0 }} /> one more person a year treated to cure at that share</> : <><i className="st-key lost" /> one person a year short of the national share</>
              : tool === "site" ? <><i className="st-key lost" /> missed today <i className="st-key closer" /> municipalities that get closer to treatment</>
              : <><i className="st-key lost" /> still missed <i className="st-key treated" /> reached by the plan{tool === "records" && !isFI && <> <i className="st-key unrec" /> treated, not recorded</>}</>}
          </p>
        )}

        {!explore && a === 3 && (
          <div className="st-check">
            {liveTarget && (isFeat || shownCheck?.pin === liveTarget.pin.id || !shownCheck?.v) && (
              <div className="st-live">
                <button className="btn sm" onClick={startLive} disabled={liveState === "running" || live.running}>Run it live{liveTarget.pin.id !== featuredId && !isFI ? `: ${liveTarget.pin.short}` : ""}</button>
                {liveNote && <span className={"st-livenote " + liveState} role="status">{liveNote}</span>}
              </div>
            )}
            {liveState === "running" ? null : shownCheck?.v ? (
              <>
                {isFeat && a === 3 && pagesOn === 0 && queriesOn < shownCheck.queries.length + 1
                  ? <ol className="st-trace">{shownCheck.queries.slice(0, queriesOn).map((q, i) => <li key={q} className={i === queriesOn - 1 ? "now" : ""}>Searching: {q}</li>)}</ol>
                  : <p className="st-mono">{shownCheck.searches} searches · {shownCheck.pages.length} pages read · {[...new Set(shownCheck.pages.map((p) => p.domain))].join(", ")}</p>}
                {isFI && shownPin && <p className="st-fine on">Shown: the check for {shownPin.short}. Each of the {pins.length} counties has its own: pick one on the map.</p>}
                {pages.map((p, i) => <PageCard key={p.url} p={p} i={i} on={i < pagesOn} quoteOn={i < quotesOn} />)}
              </>
            ) : <p className="st-quiet">{!checksOk ? "Loading the stored checks" : sel ? "Not checked yet: no stored web check for this action." : "No stored web check for this plan."}</p>}
            {liveSteps.length > 0 && (
              <ol className="st-trace">
                {liveSteps.map((t, i) => <li key={String(t.step ?? i)} className={i === liveSteps.length - 1 ? "now" : ""}>{liveLine(t)}</li>)}
              </ol>
            )}
          </div>
        )}

        {!explore && a === 4 && (studyIv ? <><StudyCard iv={studyIv} idx={evIdx} setIdx={setEvIdx} quoteOn={reached(v, 4, T.evidence.quote)} flying={false} /><ProofLine p={ov.data?.outside_proof} actionId={studyIv.id} /></> : <p className="st-quiet">{ivs.error ? "The studies are not available right now." : ""}</p>)}

        {!explore && a === 5 && (
          <div className={"st-ask" + (askOn ? " on" : "")}>
            {!(ask && pilot) && <p>{isFI ? "The plan county by county, with who does what." : `The plan for ${name}, with who does what.`}</p>}
            {ask && pilot && nat && nat.n > 1 && nat.hi != null && !isFI && !deaths && <span className="st-fine on num">The {whole(nat.extra)} is modelled, range {whole(nat.lo)} to {whole(nat.hi)}. The six months are counted: {pilot.audit?.charts} charts, about {whole(pilot.six_months?.no_surgery_decisions_reviewed?.expected ?? 0)} decisions.</span>}
            {askFor && <p className="st-askline">What we ask: one introduction, to {name}'s wellbeing services county and {askFor}.</p>}
            <button className="btn primary" onClick={() => open("plan")}>Open the plan</button>
            {ask && pilot && (
              <details className="st-more st-sixmonths">
                <summary>What the six months do{nat && !isFI && !deaths ? ", and where the numbers come from" : ""}</summary>
                <div className="st-pilot">
                  <span>Six months with {name}{hosp ? ` and ${hosp.city}` : ""}: <span className="num">{ask}</span>. Counted, not modelled.</span>
                  {pilotParts.some((x) => x.missing) && <>
                    <span>The pilot runs the two actions that decide who is treated, for the part the check did not find:</span>
                    <ul>{pilotParts.map((x) => <li key={x.id}><b>{x.name}.</b> {x.missing ? `Missing: ${x.missing}.` : "No public sign of it: the pilot starts it."}</li>)}</ul>
                  </>}
                  {pilot.effect.curative_share_after_pct != null && pilot.effect.curative_share_now_pct != null && !deaths && (
                    <span className="num">The model for these {pilot.actions.length} actions alone: {one(pilot.effect.curative_share_now_pct)}% → {one(pilot.effect.curative_share_after_pct)}% by {pilot.effect.by_year ?? years[years.length - 1]}{tot?.curative_share_after_pct != null ? ` (all ${nPins} actions: ${one(tot.curative_share_after_pct)}%)` : ""}.</span>
                  )}
                  {nat && !isFI && !deaths && <span className="num">The national plan is modelled: about {whole(nat.extra)} of the {total} a year{nat.hi != null ? `, range ${whole(nat.lo)} to ${whole(nat.hi)}` : ""}, {eurx(nat.eur)} a year in {nat.n} counties.</span>}
                </div>
              </details>
            )}
            {otherRuns("The same run, another county, a different plan:")}
          </div>
        )}

        {!explore && a === 1 && !isFI && steps.length > 0 && (
          <div className={"st-three" + (reached(v, 1, T.where.step[2]) ? " on" : "")}>
            <p>The three bottlenecks the challenge names, checked for {name}:</p>
            <ul>
              {B3.map(([id, label]) => { const st = steps.find((x) => x.id === id); return st ? <li key={id} className={st.verdict ?? ""}><span>{label}?</span> <b>{B3V[st.verdict ?? ""] ?? st.verdict_en}</b></li> : null; })}
              {recCheck?.short_answer_en && <li className={recUnsure ? "possibly_here" : ""}><span>Only missing records?</span> <b>{recCheck.short_answer_en.replace(/^./, (c) => c.toLowerCase()).replace(/\.$/, "")}</b></li>}
            </ul>
            {steps.some((x) => x.id === "treatment" && x.verdict === "here") && !B3.some(([id]) => steps.find((x) => x.id === id)?.verdict === "here") && (recUnsure
              ? <p className="st-so">On paper the gap is a fourth step: who is given treatment that aims to cure. The chart check comes first: it shows how much of it is real.</p>
              : B3.some(([id]) => steps.find((x) => x.id === id)?.verdict === "possibly_here")
              ? <p className="st-so">The clear gap is a fourth step: who is given treatment that aims to cure. The steps marked possibly may add to it.</p>
              : steps.find((x) => x.id === "detection")?.verdict === "cannot_tell"
              ? <p className="st-so">So the gap shows at a fourth step: who is given treatment that aims to cure. Whether late stage is behind it, the chart check tells.</p>
              : <p className="st-so">So the gap is a fourth step: who is given treatment that aims to cure.</p>)}
            {drugLow && <p className="st-also num">Also low: drug therapy on record, {one(drugLow.value)}% here against {one(drugLow.national)}% in Finland. The registry under-records it, so the chart check also counts biomarker tests and drug treatment. <button className="st-fig" onClick={() => openSource({ kind: drugLow.kind, source_id: drugLow.source_id, source_url: drugLow.source_url, page: drugLow.page, quote: drugLow.quote, read_by: drugLow.read_by, period: drugLow.period, what: drugLow.label_en, value: `${one(drugLow.value)}%` })}>Source</button></p>}
          </div>
        )}
      </section>

      <aside className="st-right">
        <nav className="st-nav" aria-label="More on this area">
          <button onClick={() => open("monday")}>Who does what on Monday</button>
          <button onClick={() => open("county", "why")}>Is this gap real?</button>
        </nav>
        {explore ? (
          <div className="st-card">
            <Explore tool={tool} setTool={(t) => { setTool(t); setSiteKind(t === "site" && !sites.length ? "radiotherapy" : null); }} isFI={isFI} name={name} w={cardW} unit={deaths ? "Deaths avoided a year" : "Patients reached a year"}
              curve={curve.data} curveLoading={curve.loading} budget={budget} setBudget={setBudget} numbers={numbers} myDots={myDots}
              pins={pins} exclude={exclude} toggle={tapPin} total={opt.data?.totals.eur ?? null} extra={tot ? { median: tot.shown.extra, lo: tot.extra_curative_patients_per_year.lo, hi: tot.extra_curative_patients_per_year.hi } : null} optLoading={opt.loading}
              siteKind={siteKind} setSiteKind={setSiteKind} scenario={sc} scenarioLoading={scenario.loading && sites.length > 0} nSites={sites.length} removeSite={() => setSites((s) => s.slice(0, -1))} siteCost={siteCost} setSiteCost={setSiteCost} hasStage={!!stage.data} focus={focus}
              level={level} setLevel={setLevel} totalDots={total} bestDots={counties.reduce((s, c) => s + c.dotsBQ, 0)} natPct={natPct} bestPct={stage.data?.counties.find((c) => c.best_quarter_pct != null)?.best_quarter_pct ?? null}
              unrec={recN} setUnrec={setUnrec} hidden={me?.hidden ?? null} auditEur={basePins.current.find((p) => p.id === "recording_audit")?.eur ?? null} />
          </div>
        ) : a === 1 && steps.length > 0 ? (
          <div className="st-card"><CarePathCard steps={steps} national={isFI} shown={stepsOn} split={split} splitOn={reached(v, 1, T.where.split)} lost={myDots || null} /></div>
        ) : a >= 2 && a <= 4 ? (
          <div className="st-card">
            {!opt.data ? <p className="st-quiet" role="status">Loading the plan</p>
              : ledger(l?.phone ? "rows" : undefined)}
          </div>
        ) : a === 5 ? (
          <div className="st-card">
            {deaths && myDots === 0 && tot ? (
              <p className="st-quiet">{name} already treats a larger share to cure than Finland as a whole, so there is no share to raise and nothing to play forward. Its plan is counted in deaths avoided: about {one(tot.shown.deaths)} a year, range {one(Math.max(0, tot.deaths_avoided_per_year.lo))} to {one(tot.deaths_avoided_per_year.hi)}.</p>
            ) : sim.data ? (
              <>
                <p className="st-year"><b className="num">{yearIdx > 0 ? years[yearIdx - 1] : sim.data.baseline_period?.replace("-", "–") ?? sim.data.years[0]}</b><span className="num">{yearIdx === 0 ? "measured, before the plan" : reachedIds.size ? (myDots ? `${treatedN} of the ${myDots} missed are now treated to cure` : `${treatedN} of ${reachedIds.size} reached are treated to cure`) : "share treated to cure, with and without the plan"}</span></p>
                <SimChart sim={sim.data} nat={!isFI} upto={yearIdx} w={cardW} scope={`all ${narrow?.n ?? nPins} actions`} />
                {reachedIds.size > 0 && <p className="st-fine on"><i className="st-key reached" /> reached by the plan <i className="st-key treated" /> treated to cure <i className="st-key lost" /> still missed</p>}
              </>
            ) : <p className="st-quiet" role="status">{!settled(sim) || stage.loading ? "Loading the simulation" : "No simulation for this plan."}</p>}
          </div>
        ) : null}
      </aside>

      <footer className="st-bottom">
        <div className="st-activity">
          {!loaded && !tooFew && <span className="st-loading" role="status"><i aria-hidden="true" />{failed ? "The connection dropped. Trying again." : "Loading the stored run"}{failed && <button className="btn sm" onClick={() => again.current()}>Try now</button>}</span>}
          {loaded && now && (
            <button key={now.text} onClick={() => (now.src ? openSource(now.src as SrcRef) : now.url ? window.open(now.url, "_blank", "noreferrer") : undefined)} disabled={!now.src && !now.url} title={now.src || now.url ? "Open the source" : undefined}>
              <i aria-hidden="true" />{now.text}
            </button>
          )}
        </div>
        <div className="st-bar" role="group" aria-label="The run">
          <button className="btn primary st-run" onClick={() => { leave(); run.toggle(); }} disabled={tooFew || !loaded}>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">{run.playing ? <path d="M2 1h3v10H2zM7 1h3v10H7z" /> : <path d="M2.5 1l8 5-8 5z" />}</svg>
            {run.playing ? "Pause" : "Run"}
          </button>
          <ol className="st-steps">
            {ACTS.map((x, i) => (
              <li key={x.id}>
                <button onClick={() => { leave(); setSel(null); run.jump(i); }} aria-current={!explore && run.started && a === i ? "step" : undefined} disabled={(tooFew && i > 0) || !loaded} className={!explore && run.started && i < a ? "past" : ""}>
                  <i className="num">{i + 1}</i><span>{x.label}</span>
                  <em style={{ ["--p" as string]: explore || !run.started ? 0 : i < a ? 1 : i > a ? 0 : run.t / x.ms }} />
                </button>
              </li>
            ))}
          </ol>
          <button className="btn" onClick={() => { leave(); setSel(null); run.replay(); }} disabled={tooFew || !loaded}>Replay</button>
          <button className="btn st-explore" aria-pressed={explore} onClick={() => { if (explore) leave(); else { run.pause(); setSel(null); setExplore(true); } }} disabled={tooFew || !loaded}>Explore</button>
        </div>
      </footer>

      <Fly root={root} on={flying} text={fig?.text ?? ""} />
      {hot && tip && <div className="tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 240), top: tip.y + 14 }}><b>{hot.name}</b><span>{hot.pct == null ? "too few patients to compare" : `${one(hot.pct)}% treated to cure · ${hot.dots} a year short`}</span></div>}
    </div>
  );
}

