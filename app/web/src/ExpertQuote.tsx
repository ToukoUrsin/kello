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
  return (
    <figure className="expert" aria-label={lang === "fi" ? "Asiantuntijan arvio" : "Expert review"}>
      <span className="eyebrow">{lang === "fi" ? "Asiantuntijan arvio" : "Reviewed by"}</span>
      <blockquote>“{quote}”</blockquote>
      <figcaption><b>{r.name}</b>{who ? `, ${who}` : ""}{day ? <span className="muted"> · {day}</span> : null}</figcaption>
    </figure>
  );
}
