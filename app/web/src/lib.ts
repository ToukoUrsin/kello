import { useEffect, useRef, useState, useSyncExternalStore } from "react";

/* ---------- types: the v3 API, one shape per answer ---------- */
export type Kind = "measured" | "estimated" | "assumption";
export interface Interval { median: number; lo: number; hi: number }
export interface AreaMeta { id: string; name_fi: string; name_en: string; short_fi: string; short_en: string; yta?: string | null; yta_name_fi?: string | null; patients_per_year?: number | null; deaths_per_year?: number | null }
/** A measured value with its provenance. Every field but `value` may be missing. */
export interface MeasuredVal { value: number; national?: number | null; rank?: number | null; unit?: string; period?: string; source_id?: string; source_url?: string; page?: number | string | null; read_by?: string | null; level?: string; quote?: string | null }
export interface CareSummary { curative_share_pct: number; lo?: number | null; hi?: number | null; n?: number | null; national_pct?: number | null; outside_limits?: string | null; missing_patients_per_year?: number | null; expected_pct?: number | null; recording_flag?: boolean }
export interface OverviewArea { id: string; short_en: string; short_fi: string; yta?: string | null; total_days: Interval; worst_step: string; care?: CareSummary | null; measured?: Record<string, MeasuredVal | null> | null; patients_per_year?: number | null }
export interface PathwayFigure { label_en: string; value: number | null; national: number | null; unit?: string; kind: Kind; verdict_en: string; source_id?: string | null; source_url?: string | null; page?: number | string | null; quote?: string | null; read_by?: string | null; period?: string | null; note_en?: string | null }
export interface PathwayStep { id: string; label_en: string; figures: PathwayFigure[]; verdict?: "here" | "possibly_here" | "not_behind" | "cannot_tell"; verdict_en: string; answer_en?: string; what_not_published_en: string }
export interface Pathway { steps: PathwayStep[]; note_en?: string; what_finland_does_not_publish?: string[]; distance_en?: string; stage_bound_en?: string; drug_finding?: { drug: PathwayFigure; life_prolonging: PathwayFigure; next_en?: string | null } }
export interface Overview { national: { total_days: Interval; gap_checks?: GapCheck[]; gap_checks_overall_en?: string; gap_checks_overall_fi?: string; pathway?: Pathway }; areas: OverviewArea[]; pathway?: Pathway; outside_proof?: OutsideProof | null; gap_checks?: GapCheck[]; gap_checks_overall_en?: string; national_lead?: { patients_short_per_year: number; patients_short_in_seven_counties: number; counties: number; plan_budget_eur: number; plan_extra_curative_patients_per_year: number; plan_gap_closed_pct: number; plan_spent_eur: number; plan_extra_lo?: number | null; plan_extra_hi?: number | null; plan_counties?: number | null; note_en?: string }; clock_note_en?: string | null; fixture?: boolean }

/** One stage of the care path: what share of a county's lung cancer patients reach it. */
export interface Stage { id: string; label_en: string; value: number | null; unit?: string; n?: number | null; lo?: number | null; hi?: number | null; national?: number | null;
  best?: number | null; best_area?: string | null; best_area_en?: string | null; worst?: number | null; worst_area_en?: string | null; rank?: number | null; of?: number | null;
  outside_limits?: "none" | "95" | "99.8" | null; side?: "below" | "above" | null; direction?: "higher_better" | "lower_better" | "context"; level?: string; kind?: Kind;
  source_url?: string | null; page?: number | string | null; quote?: string | null; read_by?: string | null; period?: string | null; note_en?: string | null; count?: number | null;
  registry_ci?: Partial<Record<"men" | "women", { pct: number; lo: number; hi: number; national_pct: number }>> | null }
export interface ArtefactFlag { stage_id: string; strength: "strong" | "possible"; text_en: string }
export interface MissingPatients { reference_pct?: number | null; per_year: number; lo?: number | null; hi?: number | null; by_modality: { id: string; per_year: number; note_en?: string }[];
  top_quartile?: { reference_pct?: number | null; per_year: number; lo?: number | null; hi?: number | null } | null; note_en?: string | null; split_method_en?: string | null;
  counties_below_limits_en?: string[]; per_year_in_counties_below_limits?: number | null }
export interface Expected { observed_pct: number; expected_pct: number; ratio: number; lo: number; hi: number; verdict: "below_expected" | "as_expected" | "above_expected" | string; pop_65plus_pct?: number | null;
  km_to_university_hospital?: number | null; adjusted_for: string[]; not_adjusted_for: string[]; sentence_en?: string; method_en?: string; distance_en?: string; why_not_standardised_en?: string }
