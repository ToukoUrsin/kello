import { Chosen, one, Pilot } from "./lib";

/* The pilot ask: the two actions to try first and what six months of them is counted in. Every figure comes from
   `pilot.six_months` and `pilot.effect`; the words around them are the only thing written here. */

type Lang = "en" | "fi";
const nf = (n: number, lang: Lang) => (lang === "fi" ? one(n).replace(".", ",") : one(n));
const pctx = (n: number, lang: Lang) => (lang === "fi" ? `${nf(n, lang)} %` : `${one(n)}%`);
const round = (n: number) => String(Math.round(n));
const sentences = (t: string) => t.split(/(?<=\.)\s+(?=[A-ZÅÄÖ])/);

const L = {
  en: { patients: "new patients in six months", decisions: "decisions not to operate, reviewed", comparison: "counted against", cmpSub: (p: string, d: string) => `about ${p} patients and ${d} decisions in the same six months`, share: (y?: number) => `treated to cure${y ? ` by ${y}` : ""}, estimated` },
  fi: { patients: "uutta potilasta kuudessa kuukaudessa", decisions: "arvioitua päätöstä jättää leikkaamatta", comparison: "vertailualue", cmpSub: (p: string, d: string) => `noin ${p} potilasta ja ${d} päätöstä samassa ajassa`, share: (y?: number) => `parantavan hoidon osuus${y ? ` vuoteen ${y} mennessä` : ""}, arvio` },
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
  if (s.comparison_area_en) cells.push({ k: "cmp", v: <span className="pname">{cmpName ?? s.comparison_area_en}</span>, sub: <>{l.comparison}{seen?.comparison != null && rev?.comparison != null ? <>: {l.cmpSub(nf(Math.round(seen.comparison), lang), nf(Math.round(rev.comparison), lang))}</> : null}</> });
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

/** County page: the ask as the page's conclusion. */
export function PilotAsk({ p, chosen, openPlan }: { p: Pilot; chosen: Chosen[]; name: string; openPlan: () => void }) {
  const { lead, rest } = pilotText(p);
  const acts = p.actions.map((id) => chosen.find((c) => c.intervention_id === id)).filter((c): c is Chosen => !!c);
  return (
    <section className="ask" aria-label="The ask" id="sec-ask">
      <header>
        <h2>The ask</h2>
        <button className="btn primary" onClick={openPlan}>Open the plan</button>
      </header>
      <p className="asklead">{lead}</p>
      {acts.length > 0 && <ul className="askacts">{acts.map((c) => <li key={c.intervention_id}>{c.n != null && c.n > 0 && <span className="no num">{c.n}</span>}{c.name_en}</li>)}</ul>}
      <PilotFigures p={p} />
      {rest && <p className="askrest">{rest}</p>}
      {p.cannot_show_en && <p className="askcannot">{p.cannot_show_en}</p>}
    </section>
  );
}
