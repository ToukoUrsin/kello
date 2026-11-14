// One line for the study an action's effect size comes from: the sentence, then a link (never a raw URL).
export function StudyLine({ text, label, linkLabel }: { text: string; label: string; linkLabel: string }) {
  const m = text.match(/^(.*?)(?:\s*·\s*)?(https?:\/\/\S+)\s*$/);
  const body = (m ? m[1] : text).replace(/^Evidence:\s*/i, "").trim();
  return (
    <>
      <b>{label}</b> {body}
      {m && <> <a className="studylink" href={m[2]} target="_blank" rel="noreferrer">{linkLabel}</a></>}
    </>
  );
}
