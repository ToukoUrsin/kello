"""Build data/processed/gemini_extracted.jsonl from the saved read_report() results."""
import collections, json, re, sys
from pathlib import Path
from integrations import gemini_reader as g

ROOT = Path(__file__).resolve().parents[3]
# build_extracted.py [raw folder] [output file]: the defaults are the shipped ones (see build_raw_reads.py)
RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/raw/gemini"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/processed/gemini_extracted.jsonl"
A = "https://syoparekisteri.fi/assets/themes/ssy3/factsheets/keuhkosyoparaportti.html"
B = "https://syoparekisteri.fi/assets/files/2024/12/Keuhkosyopa_Suomessa.pdf"
C = "https://tilastot.syoparekisteri.fi/syovat/"
D = "https://ihe.se/app/uploads/2026/04/IHE-Cancer-Dashboard-Finland_.pdf"
SRC = [("a", A, "fi", ["a_cases", "a_stage", "a_time", "a_histhva", "a_stagehva", "a_treatA", "a_treatB"]),
       ("b", B, "fi", ["b_pdf"]),
       ("c", C, "fi", ["c2_shiny_0", "c2_shiny_1", "c2_shiny_2", "c_shiny_3"]),
       ("d", D, "en", ["d_ihe"])]

def sex(row):
    t = f" {row.get('label_en') or ''} {row.get('label_fi') or ''} ".lower()
    if re.search(r"\b(women|female|females|naiset|nainen|naisilla|naisten)\b", t) and not re.search(r"\b(men and women|both sexes)\b", t):
        if re.search(r"\b(men|male|males|miehet|mies|miehillä|miesten)\b", t):
            return "all"
        return "women"
    if re.search(r"\b(men|male|males|miehet|mies|miehillä|miesten)\b", t):
        return "men"
    return "all"

rows, seen, stats = [], set(), {}
for tag, url, lang, names in SRC:
    n_vals = n_rows = 0
    for name in names:
        f = RAW / f"{name}.json"
        if not f.exists() or not f.stat().st_size:
            print("MISSING", name, file=sys.stderr); continue
        res = json.load(open(f))
        for r in (res if isinstance(res, list) else [res]):
            n_vals += len(r["extracted"])
            for row in g.to_rows(r, source_url=url, lang=lang):
                key = (url, row["area_id"], row["indicator"], row["period"], row["value"], row["label_en"])
                if key in seen:
                    continue
                seen.add(key)
                if row["indicator"] == "lung_days_diagnosis_to_treatment":
                    t = (row["label_en"] or "").lower()
                    for word, suf in (("surgery", "surgery"), ("radiotherapy", "radiotherapy"), ("drug", "drug_therapy")):
                        if word in t:
                            row["indicator"] = "lung_days_diagnosis_to_" + suf
                            break
                row["period"] = re.sub(r"\s*[–—]\s*", "-", str(row["period"] or ""))  # one spelling of a range, whichever dash the report used
                row["sex"] = sex(row)
                row["source"] = tag
                rows.append(row); n_rows += 1
    stats[tag] = (n_vals, n_rows)
out = OUT
out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
print("rows", len(rows), stats)
county = lambda a: a.isdigit()
for tag, *_ in SRC:
    cov = collections.defaultdict(set)
    for r in rows:
        if r["source"] == tag and county(r["area_id"]):
            cov[r["indicator"]].add(r["area_id"])
    print(tag, "county coverage:", {k: len(v) for k, v in sorted(cov.items())})
print("verified", collections.Counter((r["source"], r["verified"]) for r in rows))
print("lung indicators:", sorted({r["indicator"] for r in rows if r["indicator"].startswith("lung_")}))
print("other indicators:", len({r["indicator"] for r in rows if not r["indicator"].startswith("lung_")}))
