import { geoPath, geoTransverseMercator, GeoProjection } from "d3-geo";
import { AreaDetail, Chosen, Funnel, Intervention, OptResult, Overview, SrcRef, VerifyResult } from "../lib";
import { adviceWord, IN_USE_SHORT } from "../WebCheck";
import { apportion, host, largestRemainder, relax, shortName, StageCounty, StageHospital, StagePayload, StagePlace, sunflower } from "./data";

/* Everything the stage draws, worked out once from the API answers. No number is made here that the API did not give,
   except whole dots: published patients a year rounded so that they add up (largest remainder). */

export interface Layout { W: number; H: number; phone: boolean; region: [number, number, number, number]; colW: number; pad: number }
export interface Shape { id: string; name: string; d: string; cx: number; cy: number; b: [[number, number], [number, number]] }
export interface Cam { k: number; tx: number; ty: number }
export interface CountyM { id: string; name: string; pct: number | null; missing: number; dots: number; bq: number | null; dotsBQ: number; km: number | null; population: number | null; patients: number | null;
  seat: { name: string; x: number; y: number } | null; hidden: number | null; flagged: boolean; yta: string | null }
export interface DotM { id: string; county: string; idx: number; x: number; y: number; order: number; extra: boolean }
export interface PlaceM { id: string; name: string; county: string; x: number; y: number; r: number; pop: number; km: number; rank: number }
export interface PinM { id: string; n: number; short: string; name: string; eur: number; extra: number; lo: number; hi: number; kind: string; group: "seat" | "hospital" | "line" | "county"; x: number; y: number; area?: string; count?: number }
export interface PageM { url: string; domain: string; title: string; quotes: string[]; about?: string }
export interface CheckM { pin: string; v: VerifyResult | null; label: string | null; tone: string; advice: string | null; adviceCode: string | null; pages: PageM[]; queries: string[]; searches: number; featured: boolean; sub?: string; title?: string }

export function makeLayout(W: number, H: number): Layout {
  const phone = W < 760;
  if (phone) return { W, H, phone, region: [14, 10, W - 14, H - 12], colW: W - 32, pad: 16 };
  const pad = W >= 1400 ? 32 : 24;
  const colW = Math.round(Math.max(300, Math.min(410, W * 0.285)));
  return { W, H, phone, region: [pad + colW + 8, 18, W - pad - colW - 8, H - 104], colW, pad };
}

export function project(geo: GeoJSON.FeatureCollection, l: Layout): { proj: GeoProjection; shapes: Shape[] } {
  const [x0, y0, x1, y1] = l.region;
  const proj = geoTransverseMercator().rotate([-26, 0]).fitExtent([[x0, y0], [x1, y1]], geo);
  const path = geoPath(proj);
  const shapes = geo.features.map((f) => {
    const p = (f.properties ?? {}) as Record<string, string>;
    const c = path.centroid(f), b = path.bounds(f);
    return { id: String(p.id), name: p.short_en ?? String(p.id), d: path(f) ?? "", cx: c[0], cy: c[1], b };
  });
  return { proj, shapes };
}

/** The camera that fits a set of points (in base map pixels) into the free part of the stage. */
export function fitCam(pts: [number, number][], l: Layout, maxK = 7, inset: [number, number, number, number] = [0, 0, 0, 0]): Cam {
  if (!pts.length) return { k: 1, tx: 0, ty: 0 };
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const bx0 = Math.min(...xs), bx1 = Math.max(...xs), by0 = Math.min(...ys), by1 = Math.max(...ys);
  const m = l.phone ? 18 : 34;
  const x0 = l.region[0] + m + inset[0], y0 = l.region[1] + m + inset[1], x1 = l.region[2] - m - inset[2], y1 = l.region[3] - m - inset[3];
  const k = Math.max(1, Math.min(maxK, (x1 - x0) / Math.max(1, bx1 - bx0), (y1 - y0) / Math.max(1, by1 - by0)));
  return { k, tx: (x0 + x1) / 2 - k * (bx0 + bx1) / 2, ty: (y0 + y1) / 2 - k * (by0 + by1) / 2 };
}

const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);