export interface CarePath { patients_per_year?: number | null; period?: string; stages: Stage[]; artefact_flags: ArtefactFlag[]; limits_note_en?: string | null; note_en?: string | null;
  main_leak: { stage_id: string | null; sentence_en: string; patients_per_year?: number | null; basis_en?: string } | null; missing_patients: MissingPatients | null; expected: Expected | null }
export interface ProofItem { id: string; action_id?: string | null; action_en?: string | null; introduced_en?: string | null; where_en: string; period: string; what_en: string; before: { label: string; value: number; n?: string | null }; after: { label: string; value: number; n?: string | null }; unit: string; change_pp?: number | null; kind: Kind; quote: string; quote_lang?: string | null; source_title?: string | null; source_url: string; page?: number | string | null; caveat_en?: string | null; model?: { value?: number | null; lo?: number | null; hi?: number | null; kind?: string | null } | null }
export interface OutsideProof { backtest_en?: string | null; summary_en?: string | null; items: ProofItem[] }
export interface GapCheck { id: string; question_en: string; question_fi: string; answer_en: string; answer_fi: string; short_answer_en?: string; short_answer_fi?: string; verdict: "holds" | "mostly_holds" | "cannot_tell" | "weakens" | string; kind: Kind; source_url?: string | null; page?: number | string | null; quote?: string | null; read_by?: string | null; period?: string | null }
export interface Driver { indicator: string; label_en: string; value: number; national: number | null; unit: string; period: string; source_id: string; kind: Kind }
export interface Step { id: string; label_en: string; days: Interval; national_days: number; kind: Kind; level?: string; method_en?: string }
export interface SourceRec { title?: string; publisher?: string; url?: string | null; retrieved_at?: string | null; licence?: string; notes?: string | null; verified?: boolean;
  values?: number; used?: boolean; status?: "opened" | "listed" }
export interface ConsistencyCheck { what_en?: string; summary_en?: string; results?: { indicator: string; label_en: string; sentence_en: string; verdict?: string }[] }
export interface AreaDetail { area: AreaMeta; care_path?: CarePath | null; steps: Step[]; clock_note_en?: string | null; total_method_en?: string;
  mortality_vs_incidence?: { sentence_en?: string; small_numbers?: boolean; source_url?: string | null } | null; consistency_check?: ConsistencyCheck | null;
  gap_checks?: GapCheck[]; gap_checks_overall_en?: string; gap_checks_overall_fi?: string; outside_proof?: OutsideProof | null;
  data_gaps: { what_en: string; why_it_matters_en: string; who_could_publish_en: string }[]; sources: Record<string, SourceRec>; pathway?: Pathway; fixture?: boolean }
export interface Intervention {
  id: string; name_en: string; name_fi: string; step: string; what_en: string; what_fi?: string;
  effect: { metric: string; value: number; lo: number; hi: number; kind?: Kind; basis?: string };
  evidence: { claim: string; quote?: string | null; url?: string | null; year?: number | null; design?: string | null; n?: number | null; verified?: boolean }[];
  null_results?: { claim: string; url?: string | null; year?: number | null }[];
  roadmap_measure?: string | null; owner_fi?: string; owner_en?: string; prerequisite_en?: string | null; confidence: "high" | "medium" | "low";
}
export interface RoadmapMeasure { id: string; title_en?: string; title_fi?: string }
export interface Kpi { label_en?: string; baseline?: number | null; target?: number | null; by_year?: number | null; unit?: string | null; target_rule_en?: string | null; baseline_level?: string | null;
  baseline_period?: string | null; baseline_source_url?: string | null; target_note_en?: string | null; baseline_note_en?: string | null; baseline_kind?: string | null }
/** One measure in an optimiser answer. `shown`, `n` and `group` are set by the server so every screen shows the same rows in the same order. */
export interface Chosen { intervention_id: string; name_en: string; name_fi?: string; area_id: string; area_en?: string; eur: number; eur_setup?: number; eur_running_per_year?: number; cost_kind?: Kind;
  owner_level?: "county" | "collaborative_area" | "national"; owner_en?: string; targets_stage?: string | null;
  extra_curative_patients_per_year: Interval; deaths_avoided_per_year: Interval; eur_per_extra_curative_patient: number | null; eur_per_death_avoided: number | null;
  confidence: string; first_step_en?: string; kpi?: Kpi | null; effect_kind?: Kind; note_en?: string | null; why_first_en?: string | null;
  shown: { extra: number; deaths: number }; study_line_en?: string | null; why_here_en?: string | null; study_line_fi?: string | null; why_here_fi?: string | null; n?: number; group?: string;
  owner_fi?: string; first_step_fi?: string; day90_en?: string; day90_fi?: string }
