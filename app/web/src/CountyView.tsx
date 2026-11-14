import { StudyLine } from "./StudyLine";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, AreaDetail, AreaMeta, CarePath, Chosen, days, eurAbout, eurx, Intervention, KIND_LABEL, one, OptResult, period, plainMoney, range, rng1, ScoutFinding, ScoutResult, SrcRef, Stage, useAsync, VerifyResult, when } from "./lib";
import { Failed, Skeleton } from "./App";
import { SourceChip } from "./Source";
import GapChecks from "./GapChecks";
import { PilotAsk } from "./Pilot";
import Pathway, { DrugFinding } from "./Pathway";
import ExpertQuote from "./ExpertQuote";
import { Col, Dots } from "./Dots";
import { Finding, host, inUseWord, IN_USE_SHORT, LiveOutcome, movesOut, Scout, stepLabel, useLiveRun, WebCheckResult, adviceWord, checkCount } from "./WebCheck";

/* The county page tells one story: where this county loses lung cancer patients between diagnosis and treatment
   that aims to cure, and what closes that gap. Every number on it comes from the API. */

interface Props { scope: string; budget: number; setBudget: (n: number) => void; objective: string | null; setObjective: (o: string | null) => void;
  without: string[]; setWithout: (ids: string[]) => void; areas: AreaMeta[]; openPlan: () => void; openMonday: () => void; pick: (id: string) => void }

const PRESETS = [250_000, 500_000, 1_000_000, 2_000_000];
const OBJECTIVES: [string, string][] = [["curative", "Most patients treated to cure"], ["gap", "Close the gap to Finland"], ["deaths", "Most deaths avoided"]];
const KEY_STAGES = ["curative", "surgery", "no_record"];
const sval = (s: Stage, v: number | null | undefined = s.value) => (v == null ? "–" : s.unit === "days" ? `${one(v)} days` : `${one(v)}%`);
const stageRef = (s: Stage, where: string): SrcRef => ({ kind: s.kind === "estimated" ? "estimated" : "measured", source_url: s.source_url, page: s.page, read_by: s.read_by, period: s.period, quote: s.quote,
  what: `${s.label_en}, ${where}`, value: sval(s), note: s.note_en });
/** The clock check in plain words: the statistics stay in Sources & method. */
const plainCheck = (t: string) => t.replace(/\s*\((?:rho|n )[^;)]*(?:;\s*([^)]*))?\)/, (_m, tail) => (tail ? ` (${tail})` : ""));
const dayOf = (iso: string) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); };
/** The model writes "EUR 211,500"; the page writes euros one way. */
const euro = (t?: string | null) => (t ?? "").replace(/\bEUR\s(?=\d)/g, "€").replace(/are listed as poor_value under not_chosen/g, "are listed below under “Not in the plan, and why”");
/** University hospital areas by their city, not their acronym. */
const YTA: Record<string, string> = { HUS: "Helsinki university hospital", TYKS: "Turku university hospital", TAYS: "Tampere university hospital", KYS: "Kuopio university hospital", OYS: "Oulu university hospital" };
export const plainWords = (t?: string | null) => (t ?? "").replace(/\(university hospital\)/gi, "").replace(/the collaborative area/gi, "the university hospital area").replace(/collaborative area/gi, "university hospital area").replace(/\bOYS\b/g, "Oulu university hospital").replace(/\boptimiser\b/gi, "model").replace(/budget ceiling/gi, "budget").replace(/poor_value/gi, "below the value-for-money threshold").replace(/\s{2,}/g, " ").trim();
const lower = (t: string) => (t && !/^[A-Z]{2}/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);

/** How a stage compares with Finland, in words. "Beyond chance" = outside the limits chance gives a county of this size. */
function reading(s: Stage): { word: string; tone: "bad" | "good" | "plain" } {
  if (s.level === "collaborative_area") return { word: "Published for the university hospital area, not the county", tone: "plain" };
  if (s.id === "surgery") {
    // The registry publishes the operated share by sex with a 95% range: say for whom the whole range is below Finland.
    const ci = s.registry_ci, below = (["men", "women"] as const).filter((k) => ci?.[k] && ci[k]!.hi < ci[k]!.national_pct);
    const lowerThan = s.value != null && s.national != null && s.value < s.national;
    if (!ci?.men || !ci?.women) return { word: lowerThan ? "Lower than Finland; a small count, so this step alone could be chance" : "Not lower than Finland", tone: "plain" };
    if (below.length === 2) return { word: "Lower than Finland for men and women, beyond chance by the registry's age-adjusted ranges", tone: "bad" };
    if (below.length === 1) return { word: `Lower than Finland; by the registry's age-adjusted ranges beyond chance for ${below[0]}, not for ${below[0] === "men" ? "women" : "men"}`, tone: "plain" };
    return { word: lowerThan ? "Lower than Finland, but the registry's age-adjusted ranges reach Finland's figure: this step alone could be chance" : "Not lower than Finland", tone: "plain" };
  }
  // No interval was published for this figure, so chance cannot be judged: say only which way it differs.
  if (s.lo == null && s.hi == null && s.value != null && s.national != null && (!s.outside_limits || s.outside_limits === "none")) {
    const d = s.value - s.national;
    return { word: Math.abs(d) < 3 ? "Close to Finland" : `${d > 0 ? "Higher" : "Lower"} than Finland; no count is published, so chance cannot be judged`, tone: "plain" };
  }
  if (!s.outside_limits || s.outside_limits === "none" || !s.side) return { word: "Not different from Finland beyond chance", tone: "plain" };
  const word = `${s.side === "below" ? "Lower" : "Higher"} than Finland, beyond chance`;
  if (s.direction === "context") return { word, tone: "plain" };
  const worse = (s.direction === "higher_better") === (s.side === "below");
  return { word, tone: worse ? "bad" : "good" };
}