export function buildCounties(ov: Overview, st: StagePayload | null, proj: GeoProjection, shapes: Shape[]): CountyM[] {
  const sc = new Map<string, StageCounty>((st?.counties ?? []).map((c) => [c.area_id, c]));
  const rows = ov.areas.map((a) => {
    const s = sc.get(a.id), care = a.care as (Record<string, unknown> | null | undefined);
    const pct = s ? num(s.curative_pct) : num(care?.curative_share_pct);
    const missing = pct == null ? 0 : (s ? num(s.missing_per_year) : num(care?.missing_patients_per_year)) ?? 0;
    const bq = s && pct != null ? num(s.missing_vs_best_quarter_per_year) : null;
    const seatP = s?.seat ? proj([s.seat.lon, s.seat.lat]) : null;
    const sh = shapes.find((x) => x.id === a.id);
    return { id: a.id, name: a.short_en, pct, missing, dots: 0, bq, dotsBQ: 0, km: s ? num(s.km) : null, population: s ? num(s.population) : null, patients: s ? num(s.patients_per_year) : num(a.patients_per_year),
      seat: seatP && s?.seat ? { name: s.seat.name, x: seatP[0], y: seatP[1] } : sh ? null : null, hidden: num(s?.records?.hidden_per_year), flagged: !!s?.records?.flagged, yta: s?.yta ?? a.yta ?? null } as CountyM;
  });
  const total = Math.round(rows.reduce((a, r) => a + r.missing, 0));
  largestRemainder(rows.map((r) => r.missing), total).forEach((n, i) => { rows[i].dots = n; });
  if (rows.some((r) => r.bq != null)) {
    const tb = Math.round(rows.reduce((a, r) => a + (r.bq ?? 0), 0));
    largestRemainder(rows.map((r) => r.bq ?? 0), tb).forEach((n, i) => { rows[i].dotsBQ = Math.max(n, rows[i].dots); });
  }
  return rows;
}

export function buildPlaces(st: StagePayload | null, proj: GeoProjection): PlaceM[] {
  const out = (st?.places ?? []).map((p: StagePlace) => {
    const xy = proj([p.lon, p.lat]) ?? [0, 0];
    return { id: p.id, name: p.name, county: p.area_id, x: xy[0], y: xy[1], r: 1 + Math.sqrt(Math.max(0, p.population) / 1000) * 0.5, pop: p.population, km: p.km, rank: 0 };
  });
  // The order they appear in: nearest to a university hospital first.
  [...out].sort((a, b) => a.km - b.km || a.id.localeCompare(b.id)).forEach((p, i) => { p.rank = i; });
  return out;
}

/** One dot per missing patient a year, placed where people live: each county's dots go to its municipalities by population. */
export function buildDots(counties: CountyM[], places: PlaceM[], shapes: Shape[], focus: string | null): DotM[] {
  const dots: DotM[] = [];
  const order = [...counties].filter((c) => Math.max(c.dots, c.dotsBQ) > 0).sort((a, b) => (a.id === focus ? 1 : 0) - (b.id === focus ? 1 : 0) || a.missing - b.missing || a.id.localeCompare(b.id));
  for (const c of order) {
    const n = Math.max(c.dots, c.dotsBQ);
    const ps = places.filter((p) => p.county === c.id).sort((a, b) => b.pop - a.pop || a.id.localeCompare(b.id));
    const sh = shapes.find((s) => s.id === c.id);
    const where = ps.length ? apportion(ps.map((p) => p.pop), n) : Array.from({ length: n }, () => -1);
    const seen = new Map<number, number>();
    where.forEach((pi, j) => {
      const k = seen.get(pi) ?? 0; seen.set(pi, k + 1);
      const [ox, oy] = sunflower(k, pi < 0 ? 6.4 : 5.2);
      const ax = pi < 0 ? sh?.cx ?? 0 : ps[pi].x, ay = pi < 0 ? sh?.cy ?? 0 : ps[pi].y;
      dots.push({ id: `${c.id}-${j}`, county: c.id, idx: j, x: ax + ox, y: ay + oy, order: 0, extra: j >= c.dots });
    });
  }
  relax(dots, 7.6);
  let o = 0;
  dots.forEach((d) => { if (!d.extra) d.order = o++; });
  dots.forEach((d) => { if (d.extra) d.order = o++; });
  return dots;
}

export function hospitalFor(c: CountyM | undefined, st: StagePayload | null): StageHospital | null {
  if (!c || !st?.hospitals?.length) return null;
  const byYta = st.hospitals.find((h) => h.id === c.yta);
  if (byYta) return byYta;
  const ps = st.places.filter((p) => p.area_id === c.id).sort((a, b) => b.population - a.population);
  return st.hospitals.find((h) => h.id === ps[0]?.nearest) ?? null;
}

const pinOf = (c: Chosen, n: number, group: PinM["group"], x: number, y: number, deaths: boolean): PinM => {
  const iv = deaths ? c.deaths_avoided_per_year : c.extra_curative_patients_per_year;
  return { id: c.intervention_id, n, short: shortName(c.intervention_id, c.name_en), name: c.name_en, eur: c.eur, extra: deaths ? c.shown.deaths : c.shown.extra, lo: iv.lo, hi: iv.hi, kind: c.effect_kind ?? "assumption", group, x, y };
};