export interface ExpertReview { scope?: string; quote_en: string; quote_fi?: string; name: string; role?: string; org?: string; date?: string; consent: boolean }
export interface Strip { closes: number | null; of: number | null; pct: number | null; deaths: number | null; spent: number; budget: number; left: number; saturated: boolean; lead_en: string; money_en: string; left_en: string; text_en: string }
export interface CountyShare { n: number; area_id: string; area_en: string; eur: number; extra: number; deaths: number; measures: { intervention_id: string; name_en: string; eur: number; shown: { extra: number; deaths: number } }[] }
export interface OptUi { metric: "extra" | "deaths"; step_zero: string[]; step_zero_title_en: string; groups?: { id: string; title_en: string; ids: string[] }[] | null; national_title_en: string;
  by_county?: CountyShare[] | null; strip: Strip; pilot?: Pilot | null }
export interface Pilot { months: number; actions: string[]; missing?: { intervention_id: string; in_use_here?: string | null; missing_short_en?: string | null }[]; effect: { extra_curative_patients_per_year: Interval; curative_share_now_pct?: number; curative_share_after_pct?: number; by_year?: number; kind?: Kind }; text_en: string; text_fi?: string; six_months: Record<string, any>; ask_first?: { intervention_id: string; question_en: string; question_fi?: string; advice?: string }[]; audit?: { weeks: number; charts: number; cost_eur: number; fields_en: string[]; fields_fi: string[] }; comparison_en?: string; comparison_fi?: string; targets_en?: string; targets_fi?: string; success?: Record<string, any>; cannot_show_en?: string; cannot_show_fi?: string }
export interface OptResult {
  scope: string; scope_en?: string; budget_eur: number; objective: string; objective_note_en?: string | null; objective_en?: string | null; objectives_available?: string[]; excluded?: string[];
  chosen: Chosen[]; needs_national_decision?: Chosen[];
  totals: { eur: number; eur_left: number; extra_curative_patients_per_year: Interval; deaths_avoided_per_year: Interval; curative_share_now_pct?: number | null; curative_share_after_pct?: number | null;
    shortfall_vs_national_per_year?: number | null; gap_closed_pct?: number | null; eur_per_extra_curative_patient?: number | null; eur_per_death_avoided?: number | null; deaths_basis_en?: string;
    patients_per_year?: number | null; interval_en?: string; method_en?: string; shown: { extra: number; deaths: number }; shown_note_en?: string };
  not_chosen: { intervention_id: string; name_en?: string; reason_code?: string; reason_en: string }[]; rules_en?: string[]; saturated?: boolean; saturation_note_en?: string | null;
  goal3_link?: { note_en?: string; lung_deaths_per_year?: number | null; lung_deaths_source_url?: string | null } | null; budget_basis_en?: string; pilot?: Pilot | null; ui: OptUi; fixture?: boolean;
}
export interface Plan {
  title: string; markdown: string; claims: { text: string; source_ids: string[] }[];
  review: { removed: ({ sentence: string; reason: string } | string)[]; flagged?: { sentence: string; reason: string }[]; checked_by: string; error?: string; unknown_source_ids?: string[];
    summary?: { rewritten: number; removed: number; citations_added?: number; reviewed?: boolean } };
  sources?: Record<string, { title?: string; url?: string | null; publisher?: string; retrieved_at?: string | null; verified?: boolean }>;
  generated_at?: string; generated_by?: string; cached?: boolean; fixture?: boolean; fixture_reason?: string; lang?: string; objective?: string; objective_fell_back?: boolean; excluded?: string[];
  nearest?: { budget_eur: number; label_en: string; label_fi: string } | null;
  actions?: { n?: number | null; id: string; name?: string; study_line_en?: string | null; why_here_en?: string | null }[];
  pilot?: Pilot | null; action_studies?: { id: string; study_line_en?: string | null; why_here_en?: string | null }[];
}
/** One step of the live web check, as stored in a result and as sent live while the check runs. */
export interface TraceStep { step?: number | string; round?: number; tool?: string; input?: unknown; why?: string; result_en?: string; ms?: number; error?: boolean | string; status?: string; t_s?: number; from_cache?: boolean; title?: string; endpoint?: string; url?: string | null; model?: string | null; handover?: unknown }
export interface VerifyResult { question?: string; verdict: string; summary_en?: string; sources: { url: string; title?: string; quote?: string; fetched_at?: string; about?: string }[]; checked_at: string; error?: string | null;
  intervention_id?: string; area_id?: string | null; in_use_here?: "yes" | "partly" | "planned" | "no_evidence" | null; in_use_quote?: string | null; in_use_source?: { url?: string; title?: string } | null;
  in_use_scope?: string | null; in_use_summary_en?: string; effect_check?: "supports" | "weaker" | "contradicts" | "not_found" | null; effect_summary_en?: string; unanswered_en?: string;
  plan_effect?: "exclude" | "flag" | "keep" | null; plan_effect_reason_en?: string | null; advice?: "take_out" | "narrow" | "check_first" | "keep" | null;
  in_use_label_en?: string | null; verdict_en?: string | null; effect_label_en?: string | null; supported_en?: string | null; not_supported_en?: string | null; missing_en?: string | null; missing_short_en?: string | null;
  searched_en?: string | null; queries?: string[] | null; endpoints_used?: EndpointUse[] | null; model?: string | null; models?: string[] | null; from_cache?: boolean; live_error?: string | null;
  previous?: { verdict?: string; effect_check?: string; in_use_here?: string; plan_effect?: string; advice?: string; checked_at?: string; model?: string; evidence_n?: number } | null; stability?: string; live_candidate?: { verdict?: string; effect_check?: string; in_use_here?: string; plan_effect?: string; advice?: string; checked_at?: string; model?: string; evidence_n?: number } | null;
  live_outcome?: "first" | "replaced" | "kept" | "failed" | null; live_slow_s?: number | null; live_error_en?: string | null; live_tried_at?: string | null; evidence_n?: number | null; live_trace?: TraceStep[] | null;
  trace?: TraceStep[] | null; rounds?: number | null; searches?: number | null; pages_read?: unknown[] | null; seconds?: number | null }
