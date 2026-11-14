import { eurAbout, eurx, int, Interval, one } from "../lib";
import { BudgetCurve, Scenario, SiteKind } from "./data";
import { PinM } from "./model";
import { BudgetChart } from "./Charts";
import { KindTag } from "./Cards";

export type Tool = "budget" | "actions" | "site" | "level" | "records";
const TOOLS: [Tool, string][] = [["budget", "Budget"], ["actions", "Actions"], ["site", "New site"], ["level", "Level up"], ["records", "Records"]];
export const SITE: Record<SiteKind, string> = { radiotherapy: "Radiotherapy unit", full: "Full treatment site" };
const r0 = (n: number) => String(+n.toFixed(1));

interface Props {
  tool: Tool; setTool: (t: Tool) => void; isFI: boolean; name: string; w: number; unit: string;
  curve: BudgetCurve | null; curveLoading: boolean; budget: number | null; setBudget: (b: number | null) => void; numbers: Map<string, number>; myDots: number;
  pins: PinM[]; exclude: string[]; toggle: (id: string) => void; total: number | null; extra: Interval | null; optLoading: boolean;
  siteKind: SiteKind | null; setSiteKind: (k: SiteKind | null) => void; scenario: Scenario | null; scenarioLoading: boolean; nSites: number; removeSite: () => void; siteCost: number | null; setSiteCost: (n: number | null) => void; hasStage: boolean; focus: string | null;
  level: null | "national" | "best"; setLevel: (l: null | "national" | "best") => void; totalDots: number; bestDots: number; natPct: number | null; bestPct: number | null;
  unrec: number; setUnrec: (n: number) => void; hidden: number | null; auditEur: number | null;
}

/** What-ifs on the map: every control changes the picture, and the card says only the numbers. */
export default function Explore(p: Props) {
  const tools = TOOLS.filter(([t]) => !(p.isFI && (t === "actions" || t === "records")));
  const tool = tools.some(([t]) => t === p.tool) ? p.tool : "budget";
  return (
    <div className="st-explore-panel">
      <div className="seg wrap st-tools" role="group" aria-label="What to try">
        {tools.map(([t, label]) => <button key={t} aria-pressed={tool === t} onClick={() => p.setTool(t)}>{label}</button>)}
      </div>
      {tool === "budget" && <Budget {...p} />}
      {tool === "actions" && <Actions {...p} />}
      {tool === "site" && <Site {...p} />}
      {tool === "level" && <Level {...p} />}
      {tool === "records" && <Records {...p} />}
    </div>
  );
}

function Budget({ curve, curveLoading, budget, setBudget, w, numbers, unit, myDots }: Props) {
  if (!curve) return <p className="st-quiet">{curveLoading ? "Working out the plan at every budget" : "The budget curve is not available right now."}</p>;
  const pts = [...curve.points].sort((a, b) => a.budget_eur - b.budget_eur), maxB = pts[pts.length - 1].budget_eur;
  const b = budget ?? curve.flat_from_eur ?? maxB;
  const at = [...pts].reverse().find((x) => x.budget_eur <= b + 0.5) ?? pts[0];
  return (
    <>
      <BudgetChart curve={curve} budget={b} w={w} numbers={numbers} unit={unit} />
      <label className="st-slider" style={{ paddingLeft: 30 - 8, paddingRight: 12 - 8 }}>
        <span className="sr">Budget, euros a year</span>
        <input type="range" min={0} max={Math.ceil(maxB)} step={Math.max(500, Math.round(maxB / 400 / 500) * 500)} value={Math.min(b, maxB)} onChange={(e) => setBudget(Number(e.target.value))} />
      </label>
      <dl className="st-nums">
        <div><dt>Budget a year</dt><dd className="num">{eurx(Math.round(b))}</dd></div>
        <div><dt>Spent</dt><dd className="num">{eurx(at.spent_eur)}{at.n_actions != null && <small> · {at.n_actions} actions</small>}</dd></div>
        <div><dt>Reached a year</dt><dd className="num">{r0(at.extra)}{myDots ? <small> of {myDots}</small> : null}<small> · range {r0(at.lo)} to {r0(at.hi)}</small></dd></div>
      </dl>
    </>
  );
}

function Actions({ pins, exclude, toggle, total, extra, optLoading, myDots }: Props) {
  return (
    <>
      <ul className="st-toggles">
        {pins.map((x) => (
          <li key={x.id}>
            <label title={x.name}>
              <input type="checkbox" checked={!exclude.includes(x.id)} onChange={() => toggle(x.id)} />
              <i className="num">{exclude.includes(x.id) ? "–" : x.n}</i><b>{x.short}</b><span className="num">{eurx(x.eur)}</span>
            </label>
          </li>
        ))}
      </ul>
      <dl className={"st-nums" + (optLoading ? " busy" : "")}>
        <div><dt>Plan a year</dt><dd className="num">{eurx(total)}</dd></div>
        {extra && <div><dt>Reached a year</dt><dd className="num">{r0(extra.median)}{myDots ? <small> of {myDots}</small> : null}<small> · range {r0(extra.lo)} to {r0(extra.hi)}</small></dd></div>}
      </dl>
      <p className="st-fine on">Take an action out here or on the map. The optimiser solves the plan again without it. <KindTag kind="estimated" /></p>
    </>
  );
}

