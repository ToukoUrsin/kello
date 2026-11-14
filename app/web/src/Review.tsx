import { useEffect, useState } from "react";
import { api, AreaMeta, eurx, one, useAsync } from "./lib";
import { Failed, Skeleton } from "./App";

/* One screen to put in front of a clinician: the claim, where on the care path, what we would start with, and three
   questions. Their answers stay in this browser until "Copy answers" is pressed; nothing is sent anywhere. */

type Ans = "yes" | "partly" | "no" | "";
interface Form { gap: Ans; gapNote: string; acts: Ans; actsNote: string; missing: string; quote: string; name: string; role: string; consent: boolean }
const EMPTY: Form = { gap: "", gapNote: "", acts: "", actsNote: "", missing: "", quote: "", name: "", role: "", consent: false };
const key = (scope: string) => `kello-review-${scope}`;
const load = (scope: string): Form => { try { return { ...EMPTY, ...JSON.parse(localStorage.getItem(key(scope)) ?? "{}") }; } catch { return EMPTY; } };

function Pick({ value, set, label }: { value: Ans; set: (a: Ans) => void; label: string }) {
  const opts: [Ans, string][] = [["yes", "Yes"], ["partly", "Partly"], ["no", "No"]];
  return <div className="seg" role="group" aria-label={label}>{opts.map(([v, l]) => <button key={v} type="button" aria-pressed={value === v} onClick={() => set(value === v ? "" : v)}>{l}</button>)}</div>;
}

