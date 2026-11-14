import { ApiError, Interval, Kind, sleep, VerifyResult } from "../lib";

/* ---------- the map stage: shapes of the answers it draws ---------- */
export interface StageHospital { id: string; name_en: string; city: string; lat: number; lon: number }
export interface StagePlace { id: string; name: string; area_id: string; lat: number; lon: number; population: number; km: number; nearest: string }
export interface StageCounty {
  area_id: string; name_en: string; lat: number; lon: number; population: number; patients_per_year: number | null; curative_pct: number | null; national_pct: number | null;
  missing_per_year: number | null; missing_lo?: number | null; missing_hi?: number | null; too_few?: boolean; best_quarter_pct?: number | null; missing_vs_best_quarter_per_year?: number | null; km: number | null; pop_65plus_pct?: number | null; yta?: string | null;
  seat?: { id: string; name: string; lat: number; lon: number } | null; records?: { flagged?: boolean; hidden_per_year?: number | null; hidden_max_per_year?: number | null } | null;
}
export interface StagePayload {
  hospitals: StageHospital[]; places: StagePlace[]; counties: StageCounty[];
  distance?: { n_counties?: number; rho?: number; rho_after_65plus?: number; pp_per_100km?: number; pp_per_100km_after_65plus?: number; note_en?: string } | null;
  notes?: { places_en?: string; patients_en?: string; sites_en?: string } | null;
}
export type SiteKind = "radiotherapy" | "full";
export interface ScenarioSite { lat: number; lon: number; kind: SiteKind; place?: { id: string; name: string; area_id: string } | null; cost_eur_per_year?: number | null; cost_kind?: Kind; cost_basis_en?: string | null }
export interface Scenario {
  sites: ScenarioSite[]; places: { id: string; km_before: number; km_after: number }[];
  counties: { area_id: string; name_en?: string; km_before: number; km_after: number; curative_pct_before: number; curative_pct_after: Interval; extra_per_year: Interval }[];
  totals: { people_closer: number; extra_per_year: Interval; cost_eur_per_year: number | null; eur_per_extra_patient: number | null; eur_per_extra_patient_best_case?: number | null };
  compare?: { area_id: string; name_en: string; plan_eur_per_year: number; plan_extra_per_year: number; plan_eur_per_extra_patient: number | null } | null;
  assumption_en?: string; kind?: Kind;
}
export interface BudgetCurve {
  points: { budget_eur: number; spent_eur: number; extra: number; lo: number; hi: number; actions?: string[]; n_actions?: number }[];
  steps: { at_eur: number; intervention_id: string; area_id?: string; name_en: string; eur: number; extra: number }[];
  flat_from_eur: number | null; max_extra: number; shortfall: number | null; note_en?: string; kind?: Kind;
}
export interface SimPlan {
  years: number[]; baseline_pct: number; baseline_period?: string; runs_total?: number; plan_above_no_plan_in_100?: number | null; target_pct: number; national_pct: number | null; patients_per_year: number; ramp: number[];
  band: { year: number; p10: number; p50: number; p90: number; no_plan_p10: number; no_plan_p50: number; no_plan_p90: number; expected?: number }[];
  runs?: number[][]; reached: Interval; chance_note_en?: string; assumptions_en?: string[]; kind?: Kind; n_runs?: number;
}

/** `null` = the server does not have this answer (yet); anything else that fails is an error the caller shows as a quiet line. */
async function ask<T>(path: string, body?: unknown): Promise<T | null> {
  let res: Response | null = null;
  // A dropped connection or a busy server is asked again before it counts as a failure; the view then keeps asking.
  for (let i = 0; ; i++) {
    try { res = await fetch(path, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); } catch { res = null; }
    if ((res === null || [502, 503, 504].includes(res.status)) && i < AGAIN_MS.length) { await sleep(AGAIN_MS[i]); continue; }
    break;
  }
  if (res === null) throw new ApiError("Kello did not answer.", 0);
  if ([404, 405, 501].includes(res.status)) return null;
  if (!res.ok) throw new ApiError("That part of Kello did not answer.", res.status);
  return (await res.json()) as T;
}
const AGAIN_MS = [400, 1200, 3000];
export const stageApi = {
  /** The stored web checks of one county. A failed load is an error, never "no checks". */
  checks: (area_id: string) => ask<{ checks?: VerifyResult[] }>(`/api/verify/latest?area_id=${encodeURIComponent(area_id)}&stored=1`).then((r) => r?.checks ?? []),
  stage: () => ask<StagePayload>("/api/stage"),
  scenario: (sites: { lat: number; lon: number; kind: SiteKind }[], cost_eur_per_year?: number | null) => ask<Scenario>("/api/scenario", { sites, ...(cost_eur_per_year != null ? { cost_eur_per_year } : {}) }),
  budgetCurve: (scope: string, objective?: string | null, exclude?: string[]) => ask<BudgetCurve>("/api/budget-curve", { scope, ...(objective ? { objective } : {}), ...(exclude?.length ? { exclude } : {}) }),
  simulate: (scope: string, budget_eur: number, exclude?: string[]) => ask<SimPlan>("/api/simulate-plan", { scope, budget_eur, ...(exclude?.length ? { exclude } : {}), runs: SIM_RUNS, seed: SIM_SEED }),
  demoFresh: (intervention_id: string, area_id: string) => fetch(`/api/demo/reset?fresh=${intervention_id}:${area_id}`, { method: "POST" }).then(() => undefined, () => undefined),
};
/** The simulation is asked for with a fixed seed, so the same picture comes back every time. */
export const SIM_RUNS = 300, SIM_SEED = 7;