function Site({ siteKind, setSiteKind, scenario: s, scenarioLoading, nSites, removeSite, siteCost, setSiteCost, hasStage, focus }: Props) {
  if (!hasStage) return <p className="st-quiet">Placing a site is not available right now.</p>;
  const c = s?.counties.find((x) => x.area_id === focus) ?? s?.counties[0];
  const site = s?.sites[s.sites.length - 1];
  return (
    <>
      <div className="st-place">
        {(Object.keys(SITE) as SiteKind[]).map((k) => <button key={k} className="btn sm" aria-pressed={siteKind === k} onClick={() => setSiteKind(siteKind === k ? null : k)}><i className={`st-sitekey ${k}`} />{SITE[k]}</button>)}
        {nSites > 0 && <button className="btn sm quiet" onClick={removeSite}>Remove site</button>}
      </div>
      {siteKind && <p className="st-hint" role="status">Click the map where the {SITE[siteKind].toLowerCase()} goes. It snaps to the nearest municipality.</p>}
      {scenarioLoading && !s && <div className="skeleton" style={{ height: 120 }} />}
      {!scenarioLoading && nSites > 0 && !s && <p className="st-quiet">The scenario is not available right now.</p>}
      {s && site && (
        <>
          <dl className={"st-nums two" + (scenarioLoading ? " busy" : "")}>
            {c && <div><dt>{c.name_en ?? "County"}, km to treatment</dt><dd className="num">{int(Math.round(c.km_before))} → {int(Math.round(c.km_after))}<small> · {int(Math.round(c.km_before) - Math.round(c.km_after))} km saved</small></dd></div>}
            <div><dt>People closer</dt><dd className="num">{int(s.totals.people_closer)}</dd></div>
            {c && <div><dt>Share treated to cure</dt><dd className="num">{one(c.curative_pct_before)}% → {one(c.curative_pct_after.median)}%<small> · range {one(c.curative_pct_after.lo)} to {one(c.curative_pct_after.hi)}</small></dd></div>}
            <div><dt>Patients a year</dt><dd className="num">{r0(s.totals.extra_per_year.median)}<small> · range {r0(s.totals.extra_per_year.lo)} to {r0(s.totals.extra_per_year.hi)}</small></dd></div>
            <div>
              <dt><label htmlFor="st-cost">Cost a year</label> <KindTag kind="assumption" title={site.cost_basis_en ?? undefined} /></dt>
              <dd className="num">€ <input id="st-cost" className="st-cost-in num" type="number" min={0} step={50000} value={siteCost ?? s.totals.cost_eur_per_year ?? ""} onChange={(e) => setSiteCost(e.target.value === "" ? null : Math.max(0, Number(e.target.value)))} /></dd>
            </div>
            {s.totals.eur_per_extra_patient != null && <div><dt>Per extra patient</dt><dd className="num">{eurAbout(s.totals.eur_per_extra_patient)}{s.compare?.plan_eur_per_extra_patient != null && <small> · the plan: {eurAbout(s.compare.plan_eur_per_extra_patient)}</small>}</dd></div>}
          </dl>
          {s.assumption_en && <p className="st-fine on st-assume">{s.assumption_en}</p>}
        </>
      )}
    </>
  );
}

function Level({ level, setLevel, totalDots, bestDots, natPct, bestPct }: Props) {
  return (
    <>
      <div className="st-place">
        <button className="btn sm" aria-pressed={level === "national"} onClick={() => setLevel(level === "national" ? null : "national")}>Every county at the national share</button>
        <button className="btn sm" aria-pressed={level === "best"} onClick={() => setLevel(level === "best" ? null : "best")} disabled={!bestDots}>At the best quarter</button>
      </div>
      <dl className="st-nums">
        <div><dt>National share{natPct != null ? `, ${one(natPct)}%` : ""}</dt><dd className="num">{totalDots}<small> more a year treated to cure</small></dd></div>
        {bestDots > 0 && <div><dt>Best quarter{bestPct != null ? `, ${one(bestPct)}%` : ""}</dt><dd className="num">{bestDots}<small> more a year treated to cure</small></dd></div>}
      </dl>
      <p className="st-fine on">Arithmetic on measured values, not a forecast. <KindTag kind="measured" /></p>
    </>
  );
}

function Records({ name, myDots, unrec, setUnrec, hidden, auditEur }: Props) {
  if (!myDots) return <p className="st-quiet">{name} is at or above the national share: there is no gap to question.</p>;
  return (
    <>
      <p className="st-q">Of {name}'s {myDots}, how many were treated but not recorded?</p>
      <label className="st-slider">
        <span className="sr">Treated but not recorded, people a year</span>
        <input type="range" min={0} max={myDots} step={1} value={unrec} onChange={(e) => setUnrec(Number(e.target.value))} />
      </label>
      <dl className="st-nums">
        <div><dt>Treated, not recorded</dt><dd className="num">{unrec}</dd></div>
        <div><dt>Really missed</dt><dd className="num">{myDots - unrec}</dd></div>
        {hidden != null && <div><dt>Kello's estimate <KindTag kind="estimated" /></dt><dd className="num">{r0(hidden)}<small> a year not recorded</small></dd></div>}
      </dl>
      <p className="st-fine on">This is what the {auditEur != null ? `${eurx(auditEur)} ` : ""}chart audit settles.</p>
    </>
  );
}
