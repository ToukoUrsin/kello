import { useEffect, useRef, useState } from "react";
import { api, EvidenceResult, int, useAsync } from "./lib";

const ROLE: Record<string, string> = { in_use: "Read for: is it in place here?", effect: "Read for: does it work? A study elsewhere", context: "Background" };
/** A Finnish word carries its English meaning, so a reader who knows no Finnish can still try it. */
const TRY: [string, string?][] = [["sädehoito", "radiotherapy"], ["stereotaktinen", "stereotactic"], ["MDT"], ["surgery"]];

/** Search the sentences the web checks quoted from public pages. MongoDB Atlas Search when the database answers;
 *  a word match over the stored copy when it does not. The line under the results says which. */
export default function EvidenceSearch({ scope, scopeName }: { scope: string; scopeName?: string | null }) {
  const stats = useAsync(api.evidenceStats, []);
  const [q, setQ] = useState("");
  const [only, setOnly] = useState(false);
  const [res, setRes] = useState<EvidenceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const turn = useRef(0);
  const county = scope !== "FI" && scopeName ? scopeName : null;

  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) { setRes(null); setBusy(false); return; }
    const mine = ++turn.current;
    setBusy(true);
    const t = setTimeout(() => {
      api.evidenceSearch(text, only && county ? scope : null).then((r) => { if (turn.current === mine) { setRes(r); setBusy(false); } });
    }, 250);
    return () => clearTimeout(t);
  }, [q, only, scope, county]);

  const s = stats.data;
  const atlas = (res?.backend ?? s?.backend) === "mongodb_atlas";
  const n = res?.hits.length ?? 0;
  return (
    <section className="ev">
      <h3>Search what the hospitals' own pages say</h3>
      <p>Every web check quotes sentences word for word from public pages{s ? <>: <span className="num">{int(s.quotes)}</span> sentences behind <span className="num">{int(s.checks)}</span> checks in <span className="num">{int(s.counties)}</span> counties</> : null}. Search them in Finnish or English.</p>
      <div className="ev-bar">
        <label className="sr" htmlFor="ev-q">Search the quoted sentences</label>
        <input id="ev-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="A word, such as sädehoito" autoComplete="off" spellCheck={false} />
        {county && <label className="ev-only"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Only {county}</label>}
      </div>
      <div className="ev-try">Try: {TRY.map(([w, en]) => <button key={w} onClick={() => setQ(w)} title={en ? `Finnish for ${en}` : undefined}><span lang={en ? "fi" : undefined}>{w}</span>{en ? <em> {en}</em> : null}</button>)}</div>
      {res && (
        <div className={"ev-res" + (busy ? " busy" : "")} aria-live="polite">
          <p className="ev-sum num">{n === 0 ? `No quoted sentence matches "${res.query}".` : `${n} ${n === 1 ? "sentence" : "sentences"}${res.counties.length ? `, quoted in the checks of ${res.counties.length} ${res.counties.length === 1 ? "county" : "counties"}` : ""}`}</p>
          <ol>
            {res.hits.map((h, i) => (
              <li key={i}>
                <q lang={/[äö]/i.test(h.quote) ? "fi" : undefined}>{h.parts.map((p, k) => (p.hit ? <mark key={k}>{p.t}</mark> : p.t))}</q>
                <span className="ev-meta">
                  <a href={h.url} target="_blank" rel="noreferrer">{h.domain}</a>
                  <span>{ROLE[h.about] ?? ROLE.context}</span>
                  <span>{h.areas.map((a) => a.name).join(", ")}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
      <p className="ev-foot">
        {atlas
          ? <>Search runs on MongoDB Atlas Search with Finnish and English word forms: <i lang="fi">matka</i> also finds <i lang="fi">matkan</i>.{s?.runs ? <> Atlas also keeps every live web check a visitor runs (<span className="num">{int(s.runs)}</span> so far); the answer on screen stays the stored one.</> : null}</>
          : <>The database is not answering, so this is a plain word match over the stored copy of the same sentences.</>}
      </p>
    </section>
  );
}