/** A live run followed by id: the steps from `since` on, and once it has ended the result (or, with nothing stored, a plain reason). */
export interface LiveJob<T> { job_id: string; status: "running" | "done" | "failed"; elapsed_s: number; since: number; next: number; steps: TraceStep[]; result?: T; error_en?: string }
export interface EndpointUse { endpoint?: string; api?: string; calls?: number; failed?: number; why_en?: string; js_render?: number; from_cache?: number }
export interface ScoutFinding { date?: string | null; what_en?: string; relates_to?: string | null; scope?: string | null; title?: string; quote?: string | null; url?: string | null }
export interface ScoutResult { area_id?: string; summary_en?: string; checked_at?: string | null; trace?: TraceStep[] | null; rounds?: number | null; searches?: number | null; pages_read?: unknown[] | null;
  findings?: ScoutFinding[] | null; not_found_en?: string; error?: string | null; live_error?: string | null; live_error_en?: string | null; searched_en?: string | null; endpoints_used?: EndpointUse[] | null; from_cache?: boolean; models?: string[] | null; seconds?: number | null }
export interface ReportRow { indicator_guess?: string; label?: string; label_en?: string; area?: string; value?: number | string; unit?: string; period?: string; page?: number | string; quote?: string; verified?: boolean;
  read_from?: string; value_kind?: string }
export interface ReportResult { document?: { title?: string; url?: string; pages?: number; publisher?: string }; extracted: ReportRow[]; model?: string; cached?: boolean; read_at?: string; notes_en?: string | null; seconds?: number }
export interface KeptRow { area_name?: string; source_title?: string; url?: string; source_url?: string; row_index?: number; label_en?: string; label?: string; value?: number | string; unit?: string; area?: string; period?: string; page?: number | string; quote?: string; added_at?: string; document_title?: string }
export interface ReportJob { job_id: string | null; status: "running" | "done" | "error"; what?: string; elapsed_s: number; result?: ReportResult; error?: string; detail?: string }
export interface ReaderInfo { documents: { url: string; rows: number; verified?: number; pages?: number; indicators?: number; title?: string | null; publisher?: string | null; source_id?: string | null; read_by?: string | null }[]; rows: number;
  pre_read?: { url: string; title?: string | null; values: number; pages?: number | null; in_kello?: number | null }[] }
export interface ChartCheck { how?: string; n: number; mean_abs_error_pp: number; max_abs_error_pp: number }
export interface ChartRead { count: number; rows?: { area_name?: string; label_en?: string; value?: number; unit?: string; period?: string; figure?: string; check?: { second_read?: number; pixel_measure?: number; error_pp?: number } | null }[]; accuracy?: { figure?: string; caption?: string; what?: string; model?: string; rows?: number; source_url?: string; check_a_blind_read_vs_table?: ChartCheck; check_b_county_values_vs_pixel_measure?: ChartCheck; limits?: string; [k: string]: unknown } | null }
export interface ScienceInfo { analyses: { id: string; title: string; finding_en?: string | null; figure_url?: string | null; figure_alt?: string | null; answer_url?: string | null; files: { name: string; url: string; bytes: number }[] }[] }
export interface Status { verify_available?: boolean; reader_available?: boolean; kello_model?: boolean }
export interface SourcesPayload {
  sources: Record<string, SourceRec>;
  evidence: { intervention_id: string; intervention?: string; kind: string; claim?: string; url?: string | null; year?: number | null; verified?: boolean; design?: string | null }[];
  fixture?: boolean; status_help?: { opened?: string; listed?: string };
}

