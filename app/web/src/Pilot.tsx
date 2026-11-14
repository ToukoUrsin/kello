import { Chosen, one, Pilot } from "./lib";

/* The pilot ask: the two actions to try first and what six months of them is counted in. Every figure comes from
   `pilot.six_months` and `pilot.effect`; the words around them are the only thing written here. */

type Lang = "en" | "fi";
const nf = (n: number, lang: Lang) => (lang === "fi" ? one(n).replace(".", ",") : one(n));
const pctx = (n: number, lang: Lang) => (lang === "fi" ? `${nf(n, lang)} %` : `${one(n)}%`);
const round = (n: number) => String(Math.round(n));
const sentences = (t: string) => t.split(/(?<=\.)\s+(?=[A-ZÅÄÖ])/);

const L = {
  en: { patients: "new patients in six months", decisions: "decisions not to operate reviewed (cancer not spread; Finland's stage mix assumed)", comparison: "counted against", cmpSub: (p: string, d: string) => `about ${p} patients and ${d} decisions in the same six months`, share: (y?: number) => `treated to cure${y ? ` by ${y}` : ""} with these two actions, estimated` },
  fi: { patients: "uutta potilasta kuudessa kuukaudessa", decisions: "arvioitua päätöstä jättää leikkaamatta (ei etäpesäkkeitä; oletuksena koko maan levinneisyysjakauma)", comparison: "vertailualue", cmpSub: (p: string, d: string) => `noin ${p} potilasta ja ${d} päätöstä samassa ajassa`, share: (y?: number) => `parantavan hoidon osuus${y ? ` vuoteen ${y} mennessä` : ""} näillä kahdella toimella, arvio` },
};

/** The figures row: patients, decisions reviewed, the comparison county, the share before and after. */
export function PilotFigures({ p, lang = "en", cmpName }: { p: Pilot; lang?: Lang; cmpName?: string }) {
  const s = p.six_months ?? {};
  const seen = s.patients_seen, rev = s.no_surgery_decisions_reviewed;
  const e = p.effect ?? ({} as Pilot["effect"]);
  const l = L[lang];
  const cells: { k: string; v: React.ReactNode; sub: React.ReactNode }[] = [];
  if (seen?.expected != null) cells.push({ k: "seen", v: `${lang === "fi" ? "noin" : "about"} ${round(seen.expected)}`, sub: l.patients });
  if (rev?.expected != null) cells.push({ k: "rev", v: round(rev.expected), sub: l.decisions });
  if (s.comparison_area_en) cells.push({ k: "cmp", v: <span className="pname">{cmpName ?? s.comparison_area_en}</span>, sub: <>{l.comparison}{seen?.comparison != null && rev?.comparison != null ? <>: {l.cmpSub(round(seen.comparison), round(rev.comparison))}</> : null}</> });
  if (e.curative_share_now_pct != null && e.curative_share_after_pct != null) cells.push({ k: "share", v: <>{pctx(e.curative_share_now_pct, lang)} <span className="to" aria-label="to">→</span> <span className="after">{pctx(e.curative_share_after_pct, lang)}</span></>, sub: l.share(e.by_year) });
  if (!cells.length) return null;
  return <dl className="pfigs num">{cells.map((c) => <div key={c.k}><dt className="sr">{typeof c.sub === "string" ? c.sub : c.k}</dt><dd><b>{c.v}</b><small>{c.sub}</small></dd></div>)}</dl>;
}

/** The text around the figures: its first sentence leads, the sentence the figures restate is left out, the rest follows. */
export function pilotText(p: Pilot, lang: Lang = "en") {
  const text = (lang === "fi" ? p.text_fi : null) ?? p.text_en;
  const all = sentences(text);
  const seen = p.six_months?.patients_seen?.expected, rev = p.six_months?.no_surgery_decisions_reviewed?.expected;
  const restated = (x: string) => seen != null && rev != null && x.includes(round(seen)) && x.includes(round(rev));
  const hasFigures = seen != null || rev != null;
  return { lead: all[0] ?? text, rest: all.slice(1).filter((x) => !(hasFigures && restated(x))).join(" ") };
}

/** The gate between the audit and any further spend. */
export function PilotGate({ p, lang = "en" }: { p: Pilot; lang?: Lang }) {
  const fi = lang === "fi";
  const audit = p.audit;
  return <p className="pilotgate"><b>{fi ? "Portti." : "The gate."}</b> {fi ? `Ennen sairaalan vastauksia ja kertomusten tarkistusta ei käytetä muuta kuin tarkistuksen ${audit?.cost_eur?.toLocaleString("fi-FI") ?? "8 000"} €. Jos tarkistus osoittaa, että potilaat on sittenkin hoidettu, työ päättyy siihen ja alue on korjannut kirjauksensa.` : `Nothing beyond the ${audit?.cost_eur ? `€${audit.cost_eur.toLocaleString("en-GB")}` : "€8,000"} audit is spent before the hospital has answered and the charts are read. If the charts show the patients were treated after all, the work stops there and the county has fixed its records.`}</p>;
}