/* ---------- the missing patients as one bar that adds up ---------- */
function MissingBar({ parts, total, closes, on }: { parts: { label: string; n: number; cls: string; chip?: SrcRef }[]; total: number; closes: number | null; on: boolean }) {
  const plan = closes != null && closes > 0;
  return (
    <div className="missbar">
      <div className="bar" role="img" aria-label={`${one(total)} patients a year: ${parts.map((p) => `${p.label} ${one(p.n)}`).join(", ")}`}>
        {parts.map((p) => <div key={p.label} className={p.cls} style={{ flexGrow: Math.max(p.n, 0.01) }}><b className="num">{one(p.n)}</b></div>)}
      </div>
      {plan && <div className="closes" aria-hidden="true"><i style={{ width: `${on ? Math.min(100, (closes / total) * 100) : 0}%` }} /></div>}
      <ul className="keys">
        {parts.map((p) => <li key={p.label}><i className={p.cls} /><span><b className="num">{one(p.n)}</b> {p.label}</span>{p.chip && <SourceChip s={p.chip} short />}</li>)}
        {plan && <li className={"closed" + (on ? " on" : "")}><i className="s-gain" /><span>This plan is modelled to close <b className="num">{one(closes)}</b> of {one(total)}</span></li>}
      </ul>
    </div>
  );
}

/* ---------- one stage row ---------- */
function StageRow({ s, where, flag, best = true, own = false }: { s: Stage; where: string; flag?: string; best?: boolean; own?: boolean }) {
  const r = reading(s);
  return (
    <div className="gaprow srow" data-stage={s.id}>
      <div className="sl"><b>{s.label_en}</b>{s.period && <small className="num">{period(s.period)}</small>}</div>
      <div className="sv num"><b>{sval(s)}</b>{s.lo != null && s.hi != null && <small>95% interval {rng1(s.lo, s.hi)}</small>}</div>
      {/* For Finland as a whole there is nothing to compare the national figure with. */}
      <div className="sc num">{!own && <span><small>Finland</small>{sval(s, s.national)}</span>}{best && s.best != null && s.direction !== "context" && <span><small>Best: {s.best_area_en}</small>{sval(s, s.best)}</span>}</div>
      <div className={`rd ${r.tone}`}>{own ? "" : r.word}</div>
      <div className="sx"><SourceChip s={stageRef(s, where)} short /></div>
      {flag && <p className="flag"><b>Recording caveat.</b> {flag}</p>}
    </div>
  );
}