export default function Review({ scope, areas, openPlan, openMonday }: { scope: string; areas: AreaMeta[]; openPlan: () => void; openMonday: () => void }) {
  const area = useAsync(() => api.area(scope), [scope]);
  const opt = useAsync(() => api.optimize(scope, 1_000_000, "curative"), [scope]);
  const [f, setF] = useState<Form>(() => load(scope));
  const [copied, setCopied] = useState(false);
  useEffect(() => { try { localStorage.setItem(key(scope), JSON.stringify(f)); } catch { /* private window: the form still works */ } }, [f, scope]);
  const up = (p: Partial<Form>) => setF((x) => ({ ...x, ...p }));
  if (scope === "FI") return <div className="review"><p className="muted">Pick a county in the menu above: this page is about one county's plan.</p></div>;
  if ((area.loading && !area.data) || (opt.loading && !opt.data)) return <div className="review"><Skeleton rows={[60, 120, 240]} /></div>;
  if (!area.data || !opt.data) return <div className="review"><Failed message={area.error ?? opt.error ?? "This county could not be loaded."} retry={() => { area.reload(); opt.reload(); }} /></div>;
  const name = areas.find((a) => a.id === scope)?.short_en ?? opt.data.scope_en ?? scope;
  const steps = area.data.pathway?.steps ?? [];
  const cur = area.data.care_path?.stages?.find((s) => s.id === "curative");
  const miss = area.data.care_path?.missing_patients?.per_year;
  const pilot = opt.data.pilot;
  const zero = opt.data.chosen.find((c) => (opt.data!.ui?.step_zero ?? []).includes(c.intervention_id));
  const first = [zero, ...(pilot?.actions ?? []).map((id) => opt.data!.chosen.find((c) => c.intervention_id === id))].filter((c): c is NonNullable<typeof c> => !!c);
  const shown = first.length ? first : opt.data.chosen.slice(0, 3);
  const word = (a: Ans) => (a ? a[0].toUpperCase() + a.slice(1) : "no answer");
  const text = [
    `Kello review, ${name}, ${new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}`,
    `1. Is the gap at the treatment decision? ${word(f.gap)}${f.gapNote ? `. ${f.gapNote}` : ""}`,
    `2. Are these the right actions to start with? ${word(f.acts)}${f.actsNote ? `. ${f.actsNote}` : ""}`,
    `3. What public data cannot show: ${f.missing || "no answer"}`,
    `In their words: ${f.quote || "none"}`,
    `Name and role: ${[f.name, f.role].filter(Boolean).join(", ") || "not given"}`,
    `May be shown with their name on Kello's first screen: ${f.consent ? "YES" : "NO"}`,
  ].join("\n");
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch {
      const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    setCopied(true); setTimeout(() => setCopied(false), 2500);
  };
  return (
    <div className="review">
      <section className="rclaim" aria-label="The claim">
        <span className="eyebrow">For a clinician's eye · {name} · public registry data 2019–2023</span>
        {cur?.value != null && cur.national != null
          ? <h1>Of 100 lung cancer patients in {name}, <b className="num">{one(cur.value)}</b> get treatment that aims to cure. In Finland, <b className="num">{one(cur.national)}</b>.{miss ? <> That is about <b className="num">{Math.round(miss)}</b> patients a year.</> : null}</h1>
          : <h1>{name}: lung cancer patients treated to cure</h1>}
        {steps.length > 0 && <>
          <h2>Where on the care path</h2>
          <ol className="rsteps">{steps.map((s) => <li key={s.id} className={s.verdict ?? ""}><span>{s.label_en}</span><b>{s.verdict_en}</b></li>)}</ol>
        </>}
        <h2>What we would start with</h2>
        <ol className="racts">{shown.map((c) => (
          <li key={c.intervention_id}><div><b>{c.name_en}</b><span>{c.owner_en}</span></div><span className="num">{eurx(c.eur)}<small> a year</small></span></li>
        ))}</ol>
        {pilot?.effect?.curative_share_now_pct != null && pilot.effect.curative_share_after_pct != null &&
          <p className="small muted">Our model's estimate for the two actions: {one(pilot.effect.curative_share_now_pct)}% → {one(pilot.effect.curative_share_after_pct)}% treated to cure by {pilot.effect.by_year ?? 2028}. No trial has measured this; the range starts at zero.</p>}
        <p className="rlinks noprint"><button className="btn sm" onClick={openMonday}>Who does what on Monday</button><button className="btn sm" onClick={openPlan}>The one-page plan</button></p>
      </section>
      <form className="rform" aria-label="Three questions" onSubmit={(e) => e.preventDefault()}>
        <h2>Three questions. Two minutes.</h2>
        <div className="rq"><label>1. Is the gap where the data says: at the treatment decision, not in delays?</label><Pick value={f.gap} set={(gap) => up({ gap })} label="Is the gap at the treatment decision" />
          <input type="text" value={f.gapNote} onChange={(e) => up({ gapNote: e.target.value })} placeholder="What would you add or correct?" aria-label="Comment on question 1" /></div>
        <div className="rq"><label>2. Are these the right actions to start with?</label><Pick value={f.acts} set={(acts) => up({ acts })} label="Are these the right actions" />
          <input type="text" value={f.actsNote} onChange={(e) => up({ actsNote: e.target.value })} placeholder="What would you start with instead?" aria-label="Comment on question 2" /></div>
        <div className="rq"><label htmlFor="rmissing">3. What does a clinician know here that public data cannot show?</label>
          <input id="rmissing" type="text" value={f.missing} onChange={(e) => up({ missing: e.target.value })} placeholder="Stage, fitness, patients who decline, something else" /></div>
        <div className="rq rquote"><label htmlFor="rquote">In your words, one sentence</label>
          <textarea id="rquote" rows={2} value={f.quote} onChange={(e) => up({ quote: e.target.value })} placeholder="What you would say about this to a county's chief physician" />
          <div className="rwho"><input type="text" value={f.name} onChange={(e) => up({ name: e.target.value })} placeholder="Name" aria-label="Name" /><input type="text" value={f.role} onChange={(e) => up({ role: e.target.value })} placeholder="Role, organisation" aria-label="Role and organisation" /></div>
          <label className="rconsent"><input type="checkbox" checked={f.consent} onChange={(e) => up({ consent: e.target.checked })} /> Kello may show this sentence with my name on its first screen.</label></div>
        <div className="rsend"><button type="button" className="btn primary" onClick={copy}>{copied ? "Copied" : "Copy answers"}</button><button type="button" className="btn quiet" onClick={() => setF(EMPTY)}>Clear</button>
          <span className="small muted">Stays on this device until copied. Nothing is sent.</span></div>
      </form>
    </div>
  );
}