/* ---------- first screen: Goal 3 scoreboard and the county funnel ---------- */
export interface SurvivalTarget { cancer: string; sex: string; finland: number; sweden?: number | null; norway?: number | null; benchmark: number; gap_pp: number; gap_lo?: number | null; gap_hi?: number | null;
  lag_years?: number | null; gap_change_pp_per_decade?: number | null; strategy_target_pp?: number | null; period?: string; source_id?: string; source_url?: string }
export interface MortalityTrend { indicator?: string; unit?: string; baseline_year?: number; baseline_year_stated_in_strategy?: boolean; target_pct?: number; baseline_value?: number; target_value?: number;
  latest?: { year: number; value: number; deaths_n?: number }; change_since_baseline_pct?: number; remaining_pct?: number; target_year?: number; last_10_years?: { from_year: number; to_year: number; rate_change_pct: number; deaths_change_pct: number };
  series?: { year: number; value: number }[]; source_id?: string; source_url?: string; note_en?: string; strategy_quote_fi?: string }
export interface Goal3Row { area_id: string; cancer: string; metric: string; value: number | null; national?: number | null; n?: number | null; small_n?: boolean; note?: string | null }
export interface Goal3 {
  survival_targets: SurvivalTarget[]; survival_method_en?: string | null; survival_sex_note_en?: string; mortality_trend: MortalityTrend;
  county: { metrics: Record<string, { period?: string; unit?: string; source_id?: string; source_url?: string; source_title?: string }>; rows: Goal3Row[]; cancers: string[] };
  treated_within_target?: { available?: boolean; indicator_en?: string; target_en?: string; data_gap_en?: string; who_could_publish_en?: string };
  sources?: Record<string, { title?: string; publisher?: string; url?: string }>; notes_en?: string[];
}
export interface FunnelArea { id: string; short_en: string; n: number; k: number; pct: number; lo: number; hi: number; outside: "none" | "95" | "99.8"; side: "none" | "below" | "above"; page?: number | string | null; quote?: string | null;
  recording_flag?: { stages: string[]; strength: string; text_en: string } | null;
  km_to_university_hospital?: number | null; pop_65plus_pct?: number | null }
export interface Funnel {
  distance?: { n: number; rho: number; p: number; rho_age: number; rho_given_age: number | null; note_en: string } | null;
  label_en: string; definition_en: string; period: string; national: { n: number; k: number; pct: number }; areas: FunnelArea[];
  limits: { n: number; lo95: number; hi95: number; lo998: number; hi998: number }[]; n_areas: number;
  expected_outside_95: number; observed_outside_95: number; expected_outside_998: number; observed_outside_998: number;
  lowest: { id: string; short_en: string; n: number; k: number; per_100: number }; highest: { id: string; short_en: string; n: number; k: number; per_100: number };
  method_en?: string; not_adjusted_en?: string; missing?: string[]; source_url?: string; source_id?: string; page?: number | string | null; read_by?: string | null; quote?: string | null;
}

/* ---------- fixture flag store (drives the "Sample data" badge) ---------- */
const fixtureCalls = new Map<string, boolean>();
const listeners = new Set<() => void>();
let snapshot = "";
function note(key: string, isFixture: boolean) {
  fixtureCalls.set(key, isFixture);
  const next = [...fixtureCalls].filter(([, v]) => v).map(([k]) => k).sort().join(", ");
  if (next !== snapshot) { snapshot = next; listeners.forEach((l) => l()); }
}
export function useFixtureCalls(): string {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => snapshot);
}

