#!/usr/bin/env python3
"""Build film/src/data/film.json from the repo's own data, so nothing on screen is typed by hand.

  map      data/processed/areas.geojson (transverse Mercator on 27°E, fitted to a 1000-unit-high box)
  rows     data/processed/gemini_extracted.jsonl (the values Gemini read, with page and quote)
  facts    the LIVE app ($KELLO_BASE, default 127.0.0.1:8742): POST /api/optimize {scope 21, 1M, curative},
           /api/plan/21, /api/areas/21, /api/verify/latest, /api/reader — the same calls the app makes

Run: python3 film/scripts/make-data.py   (stdlib only). It fails if a number the script speaks is not in the data.
"""
import json
import math
import os
import time
import urllib.request
from pathlib import Path

FILM = Path(__file__).resolve().parent.parent
REPO = FILM.parent


def tm(lon, lat, lon0=27.0):
    la, dl = math.radians(lat), math.radians(lon - lon0)
    b = math.cos(la) * math.sin(dl)
    return 0.5 * math.log((1 + b) / (1 - b)), math.atan2(math.tan(la), math.cos(dl))


def build_map():
    g = json.loads((REPO / "data/processed/areas.geojson").read_text())
    feats = []
    for f in g["features"]:
        polys = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]
        feats.append((f["properties"], [[[tm(*pt[:2]) for pt in ring] for ring in poly] for poly in polys]))
    xs = [p[0] for _, polys in feats for poly in polys for ring in poly for p in ring]
    ys = [p[1] for _, polys in feats for poly in polys for ring in poly for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    k = 1000 / (y1 - y0)
    out = []
    for props, polys in feats:
        d, best, cen = [], 0, None
        for poly in polys:
            for ring in poly:
                pts = [((x - x0) * k, (y1 - y) * k) for x, y in ring]
                d.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z")
            pts = [((x - x0) * k, (y1 - y) * k) for x, y in poly[0]]
            a = cx = cy = 0
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
                cr = ax * by - bx * ay
                a += cr
                cx += (ax + bx) * cr
                cy += (ay + by) * cr
            if abs(a) > best:
                best, cen = abs(a), (cx / (3 * a), cy / (3 * a))
        out.append({"id": props["id"], "name": props["short_en"], "name_fi": props["short_fi"], "d": "".join(d), "c": [round(cen[0], 1), round(cen[1], 1)]})
    return {"w": round((x1 - x0) * k, 1), "h": 1000, "areas": out}


def build_rows():
    rows = [json.loads(l) for l in open(REPO / "data/processed/gemini_extracted.jsonl")]
    keep = []
    for r in rows:
        v = r.get("value")
        if v is None:
            continue
        val = f"{v:g}" if isinstance(v, (int, float)) else str(v)
        keep.append([val, "%" if r.get("unit") == "%" else "", r.get("page"), (r.get("area_name") or "")[:28], (r.get("quote") or "").replace("\n", " ")[:64]])
    lap = next(r for r in rows if r["area_id"] == "21" and r["indicator"] == "lung_curative_intent_pct")
    return {"count": len(rows), "rows": keep, "example": {k: lap[k] for k in ("value", "unit", "period", "page", "quote", "source_url", "read_by", "area_name", "label_en")}}


API = os.environ.get("KELLO_BASE", "http://127.0.0.1:8742")


def api(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


GROUP_EN = {"county": "the county can start on Monday", "collaborative_area": "needs the collaborative area", "step_zero": "step zero"}


def main():
    m, r = build_map(), build_rows()
    # the live product, at render time: the same calls the app makes for Lapland at a 1M euro ceiling
    opt = api("/api/optimize", {"scope": "21", "budget_eur": 1000000, "objective": "curative"})
    plan = api("/api/plan/21?budget=1000000&lang=en") if True else None
    area = api("/api/areas/21")
    checks = api("/api/verify/latest?area_id=21")["checks"]
    reader = api("/api/reader")
    T, S = opt["totals"], opt["ui"]["strip"]
    st = {x["id"]: x for x in area["care_path"]["stages"]}
    cur, days = st["curative"], st["time_to_treatment"]
    best = cur["best"]
    sbrt = next(c for c in opt["chosen"] if c["intervention_id"] == "sbrt_pathway")
    chk = next(c for c in checks if c.get("intervention_id") == "sbrt_pathway")
    pil = opt["pilot"]
    six = pil["six_months"]
    docs = reader["documents"]
    facts = {
        "lapland": {"share": cur["value"], "of100": round(cur["value"]) if cur["value"] % 1 != 0.5 else int(cur["value"]), "n": cur["n"], "treated": cur["count"], "page": cur["page"],
                    "per_year": area["care_path"]["missing_patients"]["per_year"], "per_year_round": round(area["care_path"]["missing_patients"]["per_year"])},
        "vantaa": {"share": best, "of100": round(best), "area": cur["best_area_en"]},
        "national": cur["national"],
        "days": {"area": days["value"], "fi": days["national"], "page": days["page"], "level": days["level"], "area_en": days.get("collaborative_area_en")},
        "plan": {"eur": T["eur"], "eur_left": T["eur_left"], "extra": S["closes"], "extra_lo": T["extra_curative_patients_per_year"]["lo"], "extra_hi": T["extra_curative_patients_per_year"]["hi"],
                 "shortfall": S["of"], "pct": S["pct"], "short_round": round(S["of"]), "closes_round": round(S["closes"]),
                 "share_now": T["curative_share_now_pct"], "share_after": T["curative_share_after_pct"], "moved_of100": round(T["curative_share_after_pct"] - T["curative_share_now_pct"], 1),
                 "n_actions": len(opt["chosen"]), "target_year": 2028, "plan_title": plan.get("title_en") or plan.get("title"), "plan_version": plan.get("version")},
        "sbrt": {"eur": sbrt["eur"], "group_en": GROUP_EN.get(sbrt["group"], sbrt["group"]), "first_step": sbrt["first_step_en"], "owner": sbrt["owner_en"]},
        "check": {"in_use": chk["in_use_here"], "effect": chk.get("plan_effect"), "quote": chk.get("in_use_quote"), "checked_at": chk.get("checked_at"),
                  "day": time.strftime("%-d %b", time.strptime(chk["checked_at"][:10], "%Y-%m-%d")) if chk.get("checked_at") else "14 Nov"},
        "pilot": {"months": pil["months"], "actions": pil["actions"], "now": pil["effect"]["curative_share_now_pct"], "after": pil["effect"]["curative_share_after_pct"],
                  "by_year": pil["effect"]["by_year"], "patients": round(six["patients_seen"]["expected"]), "reviews": round(six["no_surgery_decisions_reviewed"]["expected"]),
                  "extra": pil["effect"]["extra_curative_patients_per_year"], "comparison": six["comparison_area_en"], "text": pil["text_en"]},
        "gap": {"overall": area["gap_checks_overall_en"], "checks": [{"id": g["id"], "q": g["question_en"], "a": g["short_answer_en"], "verdict": g["verdict"]} for g in area["gap_checks"]]},
        "read": {"count": sum(d["rows"] for d in docs), "ok": sum(d.get("verified") or 0 for d in docs), "flagged": sum(d["rows"] - (d.get("verified") or 0) for d in docs),
                 "model": sorted({(d.get("read_by") or "gemini").split(":")[-1] for d in docs})[0]},
    }
    P = facts["plan"]
    # the numbers the voice-over speaks and the card shows (film/script.json, scenes/V4.tsx); stop if the product moved
    assert facts["lapland"]["of100"] == 18 and facts["vantaa"]["of100"] == 36 and facts["vantaa"]["area"] == "Vantaa and Kerava", facts
    assert round(days["value"]) == 31 and round(days["national"]) == 37, days
    assert facts["lapland"]["per_year_round"] == 12 and P["short_round"] == 12, facts
    assert (P["closes_round"], P["pct"], P["eur"]) == (5, 43, 211500), P
    assert P["n_actions"] == 6, P
    assert (P["share_now"], P["share_after"]) == (18.5, 22.2), P
    assert "22.2%" in json.dumps(plan) and "18.5%" in json.dumps(plan), "plan target moved"
    assert sbrt["eur"] == 30400 and sbrt["first_step_en"].startswith("Write the referral rule"), sbrt
    assert chk["in_use_here"] == "partly" and chk.get("plan_effect") == "flag" and "OYS" in (chk.get("plan_effect_reason_en") or ""), chk
    G = facts["gap"]
    assert len(G["checks"]) == 5 and G["overall"].startswith("Four of five checks say the gap is real") and "8 weeks, €8,000" in G["overall"], G
    assert [g["id"] for g in G["checks"]][:4] == ["chance", "age", "stage", "records"], G
    assert next(x["eur"] for x in opt["chosen"] if x["intervention_id"] == "recording_audit") == 8000
    Pi = facts["pilot"]
    assert (Pi["months"], Pi["now"], Pi["after"], Pi["by_year"], Pi["patients"], Pi["reviews"]) == (6, 18.5, 20.5, 2028, 71, 64), Pi
    assert set(Pi["actions"]) == {"surgeon_second_opinion", "sbrt_pathway"}, Pi
    assert facts["read"]["count"] == 966 == r["count"], facts["read"]
    out = {"map": m, "read": r, "facts": facts}
    p = FILM / "src/data/film.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False))
    print(f"{p}: {p.stat().st_size // 1024} kB · live {API}: closes {P['extra']} of {P['shortfall']} ({P['pct']}%) for {P['eur']} · {P['share_now']} -> {P['share_after']} · "
          f"days {days['value']} vs {days['national']} ({days['level']}) · check {chk['in_use_here']}/{chk.get('plan_effect')} {facts['check']['day']} · {facts['read']['count']} values read")


if __name__ == "__main__":
    main()