/* ---------- arithmetic used to turn published numbers into whole dots ---------- */
/** Whole numbers that add up to `total`, as close to `values` as possible (largest remainder). */
export function largestRemainder(values: number[], total: number): number[] {
  const sum = values.reduce((a, b) => a + Math.max(0, b), 0);
  if (!(sum > 0) || total <= 0) return values.map(() => 0);
  const exact = values.map((v) => (Math.max(0, v) / sum) * total);
  const out = exact.map(Math.floor);
  let left = total - out.reduce((a, b) => a + b, 0);
  const order = exact.map((v, i) => [v - Math.floor(v), i] as const).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let i = 0; left > 0 && i < order.length; i++, left--) out[order[i][1]]++;
  return out;
}
/** Which place the j-th dot of a county goes to: by population, and the first n dots never move when n grows. */
export function apportion(pops: number[], n: number): number[] {
  const got = pops.map(() => 0), out: number[] = [];
  for (let j = 0; j < n; j++) {
    let best = 0, bestQ = -1;
    pops.forEach((p, i) => { const q = p / (got[i] + 0.5); if (q > bestQ) { bestQ = q; best = i; } });
    got[best]++; out.push(best);
  }
  return out;
}
/** The k-th point of a sunflower: dots that share an anchor fan out around it instead of stacking. */
export function sunflower(k: number, spacing: number): [number, number] {
  if (k === 0) return [0, 0];
  const a = k * 2.399963, r = spacing * Math.sqrt(k) * 0.82;
  return [Math.cos(a) * r, Math.sin(a) * r];
}
/** Push overlapping dots apart; fixed order, fixed passes, so the picture is the same every time. */
export function relax(pts: { x: number; y: number }[], min: number, passes = 40) {
  for (let p = 0; p < passes; p++) {
    let moved = false;
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      let dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y;
      let d = Math.hypot(dx, dy);
      if (d >= min) continue;
      if (d < 1e-6) { dx = Math.cos(i * 1.7 + j); dy = Math.sin(i * 1.7 + j); d = 1; }
      const push = (min - d) / 2 / d;
      pts[i].x -= dx * push; pts[i].y -= dy * push; pts[j].x += dx * push; pts[j].y += dy * push;
      moved = true;
    }
    if (!moved) break;
  }
}
/** The same for labels that are wider than tall: two that overlap move apart up and down, never sideways. */
export function relaxBoxes(pts: { x: number; y: number }[], w: number, h: number, passes = 80) {
  for (let p = 0; p < passes; p++) {
    let moved = false;
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      const dy = pts[j].y - pts[i].y;
      if (Math.abs(pts[j].x - pts[i].x) >= w || Math.abs(dy) >= h) continue;
      const push = (h - Math.abs(dy)) / 2 + 0.05, s = dy >= 0 ? 1 : -1;
      pts[i].y -= s * push; pts[j].y += s * push;
      moved = true;
    }
    if (!moved) break;
  }
}

/* ---------- words ---------- */
/** Two to four words for a pin. The full name the API gives is always one tap away. */
const SHORT: Record<string, string> = {
  recording_audit: "Chart audit", sbrt_pathway: "Radiotherapy referral rule", travel_accommodation_support: "Travel and hotel paid", prehab_fitness_assessment: "Fitness test first",
  surgeon_second_opinion: "Surgeon's second look", video_mdt_stage1_3: "Weekly video review", cpp_pathway: "Booked pathway slots", same_day_cxr_ct: "Same-day X-ray and CT",
  gp_direct_ct: "GP direct CT", nurse_navigator: "Nurse navigator", symptom_campaign: "Cough campaign", ldct_screening: "Low-dose CT screening", reflex_molecular: "Reflex gene testing",
  smoking_cessation_at_diagnosis: "Stop-smoking help",
};
export function shortName(id: string, name: string): string {
  if (SHORT[id]) return SHORT[id];
  const w = name.replace(/\(.*?\)/g, "").split(/\s+/).filter(Boolean);
  return w.length <= 4 ? w.join(" ") : `${w.slice(0, 3).join(" ")}…`;
}
export const host = (u?: string | null) => { try { return new URL(u ?? "").hostname.replace(/^www\./, ""); } catch { return ""; } };
/** A whole number of people for a headline: 5.24 -> "5". */
export const whole = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "–" : String(Math.round(n)));
