import { useMemo } from "react";
import { api, AreaMeta, Chosen, eurFi, eurx, useAsync, VerifyResult } from "./lib";
import { Failed, Skeleton } from "./App";
import { adviceWord } from "./WebCheck";
import ExpertQuote from "./ExpertQuote";

type Lang = "en" | "fi";
const T = {
  en: { title: (n: string) => `${n}: who does what on Monday`, sub: (k: number, eur: string) => `${k} actions, at most ${eur} a year: less for each one the hospital says already runs. Each row is one person's job: what they do this week, what it costs, and what done looks like in 90 days.`,
    who: "Who", what: "Action", week: "This week", cost: "Cost a year", done: "Done in 90 days when", zero: "Step zero", ask: "Week 1: ask the university hospital first",
    askSub: "A web search of county and hospital pages found signs that part of this already runs. One phone call each settles it before any money moves.",
    web: (w: string, d: string) => `Web check ${d}: ${w.toLowerCase()}`, total: "All actions, if each is needed in full", print: "Print / save PDF", plan: "Open the one-page plan", county: "Back to the county",
    note: "Costs are planning estimates. “Done” is work the county can count itself; no trial has measured how many more patients these actions get treated to cure.", none: "No actions are chosen for this county at this budget." },
  fi: { title: (n: string) => `${n}: kuka tekee mitä maanantaina`, sub: (k: number, eur: string) => `${k} toimea, enintään ${eur} vuodessa: vähemmän jokaisesta, jonka sairaala kertoo jo olevan käytössä. Jokainen rivi on yhden ihmisen tehtävä: mitä hän tekee tällä viikolla, mitä se maksaa ja mistä tietää 90 päivän kuluttua, että se on tehty.`,
    who: "Kuka", what: "Toimi", week: "Tällä viikolla", cost: "Kustannus / v", done: "Tehty 90 päivässä, kun", zero: "Vaihe nolla", ask: "Viikko 1: kysy ensin yliopistosairaalalta",
    askSub: "Alueen ja sairaalan verkkosivuilta löytyi merkkejä siitä, että osa tästä on jo käytössä. Yksi puhelu kustakin ratkaisee asian ennen kuin rahaa käytetään.",
    web: (w: string, d: string) => `Verkkotarkistus ${d}: ${({ "take it out": "jo käytössä", "narrow it": "osin käytössä, rajaa", "ask first": "osin käytössä, kysy ensin" } as Record<string, string>)[w.toLowerCase()] ?? "kysy ensin"}`, total: "Kaikki toimet, jos jokainen tarvitaan kokonaan", print: "Tulosta / tallenna PDF", plan: "Avaa yhden sivun suunnitelma", county: "Takaisin alueeseen",
    note: "Kustannukset ovat suunnitteluarvioita. ”Tehty” on työtä, jonka alue voi itse laskea; yksikään tutkimus ei ole mitannut, kuinka monta potilasta enemmän nämä toimet tuovat parantavaan hoitoon.", none: "Tälle alueelle ei ole valittu toimia tällä budjetilla." },
};
const day = (iso?: string | null, lang: Lang = "en") => (iso ? new Date(iso).toLocaleDateString(lang === "fi" ? "fi-FI" : "en-GB", { day: "numeric", month: "short" }) : "");

