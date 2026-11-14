import { api, useAsync } from "./lib";

/** Words of a named clinician or sponsor expert who has looked at this plan. Drawn only when the server has an entry
 *  with their consent (data/processed/expert_review.json); until then nothing is shown. */
export default function ExpertQuote({ scope, lang = "en" }: { scope?: string; lang?: "en" | "fi" }) {
  const s = useAsync(api.expertReview, []);
  const all = s.data?.reviews ?? [];
  const r = (scope ? all.find((x) => x.scope === scope) : null) ?? (scope && scope !== "FI" ? null : all[0]) ?? null;
  if (!r) return null;
  const quote = (lang === "fi" ? r.quote_fi : null) ?? r.quote_en;
  const who = [r.role, r.org].filter(Boolean).join(", ");
  const day = r.date ? new Date(`${r.date}T12:00:00`).toLocaleDateString(lang === "fi" ? "fi-FI" : "en-GB", { day: "numeric", month: "long", year: "numeric" }) : null;
  const initials = r.name.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <figure className="expert" aria-label={lang === "fi" ? "Asiantuntijan arvio" : "Reviewed by"}>
      <blockquote><span className="qm" aria-hidden="true">“</span>{quote}”</blockquote>
      <figcaption>
        <span className="avatar" aria-hidden="true">{initials}</span>
        <span className="whois">
          <span><span className="muted">{lang === "fi" ? "Arvioinut" : "Reviewed by"}</span> <b>{r.name}</b></span>
          <span className="muted">{who}{who && day ? " · " : ""}{day}</span>
        </span>
      </figcaption>
    </figure>
  );
}