/** Where each action of a county plan happens: the university hospital, the county seat, or the road between them. */
export function buildPins(opt: OptResult, seat: [number, number] | null, hosp: [number, number] | null, centre: [number, number]): PinM[] {
  const deaths = opt.ui.metric === "deaths";
  const apart = !!seat && !!hosp && Math.hypot(seat[0] - hosp[0], seat[1] - hosp[1]) > 14;
  return opt.chosen.map((c, i) => {
    const n = c.n ?? i + 1;
    if (c.owner_level === "collaborative_area" && hosp) return pinOf(c, n, "hospital", hosp[0], hosp[1], deaths);
    if (c.intervention_id === "travel_accommodation_support" && apart) return pinOf(c, n, "line", seat![0] + (hosp![0] - seat![0]) * 0.62, seat![1] + (hosp![1] - seat![1]) * 0.62, deaths);
    const at = seat ?? centre;
    return pinOf(c, n, "seat", at[0], at[1], deaths);
  });
}
/** The national plan: one pin per county that gets actions, with how many and what they cost. */
export function buildCountyPins(opt: OptResult, counties: CountyM[], shapes: Shape[]): PinM[] {
  return (opt.ui.by_county ?? []).map((b) => {
    const c = counties.find((x) => x.id === b.area_id), sh = shapes.find((x) => x.id === b.area_id);
    const rows = opt.chosen.filter((x) => x.area_id === b.area_id);
    return { id: b.area_id, n: b.n, short: b.area_en, name: b.measures.map((m) => m.name_en).join("; "), eur: b.eur, extra: b.extra,
      lo: rows.reduce((a, r) => a + r.extra_curative_patients_per_year.lo, 0), hi: rows.reduce((a, r) => a + r.extra_curative_patients_per_year.hi, 0),
      kind: "estimated", group: "county" as const, x: c?.seat?.x ?? sh?.cx ?? 0, y: c?.seat?.y ?? sh?.cy ?? 0, area: b.area_id, count: b.measures.length };
  });
}

/** The pages one stored check read, grouped so that a page appears once with every sentence quoted from it. */
export function pagesOf(v: VerifyResult): PageM[] {
  const out: PageM[] = [];
  for (const s of v.sources ?? []) {
    if (!s.url) continue;
    let p = out.find((x) => x.url === s.url);
    if (!p) { p = { url: s.url, domain: host(s.url), title: s.title ?? host(s.url), quotes: [], about: s.about }; out.push(p); }
    if (s.quote && !p.quotes.includes(s.quote)) p.quotes.push(s.quote);
  }
  // The page that answers "is it in place here" goes first.
  const lead = v.in_use_source?.url;
  return out.sort((a, b) => (a.url === lead ? 0 : 1) - (b.url === lead ? 0 : 1));
}
const TONE: Record<string, string> = { yes: "yes", partly: "partly", planned: "partly", no_evidence: "none" };
export function checkOf(pin: string, v: VerifyResult | null | undefined, featured: boolean): CheckM {
  if (!v) return { pin, v: null, label: null, tone: "none", advice: null, adviceCode: null, pages: [], queries: [], searches: 0, featured };
  const queries = v.queries?.length ? v.queries : (v.trace ?? []).filter((t) => /search/i.test(t.tool ?? "") && typeof t.input === "string").map((t) => t.input as string);
  return { pin, v, label: v.in_use_label_en ?? IN_USE_SHORT[v.in_use_here ?? ""] ?? null, tone: TONE[v.in_use_here ?? ""] ?? "none", advice: adviceWord(v), adviceCode: v.advice ?? null,
    pages: pagesOf(v), queries, searches: v.searches ?? queries.length, featured };
}

/** The study number that the plan's effect leans on: the first figure of the claim that the quoted sentence also contains. */
export function figureIn(claim: string, quote: string | null | undefined): { text: string; start: number; end: number } | null {
  if (!quote) return null;
  for (const m of claim.matchAll(/\d+(?:[.,]\d+)?/g)) {
    const re = new RegExp(`(?<![\\d.,])${m[0].replace(".", "\\.")}(?![\\d])\\s?(?:%|points?|percentage points?)?`);
    const hit = re.exec(quote);
    if (hit) return { text: hit[0].trim(), start: hit.index, end: hit.index + hit[0].trimEnd().length };
  }
  return null;
}

export interface Activity { act: number; at: number; text: string; src?: SrcRef; url?: string }
export const srcOfFunnel = (f: Funnel | null, id: string, name: string): SrcRef | undefined => {
  const a = f?.areas.find((x) => x.id === id);
  return a && f ? { kind: "measured", source_id: f.source_id, source_url: f.source_url, page: a.page, quote: a.quote, read_by: f.read_by, period: f.period, what: `Share treated to cure, ${name}`, value: `${a.pct}%` } : undefined;
};
export type { AreaDetail, Intervention };