/** One page a county official can act on without us: owner, first step this week, cost, and what done looks like in 90 days. */
export default function Monday({ scope, budget, lang, setLang, objective, without, areas, openPlan, openCounty }:
  { scope: string; budget: number; lang: Lang; setLang: (l: Lang) => void; objective: string | null; without: string[]; areas: AreaMeta[]; openPlan: () => void; openCounty: () => void }) {
  const opt = useAsync(() => api.optimize(scope, budget, objective, without), [scope, budget, objective, without.join(",")]);
  const checks = useAsync(() => api.verifyLatest(scope), [scope]);
  const t = T[lang], fi = lang === "fi";
  const meta = areas.find((a) => a.id === scope);
  const name = scope === "FI" ? (fi ? "Suomi" : "Finland") : (fi ? meta?.name_fi ?? meta?.short_en : meta?.short_en) ?? opt.data?.scope_en ?? scope;
  const money = (n: number) => (fi ? eurFi(n) : eurx(n));
  const by = useMemo(() => Object.fromEntries((checks.data ?? []).map((v) => [v.intervention_id, v])) as Record<string, VerifyResult>, [checks.data]);
  if (opt.loading && !opt.data) return <div className="monday"><Skeleton rows={[40, 20, 300]} /></div>;
  if (opt.error && !opt.data) return <div className="monday"><Failed message={opt.error} retry={opt.reload} /></div>;
  const d = opt.data!;
  const zero = new Set(d.ui?.step_zero ?? []);
  const rows = [...d.chosen.filter((c) => zero.has(c.intervention_id)), ...d.chosen.filter((c) => !zero.has(c.intervention_id)).sort((a, b) => (a.n ?? 99) - (b.n ?? 99))];
  const flagged = (c: Chosen) => { const v = by[c.intervention_id]; return v && v.plan_effect === "flag" ? v : null; };
  const ask = d.pilot?.ask_first ?? [];
  return (
    <div className="monday" lang={lang}>
      <header className="mhead">
        <div>
          <h1>{t.title(name)}</h1>
          <p className="lede">{t.sub(rows.length, money(d.totals.eur))}</p>
        </div>
        <div className="mtools noprint">
          <div className="seg" role="group" aria-label="Language">
            <button aria-pressed={!fi} onClick={() => setLang("en")}>English</button><button aria-pressed={fi} onClick={() => setLang("fi")}>Suomi</button>
          </div>
          <button className="btn primary" onClick={() => window.print()}>{t.print}</button>
        </div>
      </header>
      <ExpertQuote scope={scope} lang={lang} />
      <div className="mweek">
      {rows.some((c) => zero.has(c.intervention_id)) && rows.length > 1 && <p className="mdecide">{fi
        ? <><b>Päätös tällä viikolla.</b> Hyväksy rivin 0 kertomustarkistus ({money(rows.find((c) => zero.has(c.intervention_id))!.eur)}) ja soita yliopistosairaalaan alla olevat kysymykset. Rivit 1–{rows.length - 1} käynnistetään vasta, kun vastaukset ja tarkistuksen tulos ovat tiedossa, ja vain ne, joita tulos tukee.</>
        : <><b>The decision this week.</b> Approve the chart check in row 0 ({money(rows.find((c) => zero.has(c.intervention_id))!.eur)}) and call the university hospital with the questions below. Rows 1–{rows.length - 1} start only when those answers and the chart check are in, and only the ones they support.</>}</p>}
      {ask.length > 0 && (
        <section className="mask1" aria-label={t.ask}>
          <h2>{t.ask}</h2>
          <p className="small muted">{t.askSub}</p>
          <ol>{ask.map((q) => <li key={q.intervention_id}>{fi ? q.question_fi ?? q.question_en : q.question_en}</li>)}</ol>
        </section>
      )}
      </div>
      {rows.length === 0 ? <p className="muted">{t.none}</p> : (
        <table className="mtable">
          <thead><tr><th className="mn" aria-label="#" /><th>{t.who}</th><th>{t.what}</th><th>{t.week}</th><th className="r">{t.cost}</th><th>{t.done}</th></tr></thead>
          <tbody>
            {rows.map((c) => {
              const f = flagged(c);
              return (
                <tr key={c.intervention_id} className={zero.has(c.intervention_id) ? "zero" : undefined}>
                  <td className="mn num" data-th="">{zero.has(c.intervention_id) ? "0" : c.n ?? ""}</td>
                  <td data-th={t.who} className="mwho">{(fi ? c.owner_fi : null) ?? c.owner_en}</td>
                  <td data-th={t.what} className="mwhat"><b>{(fi ? c.name_fi : null) ?? c.name_en}</b>
                    {f && <span className="mask">{t.web(adviceWord(f) ?? "Ask first", day(f.checked_at, lang))}</span>}</td>
                  <td data-th={t.week}>{(fi ? c.first_step_fi : null) ?? c.first_step_en}</td>
                  <td data-th={t.cost} className="r num mcost">{money(c.eur)}</td>
                  <td data-th={t.done} className="mdone">{(() => { const [done, counted] = ((fi ? c.day90_fi : null) ?? c.day90_en ?? "").split(/\s(?=(?:Counted|Lasketaan|Laskenta):)/); return <>{done}{counted && <span className="mcounted">{counted}</span>}</>; })()}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot><tr><td /><td colSpan={3}><b>{t.total}</b></td><td className="r num mcost"><b>{money(d.totals.eur)}</b></td><td /></tr></tfoot>
        </table>
      )}
      <p className="small muted mnote">{t.note}</p>
      <div className="mlinks noprint"><button className="btn" onClick={openPlan}>{t.plan}</button><button className="btn quiet" onClick={openCounty}>{t.county}</button></div>
    </div>
  );
}
