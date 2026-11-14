import { useCallback, useEffect, useState } from "react";
import { api, AreaMeta, SrcRef, useAsync, useFixtureCalls } from "./lib";
import MapView from "./MapView";
import CountyView from "./CountyView";
import PlanView from "./PlanView";
import SourcesDrawer from "./SourcesDrawer";
import Monday from "./Monday";
import Review from "./Review";
import StageView from "./stage/StageView";

type View = "map" | "county" | "plan" | "monday" | "review" | "run";
export type Lang = "en" | "fi";
/** Everything a link has to carry: #/plan/21?budget=1000000&lang=fi&objective=curative&without=sbrt_pathway */
interface Route { view: View; scope: string; budget: number; lang: Lang; objective: string | null; without: string[]; from?: "FI" | null }
const DEFAULT_BUDGET = 1_000_000;
/** Finland as a whole opens on the national plan the map and the Run show: the gap objective under a €5M ceiling. */
const NATIONAL_BUDGET = 5_000_000;
const budgetFor = (scope: string) => (scope === "FI" ? NATIONAL_BUDGET : DEFAULT_BUDGET);
const OBJECTIVES = ["curative", "deaths", "gap"];

function parseHash(): Route {
  const [path, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  const [v, s] = path.split("/");
  const q = new URLSearchParams(query);
  const b = q.get("budget") == null || q.get("budget") === "" ? NaN : Number(q.get("budget"));
  const scope = s || (v === "run" || !v ? "21" : "FI");
  return {
    // The first screen is the Run for Lapland; the map of every county is one tab away.
    view: v === "county" || v === "plan" || v === "monday" || v === "review" || v === "run" ? v : v ? "map" : "run", scope,
    budget: Number.isFinite(b) && b >= 0 ? Math.min(50_000_000, Math.round(b)) : budgetFor(scope),
    lang: q.get("lang") === "fi" ? "fi" : "en",
    objective: OBJECTIVES.includes(q.get("objective") ?? "") ? q.get("objective") : scope === "FI" && !Number.isFinite(b) ? "gap" : null,
    without: (q.get("without") ?? "").split(",").map((x) => x.replace(/[^a-z0-9_]/g, "")).filter(Boolean).slice(0, 20),
    from: q.get("from") === "FI" && s && s !== "FI" ? "FI" : null,
  };
}
function toHash(r: Route): string {
  const q = new URLSearchParams();
  if (r.view === "plan" || (r.view === "county" && r.budget !== budgetFor(r.scope))) q.set("budget", String(r.budget));
  if (r.view === "plan" || (r.view === "monday" && r.lang === "fi")) q.set("lang", r.lang);
  if (r.view !== "map" && r.objective) q.set("objective", r.objective);
  if (r.view !== "map" && r.without.length) q.set("without", r.without.join(","));
  if (r.view !== "map" && r.from === "FI" && r.scope !== "FI") q.set("from", "FI");
  if (r.view === "run") return `#/run/${r.scope}`;
  const qs = q.toString();
  return `#/${r.view}/${r.scope}${qs ? `?${qs}` : ""}`;
}

export function Loading({ label = "Loading", center = false }: { label?: string; center?: boolean }) {
  return <div className={"state" + (center ? " center" : "")} role="status"><span><span className="spin" />{label}…</span></div>;
}
/** Grey blocks in the shape of what is coming: `rows` are heights in px, or [height, width%]. */
export function Skeleton({ rows, label = "Loading" }: { rows: (number | [number, number])[]; label?: string }) {
  return (
    <div className="skel" role={label ? "status" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : true}>
      {rows.map((r, i) => <div key={i} className="skeleton" style={{ height: Array.isArray(r) ? r[0] : r, width: Array.isArray(r) ? `${r[1]}%` : "100%" }} />)}
    </div>
  );
}
export function Failed({ message, retry, center = false }: { message: string; retry?: () => void; center?: boolean }) {
  return (
    <div className={"state error" + (center ? " center" : "")} role="alert">
      <span>{message}</span>
      {retry && <button className="btn sm" onClick={retry}>Try again</button>}
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash);
  const [drawer, setDrawer] = useState<{ focus: SrcRef | null } | null>(null);
  const areas = useAsync<AreaMeta[]>(api.areas, []);
  const fixtureCalls = useFixtureCalls();
  // The county list fills the area picker; if it failed (after its retries), ask again a little later.
  useEffect(() => { if (!areas.error) return; const t = setTimeout(areas.reload, 5000); return () => clearTimeout(t); }, [areas.error]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    const on = (e: Event) => setDrawer({ focus: (e as CustomEvent<SrcRef | null>).detail ?? null });
    window.addEventListener("kello:source", on);
    return () => window.removeEventListener("kello:source", on);
  }, []);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  // Moving between views adds a history entry; changing budget or language rewrites the current one.
  const go = useCallback((view: View, scope?: string, section?: string) => {
    const cur = parseHash();
    const other = scope != null && scope !== cur.scope;   // a choice made for one county does not follow to the next
    // A county opened from the national page gets its own plan at the default budget, not the national one; the plan says so.
    const fromFI = other && cur.scope === "FI" && scope !== "FI";
    window.location.hash = toHash({ ...cur, view, scope: scope ?? cur.scope, ...(other ? { objective: null, without: [], from: null } : {}), ...(fromFI ? { budget: DEFAULT_BUDGET, from: "FI" } : {}), ...(other && scope === "FI" ? { budget: NATIONAL_BUDGET, objective: "gap" } : {}) });
    window.scrollTo(0, 0);
    // A step of the 90-second path lands on its own part of the county page once that part has drawn.
    if (section) {
      const t0 = performance.now();
      const look = () => { const el = document.getElementById(`sec-${section}`); if (el) { el.querySelector("details")?.setAttribute("open", ""); el.scrollIntoView({ block: "start", behavior: "smooth" }); } else if (performance.now() - t0 < 8000) setTimeout(look, 120); };
      setTimeout(look, 120);
    }
  }, []);
  const patch = useCallback((p: Partial<Route>) => {
    const next = { ...parseHash(), ...p };
    window.history.replaceState(null, "", toHash(next));
    setRoute(next);
  }, []);
  const setBudget = useCallback((budget: number) => patch({ budget, from: null }), [patch]);
  const setLang = useCallback((lang: Lang) => patch({ lang }), [patch]);
  const setObjective = useCallback((objective: string | null) => patch({ objective, without: [] }), [patch]);
  const setWithout = useCallback((without: string[]) => patch({ without }), [patch]);

  const sorted = [...(areas.data ?? [])].sort((a, b) => a.short_en.localeCompare(b.short_en));
  const tabs: [View, string][] = [["run", "Run"], ["map", "Map"], ["county", "County"], ["plan", "Plan"]];

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <b>
            <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="13" fill="none" stroke="#104281" strokeWidth="3" /><path d="M16 8v8l6 4" fill="none" stroke="#104281" strokeWidth="3" strokeLinecap="round" /></svg>
            Kello
          </b>
          <span>Where lung cancer patients are lost between diagnosis and treatment to cure, county by county</span>
        </div>
        <nav className="tabs" aria-label="Views">
          {tabs.map(([v, label]) => (
            <button key={v} aria-current={route.view === v || (v === "plan" && route.view === "monday") || (v === "county" && route.view === "review") ? "page" : undefined} onClick={() => go(v, v === "run" && route.view === "map" ? "21" : undefined)}>{label}</button>
          ))}
        </nav>
        <div className="spacer" />
        {fixtureCalls && <span className="badge" title={`Placeholder numbers until the real data and model are connected. Sample-backed: ${fixtureCalls}.`}>Sample data</span>}
        <label className="sr" htmlFor="scope">Area</label>
        <select id="scope" className="select" value={route.scope} onChange={(e) => go(route.view === "map" ? "county" : route.view, e.target.value)}>
          <option value="FI">Finland</option>
          {sorted.map((a) => <option key={a.id} value={a.id}>{a.short_en}</option>)}
        </select>
        <button className="btn srcbtn" onClick={() => setDrawer({ focus: null })} aria-haspopup="dialog">Sources<span className="wide"> &amp; method</span></button>
      </header>
      <main>
        {route.view === "run" && <StageView key={route.scope} scope={route.scope} areas={areas.data ?? []} open={(view, section) => go(view, route.scope, section)} openSources={() => setDrawer({ focus: null })} />}
        {route.view === "map" && <MapView onPick={(id, section) => go("county", id, section)} openPlan={(id) => go("plan", id)} areas={areas.data ?? []} />}
        {route.view === "county" && <CountyView key={route.scope} scope={route.scope} budget={route.budget} setBudget={setBudget} objective={route.objective} setObjective={setObjective} without={route.without} setWithout={setWithout} areas={areas.data ?? []} openPlan={() => go("plan")} openMonday={() => go("monday")} pick={(id) => go("county", id)} />}
        {route.view === "plan" && <PlanView key={route.scope} fromNational={route.from === "FI"} scope={route.scope} budget={route.budget} setBudget={setBudget} lang={route.lang} setLang={setLang} objective={route.objective} without={route.without} areas={areas.data ?? []} openCounty={() => go("county")} openMonday={() => go("monday")} />}
        {route.view === "monday" && <Monday key={route.scope} scope={route.scope} budget={route.budget} lang={route.lang} setLang={setLang} objective={route.objective} without={route.without} areas={areas.data ?? []} openPlan={() => go("plan")} openCounty={() => go("county")} />}
        {route.view === "review" && <Review key={route.scope} scope={route.scope} areas={areas.data ?? []} openPlan={() => go("plan")} openMonday={() => go("monday")} />}
      </main>
      {drawer && <SourcesDrawer scope={route.scope} focus={drawer.focus} onClose={closeDrawer} />}
    </div>
  );
}