/* ---------- fetch ---------- */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
/** Waits between tries of a request that met a network error or a 502/503/504: Wi-Fi drops for a few seconds, a server restarts. */
export const RETRY_MS = [500, 1500, 4000];
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const RETRY_STATUS = new Set([502, 503, 504]);
async function request<T>(path: string, init?: RequestInit, label?: string): Promise<T> {
  let res: Response | null = null;
  for (let i = 0; ; i++) {
    try { res = await fetch(path, init); } catch { res = null; }
    if ((res === null || RETRY_STATUS.has(res.status)) && i < RETRY_MS.length) { await sleep(RETRY_MS[i]); continue; }
    break;
  }
  if (res === null) throw new ApiError("Kello did not answer. Check your connection and try again.", 0);
  let body: any = null;
  try { body = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const d = body?.detail && typeof body.detail === "object" ? body.detail : body;
    const msg = res.status >= 500 && !d?.error ? (res.status === 503 ? "This part of Kello is busy right now. Try again in a minute." : "Something went wrong on our side. Try again.")
      : d?.error ? (typeof d.detail === "string" ? `${d.error}. ${d.detail}` : d.error) : typeof body?.detail === "string" ? body.detail : "That request could not be answered. Try again.";
    throw new ApiError(msg, res.status);
  }
  if (label && body && typeof body === "object") note(label, body.fixture === true);
  return body as T;
}
/** For endpoints an older server may not have: a missing endpoint is "no data", not an error. */
const soft = <T,>(p: Promise<T>): Promise<T | null> => p.catch((e: ApiError) => { if ([404, 405, 501, 503].includes(e.status)) return null; throw e; });
const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let statusOnce: Promise<Status> | null = null;
export interface ArchiveCopy { url: string; copy_url: string | null; captured?: string | null }
let archiveOnce: Promise<{ copies: ArchiveCopy[] }> | null = null;
/** The registry sites ask the browser to pass a check before they show a page. */
export const isRegistry = (u?: string | null) => !!u && /\/\/(?:www\.|tilastot\.)?(?:syoparekisteri|cancerregistry)\.fi/.test(u);
/** The saved copy of a cited page, if the archive holds one. */
export function savedCopy(url: string | null | undefined, copies: ArchiveCopy[] | undefined): ArchiveCopy | null {
  if (!url || !copies) return null;
  const bare = (x: string) => x.replace(/#.*$/, "");
  return copies.find((c) => c.copy_url && bare(c.url) === bare(url)) ?? null;
}
/** A request that failed in a way the reader can act on: plain words, no addresses. */
export const friendly = (e: unknown): string => {
  const err = e as ApiError;
  if (err?.status === 0) return "Kello did not answer. Check your connection and try again.";
  if (err?.status === 503 || err?.status === 429) return "This part of Kello is busy right now. Try again in a minute.";
  if (err?.status >= 500) return "Something went wrong on our side. Try again.";
  return err?.message || "Something went wrong. Try again.";
};
let expertOnce: Promise<{ reviews: ExpertReview[] }> | null = null;
export const api = {
  overview: () => request<Overview>("/api/overview", undefined, "map"),
  geo: () => request<GeoJSON.FeatureCollection>("/api/geo"),
  area: (id: string) => request<AreaDetail>(`/api/areas/${id}`, undefined, "pathway"),
  interventions: () => request<{ interventions: Intervention[]; roadmap_measures: RoadmapMeasure[]; fixture?: boolean }>("/api/interventions", undefined, "actions"),
  optimize: (scope: string, budget_eur: number, objective?: string | null, exclude?: string[]) =>
    request<OptResult>("/api/optimize", post({ scope, budget_eur, ...(objective ? { objective } : {}), ...(exclude?.length ? { exclude } : {}) }), "budget"),
  goal3: () => soft(request<Goal3>("/api/goal3")),
  funnel: () => soft(request<Funnel>("/api/funnel")),
  sources: () => request<SourcesPayload>("/api/sources", undefined, "sources"),
  /** Latest stored check per measure for an area. */
  verifyLatest: (area_id: string) => soft(request<{ checks?: VerifyResult[] }>(`/api/verify/latest?area_id=${encodeURIComponent(area_id)}`)).then((r) => r?.checks ?? [], () => [] as VerifyResult[]),
  scoutLatest: (area_id: string) => soft(request<ScoutResult>(`/api/scout/latest?area_id=${encodeURIComponent(area_id)}`)).catch(() => null),
  readKeep: (url: string, row_index: number) => request<{ added?: boolean; already?: boolean; count?: number }>("/api/read-report/keep", post({ url, row_index })),
  readKept: () => soft(request<{ count: number; rows: KeptRow[] }>("/api/read-report/kept")).catch(() => null),
  readCharts: () => soft(request<ChartRead>("/api/read-report/charts")).catch(() => null),
  readStartUrl: (url: string) => request<ReportJob>("/api/read-report/start", post({ url })),
  readStartFile: (file: File) => { const fd = new FormData(); fd.append("file", file); return request<ReportJob>("/api/read-report/start", { method: "POST", body: fd }); },
  readJob: (id: string) => request<ReportJob>(`/api/read-report/job/${id}`),
  reader: () => request<ReaderInfo>("/api/reader"),
  science: () => request<ScienceInfo>("/api/science"),
  status: () => (statusOnce ??= request<Status>("/api/status").catch(() => ({} as Status))),
  areas: () => request<AreaMeta[]>("/api/areas"),
  /** Words of a named expert who has looked at a plan; empty until someone has agreed to be quoted. */
  expertReview: () => (expertOnce ??= request<{ reviews: ExpertReview[] }>("/api/expert-review").catch(() => { expertOnce = null; return { reviews: [] as ExpertReview[] }; })),
  /** Existing archive copies of the registry pages Kello cites; looked up once on the server. */
  archive: () => (archiveOnce ??= request<{ copies: ArchiveCopy[] }>("/api/archive").catch(() => { archiveOnce = null; return { copies: [] as ArchiveCopy[] }; })),
  /** Live runs (web check, scout) are jobs on the server: start or join one, then follow it by id. */
  verifyStart: (intervention_id: string, area_id: string) => request<LiveJob<VerifyResult>>("/api/verify/start", post({ intervention_id, area_id })),
  scoutStart: (area_id: string) => request<LiveJob<ScoutResult>>("/api/scout/start", post({ area_id })),
  liveJob: <T,>(id: string, since: number) => request<LiveJob<T>>(`/api/live/${id}?since=${since}`),
  notePlan: (isFixture: boolean) => note("plan", isFixture),
};

/* ---------- async state hook ---------- */
export interface Async<T> { data: T | null; error: string | null; loading: boolean; reload: () => void }
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => { if (my === seq.current) setState({ data, error: null, loading: false }); },
      (e) => { if (my === seq.current) setState({ data: null, error: friendly(e), loading: false }); },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

/* ---------- formatting: one place, so numbers read the same everywhere ---------- */
const nf0 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const days = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "–" : nf0.format(Math.round(n)));
export const range = (lo: number, hi: number, f: (n: number) => string = days) => `${f(lo)}–${f(hi)}`;
export const one = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "–" : nf1.format(n));
export const int = (n: number | null | undefined) => (n == null ? "–" : nf0.format(n));
export function eur(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "–";
  if (Math.abs(n) >= 1e6) return `€${(n / 1e6).toFixed(n % 1e6 === 0 ? 0 : n >= 1e7 ? 1 : 2).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "")}M`;
  if (Math.abs(n) >= 1e3) return `€${nf0.format(Math.round(n / 1e3))}k`;
  return `€${nf0.format(n)}`;
}
/** Exact euros below a million, as the optimiser counts them: €211,500. Millions are short: €1M, €1.42M. */
export function eurx(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "–";
  // From a million up, money is shown to three figures at most: €1.42M, €17.4M, never €1,418,060.
  return Math.abs(n) >= 1e6 ? eur(n) : `€${nf0.format(Math.round(n))}`;
}
/** Millions in server-written text read like the rest of the page: €1,418,060 -> €1.42M. */
/** A cost per patient or per death rests on an estimated effect, so it is said in thousands. */
export const eurAbout = (n: number | null | undefined) => (n == null ? "–" : `about ${eurx(Math.round(n / 1000) * 1000)}`);
export const plainMoney = (t?: string | null) => (t ?? "").replace(/€(\d{1,3}(?:,\d{3}){2,})(?![\d,])/g, (_m, d: string) => eurx(Number(d.replace(/,/g, ""))));
/** A range in the same decimals as its point: 0–7.7 */
export const rng1 = (lo: number, hi: number) => {
  const fmt = (n: number) => {
    const x = +n.toFixed(1);
    return x === 0 ? "0" : String(Math.abs(x));
  };
  return `${lo < 0 && +lo.toFixed(1) !== 0 ? "−" : ""}${fmt(lo)}${lo < 0 ? " to " : "–"}${hi < 0 ? "−" : ""}${fmt(hi)}`;
};
export function value(n: number | null | undefined, unit?: string): string {
  if (n == null) return "–";
  const s = Math.abs(n) >= 100 || Number.isInteger(n) ? nf0.format(n) : nf1.format(n);
  if (!unit) return s;
  return unit === "%" ? `${s}%` : `${s} ${unit}`;
}
export const STEP_SHORT: Record<string, string> = { patient: "Patient", primary: "Primary care", referral: "Referral", diagnosis: "Diagnosis", treatment: "Treatment" };
export const STEP_LONG: Record<string, string> = {
  patient: "First symptom to first primary care contact", primary: "Primary care contact to referral", referral: "Referral to first specialist visit",
  diagnosis: "First specialist visit to diagnosis", treatment: "Diagnosis to treatment start",
};
export const KIND_LABEL: Record<Kind, string> = { measured: "Measured", estimated: "Estimated", assumption: "Assumption" };
export const KIND_HELP: Record<Kind, string> = {
  measured: "Taken directly from a public source", estimated: "Produced by the model, shown with an interval", assumption: "Set by hand where no data exists; editable",
};
export function when(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function whenFi(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fi-FI", { day: "numeric", month: "numeric", year: "numeric" });
}
/** Finnish number style for the plan text: decimal comma, thousands space. Citation markers, dates and URLs are left alone. */
export function fiNumbers(text: string): string {
  return text.split(/(\[\^[^\]\s]+\]|https?:\/\/\S+|\b\d{1,2}\.\d{1,2}\.\d{4}\b)/g).map((part, i) => (i % 2 ? part
    : part.replace(/(\d),(?=\d{3}(\D|$))/g, "$1\u00a0").replace(/(?<![\d.])(\d+)\.(\d+)(?!\.?\d)/g, "$1,$2").replace(/\bEUR\s?([\d\u00a0,]+)/g, "$1\u00a0€"))).join("");
}
export function eurFi(n: number): string {
  if (Math.abs(n) >= 1e6) return `${String(+(n / 1e6).toFixed(Math.abs(n) >= 1e7 ? 1 : 2)).replace(".", ",")} milj. €`;
  return `${new Intl.NumberFormat("fi-FI", { maximumFractionDigits: 0 }).format(n)} €`;
}
export function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

