import { useEffect, useRef } from "react";
import EvidenceSearch from "./EvidenceSearch";
import { api, ArchiveCopy, chipText, int, isRegistry, KIND_HELP, KIND_LABEL, Kind, one, period, publisherOf, readerName, savedCopy, SrcRef, useAsync } from "./lib";
import { Failed, Loading } from "./App";

/**
 * A link to a cited page that still works when the registry site shows a robot check:
 * the saved copy in the Internet Archive when one exists, otherwise a plain line saying what to expect.
 */
export function SourceLink({ url, copies, label, full = false }: { url: string; copies?: ArchiveCopy[]; label?: string; full?: boolean }) {
  const copy = savedCopy(url, copies);
  let host = url;
  try { host = new URL(url).hostname.replace(/^www\./, ""); } catch { /* keep the raw text */ }
  const day = copy?.captured ? `${copy.captured.slice(6, 8).replace(/^0/, "")}.${copy.captured.slice(4, 6).replace(/^0/, "")}.${copy.captured.slice(0, 4)}` : null;
  return (
    <span className="srclink">
      <a className={full ? "url" : undefined} href={url} target="_blank" rel="noreferrer">{full ? url : label ?? host}</a>
      {copy?.copy_url ? <> · <a href={copy.copy_url + (url.match(/#.*$/)?.[0] ?? "")} target="_blank" rel="noreferrer">saved copy{day ? ` (${day})` : ""}</a></>
        : isRegistry(url) ? <span className="muted"> · the registry site asks your browser to pass a check first</span> : null}
    </span>
  );
}

const sameUrl = (a?: string | null, b?: string | null) => !!a && !!b && a.replace(/[#?].*$/, "") === b.replace(/[#?].*$/, "");

export default function SourcesDrawer({ scope, focus, onClose }: { scope: string; focus: SrcRef | null; onClose: () => void }) {
  const src = useAsync(api.sources, []);
  const area = useAsync(() => api.area(scope), [scope]);
  const reader = useAsync(api.reader, []);
  const science = useAsync(api.science, []);
  const charts = useAsync(api.readCharts, []);
  const kept = useAsync(api.readKept, []);
  const archive = useAsync(api.archive, []);
  const copies = archive.data?.copies;
  const closeRef = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && panel.current) {
        const f = panel.current.querySelectorAll<HTMLElement>("a[href], button, [tabindex]:not([tabindex='-1'])");
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);

  const entries = Object.entries(src.data?.sources ?? {});
  const docs = reader.data?.documents ?? [];
  const analyses = science.data?.analyses ?? [];
  const keptRows = kept.data?.rows ?? [];
  const acc = charts.data?.accuracy ?? null;
  // One count per kind, computed from the reader's own records: values read, and how many were found again in the source.
  const nRead = reader.data?.rows ?? 0;
  const nOk = docs.reduce((n, d) => n + (d.verified ?? 0), 0);
  const model = readerName(docs[0]?.read_by) ?? "";
  const check = area.data?.consistency_check;
  // The registry entry behind the number that was clicked, if we can tell which one it is.
  const hit = focus ? entries.find(([id, s]) => id === focus.source_id || sameUrl(s.url, focus.source_url)) : undefined;
  const url = focus?.source_url ?? hit?.[1].url ?? null;
  const pageUrl = url && focus?.page != null && /\.pdf($|[?#])/i.test(url) ? `${url}#page=${focus.page}` : url;
  const isHit = (id: string, u?: string | null) => !!focus && (id === focus.source_id || sameUrl(u, focus.source_url));
  useEffect(() => {
    if (!focus || !src.data) return;
    const t = setTimeout(() => panel.current?.querySelector(".scroll")?.scrollTo({ top: 0 }), 0);
    return () => clearTimeout(t);
  }, [focus, src.data]);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="dr-title" ref={panel}>
        <header>
          <h2 id="dr-title">Sources &amp; method</h2>
          {src.data?.fixture && <span className="tag sample">Sample data</span>}
          <button className="btn sm" onClick={onClose} ref={closeRef}>Close</button>
        </header>
        <div className="scroll">
          {focus && (
            <section className={`focus ${focus.kind}`} aria-label="The number you selected">
              <div className="fk"><span className={`chip ${focus.kind} still`}><i aria-hidden="true" />{chipText(focus)}</span></div>
              {focus.quote && <blockquote lang="fi" className="fquote">{focus.page != null && focus.page !== "" && <span className="fpage num">Page {focus.page}</span>}“{focus.quote}”<cite>Verbatim from the source{focus.read_by ? `; read by ${readerName(focus.read_by)}` : ""}</cite></blockquote>}
              {(focus.what || focus.value) && <h3>{focus.what}{focus.value ? <>: <span className="num">{focus.value}</span></> : null}</h3>}
              {focus.kind === "estimated" && <p>Kello's own arithmetic on published figures, not a number taken from a register.{focus.note ? " How it is built:" : " See the method below."}</p>}
              {focus.kind === "assumption" && <p>Set by hand where no public figure exists. Replace it with the county's own number before using it in a decision.</p>}
              {focus.kind === "reported" && <p>Reported in the press, not a published national statistic. Kello shows it for context and does not build on it.</p>}
              {focus.note && focus.kind !== "reported" && <p>{focus.note}</p>}
              {(focus.kind === "measured" || focus.kind === "reported") && (
                <dl className="fmeta">
                  {(hit?.[1].title || publisherOf(focus)) && <div><dt>Source</dt><dd>{hit?.[1].title ?? publisherOf(focus)}{hit?.[1].publisher ? `, ${hit[1].publisher}` : ""}</dd></div>}
                  {focus.period && <div><dt>Period</dt><dd className="num">{period(focus.period)}</dd></div>}
                  {focus.page != null && focus.page !== "" && <div><dt>Page</dt><dd className="num">{focus.page}</dd></div>}
                  {focus.read_by && <div><dt>Read by</dt><dd>{readerName(focus.read_by)}; number and quote checked against the page</dd></div>}
                </dl>
              )}
              {pageUrl && <p className="small"><SourceLink url={pageUrl} copies={copies} label={focus?.page != null && focus.page !== "" ? `Open page ${focus.page} on ${publisherOf(focus) ?? "the source site"}` : `Open on ${publisherOf(focus!) ?? "the source site"}`} /></p>}
            </section>
          )}
          {reader.error && <section><Failed message={reader.error} retry={reader.reload} /></section>}
          {nRead > 0 && (
            <section>
              <p className="first-line num"><b>{model || "Gemini"} read {int(nRead)} values</b> from registry PDFs and charts, each with page and quote; <b>{int(nOk)}</b> re-confirmed in the source, <b>{int(nRead - nOk)}</b> flagged and shown as unverified.</p>
            </section>
          )}
          <section>
            <h3>What you are looking at</h3>
            <p>Kello shows where each wellbeing services county loses lung cancer patients between diagnosis and treatment that aims to cure, and what closes that gap. The care path comes from the Finnish Cancer Registry's own county figures. The plan is Kello's: a list of actions with an owner, a cost, a first step and a measure, chosen by stated rules. Public aggregate data only; no patient-level data.</p>
          </section>
          <EvidenceSearch scope={scope} scopeName={area.data?.area?.short_en ?? null} />
          <section>
            <h3>Three kinds of number</h3>
            <ul style={{ listStyle: "none", paddingLeft: 0 }}>
              {(["measured", "estimated", "assumption"] as Kind[]).map((k) => <li key={k}><i className={`k k-${k}`} /><b style={{ color: "var(--ink)" }}>{KIND_LABEL[k]}.</b> {KIND_HELP[k]}.</li>)}
            </ul>
            <p>An estimate is never shown as a measurement. Every estimate carries a range, written like 0–7.7. Every number on screen has a chip that opens this panel at its source.</p>
          </section>
          {docs.length > 0 && (
            <section>
              <h3>How Kello reads reports</h3>
              <p>The Finnish Cancer Registry publishes county results as PDF reports and interactive pages with no API. Gemini reads each document page by page and returns every number with its page and a verbatim quote. A second pass looks for each number again on its page.</p>
              <p><b style={{ color: "var(--ink)" }}>Not verified</b> means the second pass did not find the number again in the same words, usually because the page shows it in a chart or a rounded table cell. Those values stay in Kello, marked as unverified wherever they appear.</p>
              <table className="t" style={{ marginTop: 10 }}>
                <thead><tr><th>Document read by Gemini</th><th className="n">Values read</th><th className="n">Re-confirmed</th><th className="n">Not verified</th></tr></thead>
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.url} className={isHit(d.source_id ?? "", d.url) ? "hit" : ""}>
                      <td><b>{d.title ?? d.url}</b>{d.publisher ? `, ${d.publisher}` : ""}<br /><SourceLink url={d.url} copies={copies} full /></td>
                      <td className="n num"><b>{d.rows}</b></td>
                      <td className="n num">{d.verified ?? "–"}</td>
                      <td className="n num">{d.verified != null ? d.rows - d.verified : "–"}</td>
                    </tr>
                  ))}
                  <tr><td><b>All four</b></td><td className="n num"><b>{int(nRead)}</b></td><td className="n num"><b>{int(nOk)}</b></td><td className="n num"><b>{int(nRead - nOk)}</b></td></tr>
                </tbody>
              </table>
              <p className="small" style={{ marginTop: 8 }}>These are values read by Gemini. The “Values in Kello” column further down counts everything Kello takes from a source, including tables that could be read directly.</p>
              {acc && (
                <>
                  <h3 style={{ marginTop: 16 }}>Numbers read off a chart</h3>
                  <p>{acc.what} Gemini read the {acc.rows} values off the bars ({acc.figure}).
                    {acc.check_a_blind_read_vs_table ? ` To see how accurate that is, we took a chart of the same design whose numbers are printed, painted the numbers out and let Gemini read it: ${acc.check_a_blind_read_vs_table.n} values, off by ${one(acc.check_a_blind_read_vs_table.mean_abs_error_pp)} percentage points on average and ${one(acc.check_a_blind_read_vs_table.max_abs_error_pp)} at most.` : ""}
                    {acc.check_b_county_values_vs_pixel_measure ? ` Each county value was also measured from the colours of the picture itself: ${acc.check_b_county_values_vs_pixel_measure.n} values, ${one(acc.check_b_county_values_vs_pixel_measure.mean_abs_error_pp)} points apart on average, ${one(acc.check_b_county_values_vs_pixel_measure.max_abs_error_pp)} at most.` : ""}
                    {" "}Values read off an axis stay marked as unverified.</p>
                </>
              )}
              <h3 style={{ marginTop: 16 }}>Added by you, unverified</h3>
              {keptRows.length === 0 ? <p>Nothing yet. In the Plan view, “Read a report” lets you read any report and add single values to Kello; they are listed here.</p> : (
                <table className="t" style={{ marginTop: 6 }}>
                  <thead><tr><th>Value</th><th>What</th><th>From</th></tr></thead>
                  <tbody>
                    {keptRows.map((k, i) => (
                      <tr key={i}>
                        <td className="num" style={{ whiteSpace: "nowrap" }}><b>{k.value ?? "–"}</b> {k.unit}</td>
                        <td>{k.label_en ?? k.label}{k.area_name ? `, ${k.area_name}` : ""}{k.period ? `, ${k.period}` : ""}{k.quote ? <div className="muted quote">p. {k.page ?? "–"} · “{k.quote}”</div> : null}</td>
                        <td>{k.source_title ?? "–"}<br /><a className="url" href={k.source_url ?? k.url ?? "#"} target="_blank" rel="noreferrer">{k.source_url ?? k.url}</a><div className="muted small">added by you, unverified</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
          <section>
            <h3>Method, in plain language</h3>
            <ol>
              <li><b>The care path.</b> For each county the registry publishes how many lung cancer patients were staged, discussed by a team, treated to cure, operated, given other treatment or have no treatment on record. Kello shows each share with its 95% range, next to Finland and the best county.</li>
              <li><b>Beyond chance.</b> A small county's share moves a lot from one period to the next. Kello draws the range that chance alone gives a county of each size around the national share, and only calls a county lower or higher when it is outside that range.</li>
              <li><b>Missing patients.</b> The county's share against the national share, times its patients a year. It is arithmetic on registry shares: it does not say which patients could have been treated to cure.</li>
              <li><b>Expected share.</b> What the county's share would be if only the age of its residents mattered. Stage, fitness and other illness are not published by county and cannot be adjusted for.</li>
              <li><b>Actions.</b> Each action has an assumed effect with a low and a high end, taken from published studies in other health systems, a cost assumption and an owner. No trial has measured the access effects in Finland, so their low end is zero.</li>
              <li><b>The plan.</b> For a budget, Kello chooses the actions that add the most patients treated to cure per euro, within stated rules. Every rule is listed on the county page under “How this was chosen”.</li>
            </ol>
            <h3 style={{ marginTop: 16 }}>The estimated clock, and a check that did not confirm it</h3>
            <p>Kello also estimates the days from first symptom to treatment by county. Only diagnosis to treatment is measured, and only for the five university hospital areas; the earlier steps are national figures scaled by public county indicators with assumed weights. It is kept as a secondary view (“Time (estimated)”) and is not used in the plan.</p>
            {check?.summary_en && <p><b style={{ color: "var(--ink)" }}>The check.</b> {check.what_en} {check.summary_en}</p>}
            {(check?.results ?? []).length > 0 && <ul>{check!.results!.map((r) => <li key={r.indicator}>{r.sentence_en}</li>)}</ul>}
          </section>
          {analyses.length > 0 && (
            <section>
              <h3>Reproducible analyses</h3>
              <p>Each analysis was run from a script by an AI research agent (Claude Science). Each one keeps its figures, data, code and every permission it was given, so the result can be re-run.</p>
              <ul className="sci">
                {analyses.map((a) => (
                  <li key={a.id}><b>{a.title}</b>
                    {a.finding_en && <p>{a.finding_en}</p>}
                    {a.figure_url && <a href={a.figure_url} target="_blank" rel="noreferrer"><img src={a.figure_url} alt={a.figure_alt ?? a.title} loading="lazy" /></a>}
                    <details>
                      <summary>Full answer, code and data</summary>
                      <div>{a.files.map((f) => <a key={f.url} href={f.url} target="_blank" rel="noreferrer">{f.name.split("/").pop()}</a>)}</div>
                    </details>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h3>Limits</h3>
            <ul>
              <li>County-level aggregates cannot show cause. A county with a low share treated to cure is a place to look, not proof of worse care.</li>
              <li>County shares are not adjusted for stage, fitness or other illness: the registry does not publish those by county.</li>
              <li>Part of a gap can be treatment that was given but not recorded. Where the registry's own figures suggest that, the county is flagged.</li>
              <li>Days from diagnosis to treatment are published for the five university hospital areas, not for each county.</li>
              <li>Effects come from studies in other health systems. No trial has measured them in a Finnish county, and the low end of the access effects is zero.</li>
              <li>Costs are assumptions and should be replaced with the county's own figures.</li>
              <li>Åland has too few patients for the registry to publish its care path.</li>
              <li>Nothing here predicts the course of an individual patient.</li>
              <li>Three passages of the plan are written by a language model from these numbers, then checked by a second pass that removes any sentence without a source. The table, the targets and the totals are filled in by code.</li>
            </ul>
          </section>
          <section>
            <h3>Data sources</h3>
            {src.error ? <Failed message={src.error} retry={src.reload} /> : !src.data ? <Loading label="Loading sources" /> : entries.length === 0 ? <p>No sources are registered yet.</p> : (
              <>
                <p><b style={{ color: "var(--ink)" }}>Opened:</b> {(src.data.status_help?.opened ?? "we read the number on this page.").replace(/^opened:\s*/i, "")} <b style={{ color: "var(--ink)" }}>Listed:</b> {(src.data.status_help?.listed ?? "we downloaded it but took no number from it.").replace(/^listed:\s*/i, "")} Sources that Kello takes numbers from come first.</p>
                <table className="t srct" style={{ marginTop: 10 }}>
                  <thead><tr><th>Source</th><th className="n">Values in Kello</th><th>Retrieved</th><th>Status</th></tr></thead>
                  <tbody>
                    {[...entries].sort(([a, x], [b, y]) => Number(isHit(b, y.url)) - Number(isHit(a, x.url))).map(([id, s]) => {
                      const status = s.status ?? (s.verified === false ? "listed" : s.retrieved_at ? "opened" : null);
                      return (
                        <tr key={id} className={(isHit(id, s.url) ? "hit" : "") + (status === "listed" ? " listed" : "")}>
                          <td><b>{s.title ?? id}</b>{s.publisher ? `, ${s.publisher}` : ""}<br />{s.url ? <SourceLink url={s.url} copies={copies} full /> : <span className="muted">no URL</span>}{s.notes && <div className="muted" style={{ fontSize: 12.5 }}>{s.notes.replace(/^\d+ values parsed[^.]*\.\s*/, "")}</div>}</td>
                          <td className="n num">{s.values ? s.values : "–"}</td>
                          <td className="num" style={{ whiteSpace: "nowrap" }}>{s.retrieved_at ? String(s.retrieved_at).slice(0, 10) : "–"}</td>
                          <td style={{ whiteSpace: "nowrap" }}>{status === "opened" ? "Opened" : status === "listed" ? "Listed" : "–"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}
          </section>
          {src.data && src.data.evidence.length > 0 && (
            <section>
              <h3>Evidence behind the actions</h3>
              <p><b style={{ color: "var(--ink)" }}>Opened:</b> we read the page and the quoted words are on it. <b style={{ color: "var(--ink)" }}>Not verified:</b> the claim is listed with its link, but we have not confirmed the wording on the page ourselves.</p>
              <table className="t" style={{ marginTop: 10 }}>
                <thead><tr><th>Action</th><th>Claim</th><th>Status</th></tr></thead>
                <tbody>
                  {src.data.evidence.map((e, i) => (
                    <tr key={i}>
                      <td>{e.intervention ?? e.intervention_id}</td>
                      <td>{e.kind === "null_result" && <b>No effect found: </b>}{e.claim}{e.year ? ` (${e.year}${e.design ? `, ${e.design}` : ""})` : ""}<br />{e.url ? <a className="url" href={e.url} target="_blank" rel="noreferrer">{e.url}</a> : <span className="muted">no URL</span>}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{e.verified === true ? "Opened" : "Not verified"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