export function PilotSteps({ p, lang = "en", gate = true }: { p: Pilot; lang?: Lang; gate?: boolean }) {
  const fi = lang === "fi";
  const ask = p.ask_first ?? [];
  const audit = p.audit;
  const success = p.success;
  const moved = success?.patients_moved;
  return <div className="pilotsteps">
    <article><b>1</b><div><h3>{fi ? "Viikko 1: kysy ensin" : "Week 1: ask first"}</h3><ul>{ask.map((q) => <li key={q.intervention_id}>{fi ? (q.question_fi ?? q.question_en) : q.question_en}</li>)}</ul></div></article>
    <article><b>2</b><div><h3>{fi ? `Viikot 1–8: tarkistus (${audit?.cost_eur?.toLocaleString("fi-FI") ?? "8 000"} €)` : `Weeks 1–8: audit (${audit?.cost_eur ? `€${audit.cost_eur.toLocaleString("en-GB")}` : "€8,000"})`}</h3><p>{fi ? `${audit?.charts ?? 50} kertomusta: ${audit?.fields_fi?.join(", ") ?? "levinneisyysaste, toimintakyky, biomarkkerit, hoitopäätös ja hoitopaikka"}.` : `${audit?.charts ?? 50} charts: ${audit?.fields_en?.join(", ") ?? "stage, fitness, biomarker tested, why no curative treatment and where treated"}.`}</p></div></article>
    {gate && <PilotGate p={p} lang={lang} />}
    <article><b>3</b><div><h3>{fi ? "Kuukaudet 3–6: vain se, mitä tarkistus tukee" : "Months 3–6: only what the audit supports"}</h3><p>{fi ? (p.targets_fi ?? "Mitoita thoraxkirurgin arvio ja täsmäsädehoidon lähete tarkistuksen perusteella.") : (p.targets_en ?? "Size the thoracic-surgeon review and precise-radiotherapy referral from the audit.")}</p></div></article>
    <div className="pilotsuccess"><b>{fi ? "Onnistuminen kuudessa kuukaudessa" : "Six-month success"}</b><span>{fi ? `${success?.charts_audited ?? 50} kertomusta tarkistettu · ${success?.decisions_not_to_operate_reviewed ?? "–"} päätöstä jättää leikkaamatta arvioitu · muuttuneet päätökset ja tehdyt lähetteet lasketaan.` : `${success?.charts_audited ?? 50} charts audited · ${success?.decisions_not_to_operate_reviewed ?? "–"} decisions not to operate reviewed · decisions changed and referrals made counted.`}</span>{moved?.model_estimate != null && <small>{fi ? `Potilassiirtymät: toissijainen malliarvio noin ${nf(moved.model_estimate, "fi")} (${nf(moved.lo ?? 0, "fi")}–${nf(moved.hi ?? 0, "fi")}).` : `Patients moved: secondary model estimate about ${one(moved.model_estimate)} (${one(moved.lo ?? 0)}–${one(moved.hi ?? 0)}).`}</small>}</div>
    {p.comparison_en && <p className="pilotcomparison">{fi ? (p.comparison_fi ?? p.comparison_en) : p.comparison_en}</p>}
  </div>;
}

/** County page: the ask as the page's conclusion. */
export function PilotAsk({ p, openPlan, short = false }: { p: Pilot; chosen?: Chosen[]; name: string; openPlan: () => void; short?: boolean }) {
  const { lead } = pilotText(p);
  if (short) return (
    <section className="ask askshort" aria-label="The ask" id="sec-ask">
      <header>
        <h2>The ask</h2>
        <button className="btn primary" onClick={openPlan}>Open the plan</button>
      </header>
      <PilotRail p={p} />
      <details className="askmore"><summary>The questions, figures and caveats</summary>
        <p className="asklead">{lead}</p>
        <PilotSteps p={p} gate={false} />
        <PilotFigures p={p} />
        {p.cannot_show_en && <p className="askcannot">{p.cannot_show_en}</p>}
      </details>
    </section>
  );
  return (
    <section className="ask" aria-label="The ask" id="sec-ask">
      <header>
        <h2>The ask</h2>
        <button className="btn primary" onClick={openPlan}>Open the plan</button>
      </header>
      <p className="asklead">{lead}</p>
      <PilotSteps p={p} />
      <PilotFigures p={p} />
      {p.cannot_show_en && <p className="askcannot">{p.cannot_show_en}</p>}
    </section>
  );
}

/** The ask at a glance: the three step titles on a rail, and the gate sentence between the audit and the spend. */
function PilotRail({ p }: { p: Pilot }) {
  const audit = p.audit;
  const eur = audit?.cost_eur ? `€${audit.cost_eur.toLocaleString("en-GB")}` : "€8,000";
  const n = (p.ask_first ?? []).length;
  return (
    <ol className="askrail">
      <li><span className="when">Week 1</span><span className="what">Ask first{n ? <span className="muted num"> · {n} question{n === 1 ? "" : "s"}</span> : null}</span></li>
      <li><span className="when">Weeks 1–{audit?.weeks ?? 8}</span><span className="what">Audit {audit?.charts ?? 50} charts<span className="muted num"> · {eur}</span></span></li>
      <li className="gate"><PilotGate p={p} /></li>
      <li className="go"><span className="when">Months 3–6</span><span className="what">Only what the audit supports</span></li>
    </ol>
  );
}