/* ---------- provenance: one reference shape for every number, one chip, one drawer ---------- */
export interface SrcRef { kind: Kind | "reported"; source_id?: string | null; source_url?: string | null; page?: number | string | null; read_by?: string | null; period?: string | null; quote?: string | null;
  publisher?: string | null; what?: string | null; value?: string | null; note?: string | null;
  /** Chip text when the standard one would mislead, e.g. "By subtraction". */
  label?: string | null }
export function openSource(ref: SrcRef | null) { window.dispatchEvent(new CustomEvent("kello:source", { detail: ref })); }
const HOSTS: [RegExp, string][] = [[/syoparekisteri|cancerregistry/, "Cancer Registry"], [/ihe\.se/, "IHE"], [/yle\.fi/, "Yle"], [/nordcan|iarc/, "NORDCAN"], [/sotkanet|thl\.fi/, "THL"], [/stat\.fi/, "Statistics Finland"], [/kela\.fi/, "Kela"]];
const IDS: [RegExp, string][] = [[/^fcr_/, "Cancer Registry"], [/^(sotkanet|thl)_/, "THL"], [/^statfin_/, "Statistics Finland"], [/^nordcan_/, "NORDCAN"], [/^kela_/, "Kela"], [/^model$/, "model"]];
export function publisherOf(r: Pick<SrcRef, "publisher" | "source_url" | "source_id">): string | null {
  if (r.publisher) return r.publisher;
  const u = r.source_url ?? (r.source_id?.startsWith("http") ? r.source_id : null);
  if (u) { const hit = HOSTS.find(([re]) => re.test(u)); if (hit) return hit[1]; try { return new URL(u).hostname.replace(/^www\./, ""); } catch { /* not a URL */ } }
  if (r.source_id) { const hit = IDS.find(([re]) => re.test(r.source_id!)); if (hit) return hit[1]; }
  return null;
}
/** "2019-2023" -> "2019–2023"; "1.1.2018-30.6.2022" -> "2018–mid 2022". */
export function period(p?: string | null): string {
  if (!p) return "";
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})\s*[-–]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(p.trim());
  if (m) return `${m[3]}–${m[5] === "6" || m[5] === "7" ? "mid " : ""}${m[6]}`;
  return p.replace(/(\d{4})\s*-\s*(\d{4})/, "$1–$2");
}
export const readerName = (rb?: string | null) => (rb ? (/gemini/i.test(rb) ? "Gemini" : rb.split(":")[0]) : null);
export function chipText(r: SrcRef): string {
  if (r.label) return r.label;
  if (r.kind === "assumption") return "Assumption";
  if (r.kind === "estimated") return "Estimated · model";
  const head = r.kind === "reported" ? "Reported" : "Measured";
  const pub = publisherOf(r);
  const parts = [head, [pub, period(r.period)].filter(Boolean).join(" ")];
  if (r.page != null && r.page !== "") parts.push(`p. ${r.page}`);
  if (r.read_by) parts.push(`read by ${readerName(r.read_by)}`);
  return parts.filter(Boolean).join(" · ");
}
/** Measured values keep the precision they were published with. */
export function mval(n: number | null | undefined, unit?: string): string {
  if (n == null || Number.isNaN(n)) return "–";
  const s = Number.isInteger(n) && unit !== "%" ? nf0.format(n) : nf1.format(n);
  return unit === "%" ? `${s}%` : s;
}
export const lowerIsBetter = (direction?: string | null, key = "") => (direction ? /^lower/.test(direction) : /no_treatment|days|wait|deaths|queue/.test(key));