export default function CountyView({ scope, budget, setBudget, objective, setObjective, without, setWithout, areas, openPlan, openMonday, pick }: Props) {
  const isFI = scope === "FI";
  const area = useAsync(() => api.area(scope), [scope]);
  const ivs = useAsync(api.interventions, []);
  const key = without.join(",");
  const opt = useAsync(() => api.optimize(scope, budget, objective, without), [scope, budget, objective, key]);
  // The same question without anything left out: what each left-out measure cost, and what each objective would buy.
  const alts = useAsync(() => Promise.all([null, ...OBJECTIVES.map(([o]) => o)].map((o) => api.optimize(scope, budget, o))), [scope, budget]);
  const stored = useAsync(() => api.verifyLatest(scope), [scope]);
  const scout = useAsync(() => (isFI ? Promise.resolve(null) : api.scoutLatest(scope)), [scope]);
  const [scoutNew, setScoutNew] = useState<ScoutResult | null>(null);
  const [live, setLive] = useState<Record<string, VerifyResult>>({});
  const [planOn, setPlanOn] = useState(false);

  const cp: CarePath | null = area.data?.care_path ?? null;
  const stages = useMemo(() => new Map((cp?.stages ?? []).map((s) => [s.id, s])), [cp]);
  const cur = stages.get("curative");
  // Reference columns of the dot chart: the best county, and for the national page also the lowest one.
  const bestId = cur?.best_area ?? null;
  const lowId = isFI ? areas.find((a) => a.short_en === cur?.worst_area_en)?.id ?? null : null;
  const best = useAsync(() => (bestId && bestId !== scope ? api.area(bestId) : Promise.resolve(null)), [bestId, scope]);
  const low = useAsync(() => (lowId ? api.area(lowId) : Promise.resolve(null)), [lowId]);

  // The dots open on Today; the reader switches the plan on and sees the patients it moves.
  useEffect(() => { setPlanOn(false); }, [scope]);
  // #/reset/demo opens this page on the action whose web check it put aside (see main.tsx).
  const planReady = !!opt.data;
  useEffect(() => {
    if (!planReady) return;
    let id: string | null = null;
    try { id = sessionStorage.getItem("kello-focus"); sessionStorage.removeItem("kello-focus"); } catch { /* private window */ }
    if (id) window.setTimeout(() => document.getElementById(id!)?.scrollIntoView({ block: "center" }), 150);
  }, [planReady]);

  const meta = area.data?.area ?? areas.find((a) => a.id === scope);
  const name = isFI ? "Finland" : meta?.short_en ?? scope;

  if (area.error) return <div className="page"><Failed message={/unknown area/i.test(area.error) ? "There is no county with that code. Choose one from the list at the top of the page." : area.error} retry={/unknown area/i.test(area.error) ? undefined : area.reload} /></div>;
  // The skeleton has the page's own shape: two headline lines, the summary line, the care-path panel, the actions panel.
  if (!area.data) return (
    <div className="page county" role="status" aria-label="Loading the county">
      <div className="pagehead"><div className="phmain"><Skeleton label="" rows={[[28, 86], [28, 70], [15, 58], [15, 44]]} /></div><div className="skeleton" style={{ width: 190, height: 40 }} /></div>
      <div className="strip"><Skeleton label="" rows={[[20, 64]]} /></div>
      <div className="panel skbox"><Skeleton label="" rows={[[20, 44]]} /><div className="skcols"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div><Skeleton label="" rows={[36, 36, 36]} /></div>
      <div className="panel skbox"><Skeleton label="" rows={[[20, 36], [20, 70], 64, 64, 64]} /></div>
    </div>
  );
  const d: AreaDetail = area.data;
  const o: OptResult | null = opt.data;
  const ui = o?.ui;
  const t = o?.totals;
  const checks: Record<string, VerifyResult> = { ...Object.fromEntries((stored.data ?? []).map((v) => [v.intervention_id ?? "", v])), ...live };
  const byIv = new Map((ivs.data?.interventions ?? []).map((i) => [i.id, i]));
  const base = alts.data?.[objective ? 1 + OBJECTIVES.findIndex(([x]) => x === objective) : 0] ?? null;
  const defaultObjective = alts.data?.[0]?.objective ?? null;
  const flags = new Map((cp?.artefact_flags ?? []).map((f) => [f.stage_id, f.text_en]));
  const mp = cp?.missing_patients ?? null;
  const leak = cp?.main_leak ?? null;
  const short = mp?.per_year ?? 0;
  const ttt = stages.get("time_to_treatment");
  const curBelow = !!cur && cur.side === "below" && !!cur.outside_limits && cur.outside_limits !== "none";
  const waitLine = !isFI && curBelow && ttt?.value != null && ttt.national != null && ttt.value <= ttt.national;
  const scoutData = scoutNew ?? scout.data ?? null;
  const findings: ScoutFinding[] = scoutData?.findings ?? [];
  const bears = (id?: string | null) => (id ? byIv.get(id)?.name_en ?? stages.get(id)?.label_en ?? null : null);

  /* dot columns */
  const gain = t && ui?.metric === "extra" && t.curative_share_now_pct != null && t.curative_share_after_pct != null ? Math.max(0, t.curative_share_after_pct - t.curative_share_now_pct) : 0;
  const sur = stages.get("surgery");
  const stageOf = (a: AreaDetail | null, id: string) => a?.care_path?.stages.find((s) => s.id === id)?.value ?? null;
  const cols: Col[] = !cur || cur.value == null ? [] : isFI ? [
    { name: "Finland", cure: cur.value, op: sur?.value ?? null, gain, main: true },
    ...(cur.worst != null ? [{ name: cur.worst_area_en ?? "Lowest county", note: "lowest county", cure: cur.worst, op: stageOf(low.data, "surgery"), gain: 0 }] : []),
    ...(cur.best != null ? [{ name: cur.best_area_en ?? "Highest county", note: "highest county", cure: cur.best, op: stageOf(best.data, "surgery"), gain: 0 }] : []),
  ] : [
    { name, cure: cur.value, op: sur?.value ?? null, gain, main: true },
    ...(cur.national != null ? [{ name: "Finland", cure: cur.national, op: sur?.national ?? null, gain: 0 }] : []),
    ...(cur.best != null && bestId !== scope ? [{ name: cur.best_area_en ?? "Best county", note: "best county", cure: cur.best, op: stageOf(best.data, "surgery"), gain: 0 }] : []),
  ];

  /* the missing patients, split so the parts add up to the total */
  const MOD: Record<string, [string, string]> = { surgery: ["not operated", "m-op"], radiotherapy: ["not given radiotherapy that aims to cure", "m-ot"] };
  const missParts = !mp || short <= 0 ? [] : mp.by_modality.length ? mp.by_modality.map((m) => ({ label: MOD[m.id]?.[0] ?? m.id, n: m.per_year, cls: MOD[m.id]?.[1] ?? "m-ot",
    chip: m.id === "surgery" && sur ? { ...stageRef(sur, name), note: m.note_en } : { kind: "estimated" as const, label: "By subtraction, not measured", what: `Patients a year ${MOD[m.id]?.[0] ?? m.id}, ${name}`, value: one(m.per_year), note: m.note_en } }))
    : mp.per_year_in_counties_below_limits != null ? [
      { label: `in the ${mp.counties_below_limits_en?.length ?? ""} counties below Finland beyond chance`, n: mp.per_year_in_counties_below_limits, cls: "m-op" },
      { label: "in other counties below the national share", n: +(short - mp.per_year_in_counties_below_limits).toFixed(1), cls: "m-ot" }]
    : [{ label: "patients a year", n: short, cls: "m-op" }];

  /* actions */
  const chosen = o?.chosen ?? [];
  const metric = ui?.metric ?? "extra";
  const showExtra = chosen.some((c) => c.shown.extra > 0);
  const showDeaths = chosen.some((c) => c.shown.deaths > 0);
  const zero = chosen.filter((c) => c.group === "step_zero");
  const baseRow = (id: string) => base?.chosen.find((c) => c.intervention_id === id) ?? null;
  const inPlace = without.filter((id) => checks[id] && (movesOut(checks[id]) || checks[id].in_use_here === "yes"));
  const off = without.filter((id) => !inPlace.includes(id));
  const drop = (id: string) => setWithout([...without.filter((x) => x !== id), id]);
  const putBack = (id: string) => setWithout(without.filter((x) => x !== id));
  const onCheck = (id: string, v: VerifyResult) => {
    setLive((p) => ({ ...p, [id]: v }));
    // A check that finds the measure already in place takes it out of the plan: its euros are freed and the totals follow.
    if (movesOut(v) && chosen.some((c) => c.intervention_id === id)) drop(id);
    // A run that replaced an "already in place" answer with a weaker one puts the line back.
    else if (!movesOut(v) && v.live_outcome === "replaced" && v.previous?.plan_effect === "exclude" && without.includes(id)) putBack(id);
  };
  const linked = new Set([...chosen.map((c) => c.intervention_id), ...(o?.needs_national_decision ?? []).map((c) => c.intervention_id)]);
  // The stage named as the reason on a card must be one where this county is behind Finland; otherwise the share treated to cure, or nothing.
  const behind = (st?: Stage) => !!st && st.value != null && st.national != null && (st.direction === "lower_better" ? st.value > st.national : st.value < st.national);
  const reasonStage = (id?: string | null) => { const st = id ? stages.get(id) : undefined; const cure = stages.get("curative"); return behind(st) ? st : behind(cure) ? cure : undefined; };
  const cardProps = (c: Chosen) => ({ c, iv: byIv.get(c.intervention_id), stage: reasonStage(c.targets_stage), name, areaId: scope, metric, showExtra, showDeaths,
    check: checks[c.intervention_id], fresh: !!live[c.intervention_id], onCheck: (v: VerifyResult) => onCheck(c.intervention_id, v), onDrop: () => drop(c.intervention_id),
    findings: findings.filter((f) => f.relates_to === c.intervention_id), roadmap: ivs.data?.roadmap_measures ?? [] });
  const nothing = !!o && chosen.length === 0;
  // The count covers the whole plan as it stood before any check took a line out.
  const checked = checkCount([...chosen.map((c) => c.intervention_id), ...inPlace], checks);

  // One headline of at most two sentences; a longer sentence from the model continues below it at reading size.
  const full = leak?.sentence_en ?? (cp?.stages.length ? name : `${name}: too few patients to compare`);
  const parts = full.length > 150 ? full.split(/(?<=\.)\s+(?=[A-ZÅÄÖ])/) : [];
  const headline = parts.length > 2 ? parts.slice(0, 2).join(" ") : full;
  const headRest = parts.length > 2 ? parts.slice(2).join(" ") : "";
  return (
    <div className="page county">
      <div className="pagehead">
        <div className="phmain">
          <h1>{headline}</h1>
          {headRest && <p className="phlead">{headRest}</p>}
          <p className="phsub">{isFI ? "Finland, all wellbeing services counties" : meta?.name_en ?? name}{cp?.patients_per_year ? `, ${Math.round(cp.patients_per_year).toLocaleString("en-GB")} new lung cancer patients a year.` : "."}
            {!cp?.stages.length && cp?.note_en && <> {cp.note_en}</>}
          </p>
          <ExpertQuote scope={scope} />
        </div>
        <button className="btn primary lg" onClick={openPlan}>Open the plan</button>
      </div>

      {cp && cp.stages.length > 0 && cur && (
        <section className="panel care" aria-label="Care path" id="sec-gap">
          <header>
            <h2>Of 100 lung cancer patients, how many are treated to cure?</h2>
            <SourceChip s={stageRef(cur, name)} />
            <div className="spacer" />
            {gain > 0 && (
              <div className="seg" role="group" aria-label="Show the plan">
                <button aria-pressed={!planOn} onClick={() => setPlanOn(false)}>Today</button>
                <button aria-pressed={planOn} onClick={() => setPlanOn(true)}>With the plan</button>
              </div>
            )}
          </header>
          <div className="carebody">
            <div className="dotwrap">
              <div className="dotcols">{cols.map((c) => <Dots key={c.name} col={c} on={planOn} />)}</div>
              <ul className="dotkey">
                {cols.some((c) => c.op != null) && <li><i className="s-op" />Operated</li>}
                {cols.some((c) => c.op != null) && <li><i className="s-ot" />Radiotherapy or other treatment that aims to cure</li>}
                {cols.some((c) => c.op == null) && <li><i className="s-cure" />Treated to cure (the split by operation is not published for every column)</li>}
                {gain > 0 && <li><i className="s-gain" />Moved by this plan (modelled, {one(gain)} of 100)</li>}
                <li><i className="s-no" />Not treated to cure</li>
              </ul>
            </div>

            <div className="missing">
              {short > 0 && mp ? (
                <>
                  <h3><span className="big num">{one(short)}</span> patients a year are missing from treatment that aims to cure{isFI ? ", summed over the counties below the national share" : ", compared with Finland"}{mp.lo != null && mp.hi != null ? <span className="muted num"> ({rng1(mp.lo, mp.hi)})</span> : null}</h3>
                  <MissingBar parts={missParts} total={short} closes={ui?.strip.closes ?? null} on={planOn} />
                </>
              ) : (
                <>
                  <h3>No shortfall against Finland</h3>
                  <p>{name} treats at least as large a share to cure as the country as a whole, so there are no missing patients to count here. Use this page to see what {name} does more of (the stages below){o?.objective === "deaths" ? ", and the plan further down, which is ranked by deaths avoided instead" : ""}.</p>
                </>
              )}
            </div>
          </div>

          <div id="sec-why" className="anchor gapline incare"><GapChecks areaId={scope} variant="line" /></div>

        </section>
      )}

      {!(cp && cp.stages.length > 0 && cur) && <div id="sec-why" className="anchor gapline"><GapChecks areaId={scope} variant="line" /></div>}

      {scope !== "FI" && <Pathway pathway={d.pathway} where={name} drug={false} />}

      <section className="panel acts" aria-label="Budget and actions" id="sec-plan">
        <header>
          <h2>{nothing ? `What ${name} can do` : metric === "extra" ? (short > 0 || isFI ? `What closes the gap in ${name}, in order` : `What ${name} could still do, in order`) : `What the plan buys in ${name}, in order`}</h2>
          <div className="spacer" />
          <button className="btn sm" onClick={openMonday}>Who does what on Monday</button>
          <button className="btn sm" onClick={openPlan}>Open the plan</button>
        </header>
        {opt.error ? <Failed message={opt.error} retry={opt.reload} /> : !o || !ui || !t ? <div className="body"><Skeleton rows={[40, 150, 150, 150]} label="Choosing the actions" /></div> : (
          <div className={opt.loading ? "busy" : ""}>
            <div className="totals">
              <div className="strip" role="note" aria-label="The plan in one line">
                <b>{plainMoney(ui.strip.lead_en)}</b><span className="num">{plainMoney(ui.strip.money_en)} a year</span><span className="num">{plainMoney(ui.strip.left_en)}</span>
                {checked && <span className="webline" key={checked}>{checked}</span>}
              </div>
              {nothing && <p className="lede">No measure adds to this objective in {name} at this budget. {euro(o.saturation_note_en)}</p>}
            </div>
            <details className="more tune">
              <summary>Budget, ranking and what the plan adds <span className="muted num">{eurx(budget)} a year, ranked by {({ curative: "patients treated to cure", gap: "how much of the gap to Finland it closes", deaths: "deaths avoided" } as Record<string, string>)[o.objective ?? ""] ?? "patients treated to cure"}</span></summary>
            <div className="totals inner">
              {!nothing && (
                <p className="lede">
                  <b>{chosen.length} action{chosen.length === 1 ? "" : "s"}{isFI ? ` in ${ui.by_county?.length ?? 0} counties` : ""}, {eurx(t.eur)} a year</b>:{" "}
                  {metric === "extra" ? <><b>{one(t.shown.extra)}</b> more patients a year treated to cure <span className="muted">({rng1(t.extra_curative_patients_per_year.lo, t.extra_curative_patients_per_year.hi)})</span>{t.eur_per_extra_curative_patient ? <>, {eurAbout(t.eur_per_extra_curative_patient)} per extra patient</> : null}.</>
                    : <>about <b>{one(t.shown.deaths)}</b> deaths avoided a year <span className="muted">({rng1(t.deaths_avoided_per_year.lo, t.deaths_avoided_per_year.hi)}, modelled)</span>{t.eur_per_death_avoided ? <>, {eurAbout(t.eur_per_death_avoided)} per death avoided</> : null}.</>}
                  {" "}<SourceChip s={{ kind: "estimated", what: `What the plan adds, ${name}`, note: t.interval_en }} />
                  {metric === "extra" && <span className="lcaveat"> No trial has measured these effects; the low end of every range is zero. The ranges show what the plan adds if every assumption is at its lowest or its highest.</span>}
                </p>
              )}
            </div>
            <div className="controls">
              <div>
                <span className="lb" id="lb-obj">Rank the actions by</span>
                <div className="objs" role="group" aria-labelledby="lb-obj">
                  {OBJECTIVES.map(([id, label], i) => {
                    const a = alts.data?.[i + 1];
                    const buys = a ? (a.chosen.length ? `${a.ui.metric === "extra" ? `${one(a.totals.shown.extra)} patients` : `${one(a.totals.shown.deaths)} deaths avoided`} · ${eurx(a.totals.eur)}` : "adds nothing here") : "…";
                    return <button key={id} aria-pressed={o.objective === id} disabled={!!a && !a.chosen.length} onClick={() => setObjective(id === defaultObjective ? null : id)}><b>{label}</b><small className="num">{buys}</small></button>;
                  })}
                </div>
              </div>
              <div>
                <span className="lb" id="lb-bud">Budget a year</span>
                <div className="budget">
                  <div className="seg" role="group" aria-labelledby="lb-bud">{PRESETS.map((b) => <button key={b} aria-pressed={budget === b} onClick={() => setBudget(b)}>{eurx(b).replace(/,000$/, "k")}</button>)}</div>
                  <BudgetField budget={budget} setBudget={setBudget} />
                </div>
              </div>
            </div>

            </details>

            {zero.length > 0 && (
              <div className="group zero">
                <h3 className="gh">{ui.step_zero_title_en}</h3>
                {zero.map((c) => <ActionCard key={c.intervention_id} {...cardProps(c)} />)}
              </div>
            )}
            {isFI && ui.by_county ? (
              <div className="group">
                <h3 className="gh">Where the money goes: {ui.by_county.length} counties, most patients gained first</h3>
                <div className="scrollx">
                  <table className="t alloc num">
                    <thead><tr><th /><th>County</th><th>Actions funded there</th><th className="n">Cost a year</th><th className="n">{metric === "extra" ? "More patients treated to cure a year" : "Deaths avoided a year"}</th></tr></thead>
                    <tbody>
                      {ui.by_county.map((c) => (
                        <tr key={c.area_id}>
                          <td className="r">{c.n}</td>
                          <td><button className="btn quiet sm" onClick={() => pick(c.area_id)}>{c.area_en}</button></td>
                          <td className="ms">{c.measures.map((m) => <span key={m.intervention_id}>{m.name_en} <span className="muted">({one(metric === "extra" ? m.shown.extra : m.shown.deaths)})</span></span>)}</td>
                          <td className="n">{eurx(c.eur)}</td>
                          <td className="n"><b>{one(metric === "extra" ? c.extra : c.deaths)}</b></td>
                        </tr>
                      ))}
                      <tr className="sum"><td /><td>Total</td><td>{chosen.length} actions</td><td className="n">{eurx(t.eur)}</td><td className="n"><b>{one(metric === "extra" ? t.shown.extra : t.shown.deaths)}</b></td></tr>
                    </tbody>
                  </table>
                </div>
                <p className="small muted pad">Open a county to see its actions with owner, first step and evidence. {t.shown_note_en}</p>
              </div>
            ) : (ui.groups ?? []).map((g) => {
              const rows = g.ids.map((id) => chosen.find((c) => c.intervention_id === id)).filter((c): c is Chosen => !!c);
              return rows.length === 0 ? null : (
                <div className="group" key={g.id}>
                  <h3 className="gh">{plainWords(g.title_en)}</h3>
                  {rows.map((c) => <ActionCard key={c.intervention_id} {...cardProps(c)} />)}
                </div>
              );
            })}

            {inPlace.length > 0 && (
              <div className="group placed">
                <h3 className="gh">Already in place <span className="muted">found by the web check, left out of the plan</span></h3>
                {inPlace.map((id) => {
                  const v = checks[id], row = baseRow(id);
                  return (
                    <article className="card placedcard" key={id}>
                      <div className="chead"><h3>{row?.name_en ?? byIv.get(id)?.name_en ?? id}</h3><button className="btn sm" onClick={() => putBack(id)}>Undo</button></div>
                      <p className="small">{row ? <><b className="num">{eurx(row.eur)} a year is freed.</b> </> : null}{v.verdict_en ? "The plan and the dots above no longer count it." : v.plan_effect_reason_en ?? v.in_use_summary_en}</p>
                      <WebCheckResult v={v} areaName={name} />
                    </article>
                  );
                })}
              </div>
            )}
            {off.length > 0 && (
              <div className="group placed">
                <h3 className="gh">Switched off <span className="muted">left out of the plan by you</span></h3>
                <ul className="offlist">
                  {off.map((id) => { const row = baseRow(id); return <li key={id}><span>{row?.name_en ?? byIv.get(id)?.name_en ?? id}{row ? <span className="muted num"> · {eurx(row.eur)} a year · {metric === "extra" ? `${one(row.shown.extra)} patients` : `${one(row.shown.deaths)} deaths avoided`} before it was left out</span> : null}</span><button className="btn sm" onClick={() => putBack(id)}>Put back</button></li>; })}
                </ul>
              </div>
            )}

            {(o.needs_national_decision ?? []).length > 0 && (
              <details className="group national more">
                <summary>{plainWords(ui.national_title_en)} <span className="muted">{(o.needs_national_decision ?? []).map((c) => `${c.name_en}, ${eurx(c.eur)} a year`).join("; ")}</span></summary>
                {(o.needs_national_decision ?? []).map((c) => <ActionCard key={c.intervention_id} {...cardProps(c)} national />)}
              </details>
            )}


          </div>
        )}
      </section>

      {ui?.pilot && !isFI && <PilotAsk p={ui.pilot} chosen={chosen} name={name} openPlan={openPlan} short />}

      <details className="panel morelist behind" aria-label="More detail">
      <summary><h2>Behind these numbers</h2><span className="muted">stage by stage, the second finding, how the plan was chosen, sources</span></summary>
      {cp && cp.stages.length > 0 && cur && (<>
          <details className="more">
            <summary>Stage by stage <span className="muted">{cp.stages.length} figures with intervals and sources, against Finland and the best county</span></summary>
            <div className="srows">
              {[...KEY_STAGES.map((id) => stages.get(id)).filter((s): s is Stage => !!s), ...cp.stages.filter((s) => !KEY_STAGES.includes(s.id))].map((s) => <StageRow own={isFI} key={s.id} s={s} where={name} flag={flags.get(s.id)} best={!isFI} />)}
            </div>
          </details>
          <details className="more">
            <summary>How to read these figures <span className="muted">what a dot is, what “beyond chance” means, what the count cannot say</span></summary>
            <div className="prose">
              {sur && <p>One dot is one patient in a hundred; a part-filled dot is a fraction. The operated share is the registry's age-standardised figure for {period(sur.period)}, the total is for {period(cur.period)}; the rest of the treated is the total minus the operated. Not adjusted for stage or other illness.</p>}
              {short > 0 && mp && (
                <p>
                  {mp.top_quartile && mp.top_quartile.per_year > 0 && <>Compared with the best quarter of counties ({one(mp.top_quartile.reference_pct)}%) the missing patients are <b>{one(mp.top_quartile.per_year)}</b> a year{mp.top_quartile.lo != null && mp.top_quartile.hi != null ? <> ({rng1(mp.top_quartile.lo, mp.top_quartile.hi)})</> : null}. </>}
                  The count is arithmetic on registry shares, not a causal estimate: the registry cannot say which of these patients could have been treated to cure.
                </p>
              )}
              {cp.limits_note_en && <p>“Beyond chance” means outside the range that chance alone gives a county of this size around the national share (95% limits). It shows a real difference, not its cause.</p>}
            </div>
          </details>
      </>)}
      {!isFI && d.pathway?.drug_finding && (
        <details className="more">
          <summary>The second finding: drug treatment <span className="muted">what is on record here against Finland, and what the plan does about it</span></summary>
          <DrugFinding pathway={d.pathway} where={name} />
        </details>
      )}
      {!isFI && (
        <details className="more">
          <summary>What is {name} already doing? <span className="muted">a web search of county and hospital pages{findings.length ? `, ${findings.length} findings` : ""}</span></summary>
          <Scout scope={scope} name={name} stored={scoutData} onNew={setScoutNew} bears={bears} linked={linked} />
        </details>
      )}
      {(cp?.expected || d.mortality_vs_incidence?.sentence_en) && (
        <details className="more expect">
          <summary>Is it the county, or who lives there? <span className="muted">the age-adjusted comparison and deaths against new cases</span></summary>
          <div className="prose">
            {cp?.expected?.sentence_en && <p>{cp.expected.sentence_en} <SourceChip short s={{ kind: "estimated", what: `Expected share treated to cure, ${name}`, value: `${one(cp.expected.expected_pct)}%`, note: cp.expected.method_en }} /></p>}
            {d.mortality_vs_incidence?.sentence_en && <p><b>Deaths against new cases.</b> {d.mortality_vs_incidence.sentence_en} <SourceChip short s={{ kind: "measured", source_url: d.mortality_vs_incidence.source_url, publisher: "Cancer Registry", period: "2020-2024", what: `Age-standardised lung cancer mortality and incidence, ${name}` }} /></p>}
            {cp?.expected && (
              <div className="adj">
                <div><b>Adjusted for</b><ul>{cp.expected.adjusted_for.map((x) => <li key={x}>{x}</li>)}</ul></div>
                <div><b>Could not be adjusted for</b><ul>{cp.expected.not_adjusted_for.map((x) => <li key={x}>{x}</li>)}</ul></div>
              </div>
            )}
            {cp?.expected?.why_not_standardised_en && <p>{cp.expected.why_not_standardised_en}</p>}
          </div>
        </details>
      )}
      {o?.goal3_link?.note_en && (
        <details className="more">
          <summary>Against Goal 3 of the cancer strategy <span className="muted">what this plan does for the national mortality target</span></summary>
          <div className="prose"><p>{o.goal3_link.note_en}</p></div>
        </details>
      )}

      {o && o.not_chosen.length > 0 && (
        <details className="more">
          <summary>Not in the plan, and why <span className="muted">{o.not_chosen.length} measures</span></summary>
          <ul className="notchosen">{o.not_chosen.map((n) => <li key={n.intervention_id}><b>{n.name_en ?? byIv.get(n.intervention_id)?.name_en ?? "This measure"}</b><span>{plainWords(n.reason_en).replace(/needs_national_decision/g, "needs a national decision")}</span></li>)}</ul>
        </details>
      )}
      {o && t && (o.rules_en ?? []).length > 0 && (
        <details className="more">
          <summary>How this was chosen <span className="muted">every rule the model follows, in words</span></summary>
          {(o.objective_note_en || (o.saturation_note_en && !nothing)) && (
            <div className="prose">
              {o.objective_note_en && <p>{euro(o.objective_note_en)}</p>}
              {o.saturation_note_en && !nothing && <p><b>{o.saturated ? "What more money cannot buy." : "The next euro."}</b> {euro(o.saturation_note_en)}</p>}
            </div>
          )}
              <ol className="rules">{(o.rules_en ?? []).map((r, i) => <li key={i}>{euro(plainWords(r).replace(/needs_national_decision/g, "a national decision"))}</li>)}{t.shown_note_en && <li>{t.shown_note_en}</li>}</ol>
        </details>
      )}
      <details className="more clock">
        <summary>Time (estimated) <span className="muted">a secondary view: days from first symptom to treatment are modelled, not measured</span></summary>
        <div className="body">
          {d.clock_note_en && <p className="small">{d.clock_note_en}</p>}
          <div className="scrollx">
            <table className="t num">
              <thead><tr><th>Step</th><th className="n">{name}, days</th><th className="n">Range</th><th className="n">Finland</th><th>Kind</th></tr></thead>
              <tbody>{d.steps.map((s) => {
                // The registry measures the medians per treatment for the university hospital area; mixing them into one number is our arithmetic, so it is an estimate with no range.
                const mixed = s.level === "collaborative_area", kind = mixed ? "estimated" : s.kind;
                const above = mixed ? d.care_path?.stages.find((x) => x.id === "time_to_treatment")?.value : null;
                return <tr key={s.id}><td>{s.label_en}</td><td className="n">{days(s.days.median)}</td><td className="n">{mixed && s.days.lo === s.days.hi ? "not published" : range(s.days.lo, s.days.hi)}</td><td className="n">{days(s.national_days)}</td><td><span className={`tag ${kind}`}>{KIND_LABEL[kind]}</span>{mixed ? <span className="small muted"> university hospital area, weighted by this county's mix of treatments{above != null && Math.abs(above - s.days.median) >= 0.05 ? ` (the ${one(above)} above uses Finland's mix)` : ""}</span> : null}</td></tr>;
              })}</tbody>
            </table>
          </div>
          {flags.get("time_to_treatment") && <p className="flag"><b>Recording caveat.</b> {flags.get("time_to_treatment")}</p>}
          {(d.consistency_check?.results ?? []).length > 0 && (
            <div className="small">
              <b>Does the estimated clock agree with measured outcomes?</b> We checked it against three, and publish the result as it is:
              <ul>{d.consistency_check!.results!.map((r) => <li key={r.indicator}>{plainCheck(r.sentence_en)}</li>)}</ul>
            </div>
          )}
        </div>
      </details>

      {d.data_gaps.length > 0 && (
        <details className="more">
          <summary>What Finland does not publish yet <span className="muted">{d.data_gaps.length} gaps that would sharpen this page</span></summary>
          <ul className="gaps">{d.data_gaps.map((g) => <li key={g.what_en}><b>{g.what_en}</b><p>{g.why_it_matters_en}</p><p className="who">Who could publish it: {g.who_could_publish_en}</p></li>)}</ul>
        </details>
      )}
      </details>
    </div>
  );
}

function BudgetField({ budget, setBudget }: { budget: number; setBudget: (n: number) => void }) {
  const [txt, setTxt] = useState(String(budget));
  useEffect(() => setTxt(String(budget)), [budget]);
  const commit = () => { const n = Number(txt.replace(/[^\d]/g, "")); if (Number.isFinite(n) && n > 0) setBudget(Math.min(50_000_000, n)); else setTxt(String(budget)); };
  return (
    <label className="field"><span className="muted">€</span>
      <input inputMode="numeric" aria-label="Budget in euros a year" value={txt} onChange={(e) => setTxt(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
    </label>
  );
}

/* ---------- one action ---------- */
interface CardProps { c: Chosen; iv?: Intervention; stage?: Stage; name: string; areaId: string; metric: "extra" | "deaths"; showExtra: boolean; showDeaths: boolean; national?: boolean;
  check?: VerifyResult; fresh: boolean; onCheck: (v: VerifyResult) => void; onDrop: () => void; findings: ScoutFinding[]; roadmap: { id: string; title_en?: string }[] }

/* An action at rest is three lines: what (title), what it costs and buys, who owns it; then the web check button and,
   once a check exists, its one verdict chip. Everything else opens under "Details". After a live check the card shows
   the chip and the one quote that decided it; how the check was made opens under "How we checked". */
function ActionCard({ c, iv, stage, name, areaId, metric, showExtra, showDeaths, national, check, fresh, onCheck, onDrop, findings, roadmap }: CardProps) {
  const run = useLiveRun<VerifyResult>();
  const [more, setMore] = useState(false);
  const k = c.kpi;
  const zero = c.group === "step_zero";
  const ex = c.extra_curative_patients_per_year, de = c.deaths_avoided_per_year;
  const unit = k?.unit === "%" ? "%" : k?.unit ? ` ${k.unit}` : "";
  const use = check ? inUseWord(check, name) : null;
  const chip = check ? IN_USE_SHORT[check.in_use_here ?? ""] ?? use?.[1] ?? null : null;
  // A check that found part of the measure in place changes what to do first; its reason opens under Details.
  const flag = check && !national && !movesOut(check) && check.plan_effect === "flag" && check.plan_effect_reason_en ? check : null;
  const rm = roadmap.find((r) => r.id === iv?.roadmap_measure);
  // The check runs as a job on the server: a dropped connection loses nothing, and pressing again joins the running check.
  const start = () => run.start(() => api.verifyStart(c.intervention_id, areaId), onCheck);
  const because = zero ? c.why_first_en : stage && stage.value != null && stage.national != null && areaId !== "FI"
    ? `Because ${name}'s share for “${lower(stage.label_en)}” is ${sval(stage)} against ${sval(stage, stage.national)} in Finland.` : null;
  const lastStep = [...run.steps].reverse().map(stepLabel).find(Boolean);
  const done = check && !run.running;
  const quote = done && check.in_use_quote ? (
    <blockquote className="cquote">“{check.in_use_quote}”{check.in_use_source?.url ? <> <a href={check.in_use_source.url} target="_blank" rel="noreferrer">{check.in_use_source.title ?? host(check.in_use_source.url)}</a></> : null}</blockquote>
  ) : null;
  const how = done ? (
    <details className="vhow chow"><summary>How we checked</summary>
      <LiveOutcome v={check} retry={start} />
      <WebCheckResult v={check} areaName={name} fresh={fresh} lead={false}>
        {!national && (check.in_use_here === "yes" || movesOut(check)) && <p className="small"><b>The budget should not buy it twice.</b> <button type="button" className="btn sm" onClick={onDrop}>Re-plan without it</button></p>}
      </WebCheckResult>
    </details>
  ) : null;
  const patients = zero ? "no direct effect"
    : metric === "deaths" || (national && !(c.shown.extra > 0)) ? (showDeaths || national ? <>{one(c.shown.deaths)} deaths avoided a year <span className="rg">({rng1(de.lo, de.hi)}, modelled)</span></> : null)
    : (showExtra || national) && c.shown.extra > 0 ? (+ex.hi.toFixed(1) <= +c.shown.extra.toFixed(1)
      ? <>up to {one(ex.hi)} more treated to cure a year <span className="rg">(could be 0)</span></>
      : <>{one(c.shown.extra)} more treated to cure a year <span className="rg">({rng1(ex.lo, ex.hi)})</span></>) : null;
  const numbered = !zero && !national && c.n != null;
  const detId = `det-${c.intervention_id}`;
  return (
    <article id={`card-${c.intervention_id}`} data-action={c.intervention_id} className={"card card3" + (national ? " nat" : "") + (flag ? " flagged" : "") + (numbered ? " numbered" : "") + (more ? " opened" : "")}>
      {numbered && <span className="no num" aria-hidden="true">{c.n}</span>}
      <div className="cbody">
        <h3>{c.name_en}</h3>
        <p className="cfacts num"><b>{eurx(c.eur)}</b> a year{national ? ", outside this budget" : ""}{patients && <> · {patients}</>}</p>
        {c.owner_en && <p className="cown"><span>Owner</span> {c.owner_en}</p>}
      </div>
      <div className="crow">
        <button className="btn sm" onClick={start} disabled={run.running} title={`Is it already in place in ${name}? An agent searches and reads county and hospital pages through the Oxylabs Web API.`}>Check on the web</button>
        {run.running ? <span className="cprog" role="status"><i className="spin" aria-hidden="true" />{run.waiting ? "Waiting for the connection" : lastStep ?? "Starting the check"}…</span>
          : chip && use && <span className={`inuse ${use[0]}`}>{chip}</span>}
      </div>
      <button type="button" className="linkish cmore" aria-expanded={more} aria-controls={detId} onClick={() => setMore((x) => !x)}>{more ? "Less" : "Details"}</button>
      {run.error && <p className="readerr">{run.error}{check ? ` The stored check of ${dayOf(check.checked_at)} stays.` : ""} <button className="btn sm" onClick={start}>Try again</button></p>}
      {done && fresh && <div className="cafter" role="status">{(check.live_outcome === "failed" || check.live_outcome === "kept") && <span className="cstored">{check.live_outcome === "kept" ? "The live run found no more" : check.live_slow_s ? `The live run is still reading after ${check.live_slow_s} s` : "The live run did not finish"}; this is the stored answer of {dayOf(check.checked_at)}.</span>}{quote}{flag && <p className="cplan"><b>The plan changes: {(adviceWord(flag) ?? "ask first").toLowerCase()}.</b> {plainWords(flag.plan_effect_reason_en)}</p>}{how}</div>}
      {more && (
        <div className="cdetail" id={detId}>
          {flag && <p className="askfirst"><b>{adviceWord(flag) ?? "Ask first"}.</b> {plainWords(flag.plan_effect_reason_en)}</p>}
          {c.why_here_en && <p><b>Why here.</b> {c.why_here_en}</p>}
          {zero && because && <p><b>Why first.</b> {because}</p>}
          {c.first_step_en && <p><b>{flag ? "Then, the first step." : "First step."}</b> {c.first_step_en}</p>}
          {c.day90_en && !national && <p><b>Done in 90 days when.</b> {c.day90_en.split(" Counted:")[0]}</p>}
          {c.study_line_en && <div className="studyline"><StudyLine text={c.study_line_en} label="The evidence:" linkLabel="open the study" /></div>}
          {done && !fresh && (quote || how) && <div className="cweb"><b>Web check, {dayOf(check.checked_at)}.</b>{quote}{how}</div>}
          {!national && <label className="inplan"><input type="checkbox" checked onChange={onDrop} /> In the plan</label>}
          <details className="vhow"><summary>More on the evidence and the numbers</summary>
            <div className="meta">
              {iv?.what_en && <div><b>What it is:</b> {iv.what_en}</div>}
              {!zero && c.eur_per_extra_curative_patient != null && c.shown.extra > 0 && <div><b>Cost per extra patient treated to cure:</b> <span className="num">{eurAbout(c.eur_per_extra_curative_patient)}</span></div>}
              {c.eur_per_death_avoided != null && (metric === "deaths" || national) && <div><b>Cost per death avoided:</b> <span className="num">{eurAbout(c.eur_per_death_avoided)}</span></div>}
              {k && (
                <div><b>Measure:</b> {k.label_en}: {k.baseline != null && k.target != null ? <><b className="num">{one(k.baseline)}{unit} → {one(k.target)}{unit}</b>{k.by_year ? ` by ${k.by_year}` : ""}</>
                  : <>{k.baseline_note_en ?? "not published today."} {k.target_note_en}</>}
                  {k.baseline != null && k.target != null && k.target_rule_en ? <span className="muted"> ({k.target_rule_en})</span> : null}</div>
              )}
              {zero && <div><b>Direct effect:</b> none; it shows how much of the gap is missing records.</div>}
              {c.owner_en && c.owner_level && <div><b>Whose decision:</b> {c.owner_level === "collaborative_area" ? "needs the university hospital area" : c.owner_level === "national" ? "a national decision" : "the county's own"}</div>}
              {iv?.roadmap_measure && <div><b>Roadmap measure {iv.roadmap_measure}:</b> {rm?.title_en ?? ""}</div>}
              {iv?.prerequisite_en && <div><b>Needs first:</b> {iv.prerequisite_en}</div>}
              {iv?.effect.basis && <div><b>The effect we assume{iv.effect.kind === "assumption" ? " (an assumption)" : ""}:</b> {iv.effect.basis}</div>}
              {c.note_en && <div><b>How the number is built:</b> {c.note_en}</div>}
              {(iv?.evidence ?? []).length > 0 && (
                <div><b>Evidence</b>
                  <ul>{iv!.evidence.map((e, i) => <li key={i}>{e.claim}{e.quote ? <blockquote>“{e.quote}”</blockquote> : null}<span className="muted">{[e.design, e.year].filter(Boolean).join(", ")}{e.url ? <> · <a href={e.url} target="_blank" rel="noreferrer">{host(e.url)}</a></> : null}{e.verified === false ? " · listed, not opened by us" : ""}</span></li>)}</ul>
                </div>
              )}
              {findings.length > 0 && <div className="found"><b>The web scout found, for this action</b><ul>{findings.map((f, i) => <Finding key={i} f={f} />)}</ul></div>}
              {(iv?.null_results ?? []).length > 0 && (
                <div><b>What speaks against it</b>
                  <ul>{iv!.null_results!.map((e, i) => <li key={i}>{e.claim}{e.url ? <span className="muted"> · <a href={e.url} target="_blank" rel="noreferrer">{host(e.url)}</a>{e.year ? `, ${e.year}` : ""}</span> : null}</li>)}</ul>
                </div>
              )}
            </div>
          </details>
        </div>
      )}
    </article>
  );
}
