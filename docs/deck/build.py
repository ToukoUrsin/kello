"""Build the pitch deck PDF.

  .venv/bin/python docs/deck/build.py [--api http://127.0.0.1:8742] [--repo github.com/owner/kello]

Slide 3 ("Is the gap real?") is filled from the running app (/api/areas/21), so the deck
cannot drift from the product. Output: docs/deck/kello-deck.pdf (6 slides, 1920x1080).
"""
import argparse, json, os, pathlib, urllib.request
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
DECK_OUT = pathlib.Path(os.environ.get("KELLO_DECK_OUT", str(HERE / "out")))
DECK_OUT.mkdir(parents=True, exist_ok=True)
ap = argparse.ArgumentParser()
ap.add_argument("--api", default="http://127.0.0.1:8742")
ap.add_argument("--repo", default="")
a = ap.parse_args()

area = json.load(urllib.request.urlopen(f"{a.api}/api/areas/21", timeout=30))
gc = area.get("gap_checks") or {}
checks = gc.get("checks") if isinstance(gc, dict) else gc
overall = (gc.get("overall_en") if isinstance(gc, dict) else None) or area.get("gap_checks_overall_en") or ""
short = lambda t: t if len(t) <= 150 else t[:147].rsplit(" ", 1)[0] + "…"
data = {"overall": overall, "checks": [{"q": c.get("short_question_en") or c["question_en"], "a": short(c.get("short_answer_en") or c["answer_en"]), "verdict": c["verdict"]} for c in (checks or [])]}
(HERE / "checks.js").write_text("window.KELLO_CHECKS = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n")

html = (HERE / "deck.html").read_text()
tmp = HERE / "_deck_build.html"
tmp.write_text(html.replace("REPO_URL", a.repo or "link in the submission"))
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(tmp.as_uri()); pg.wait_for_timeout(600)
    pg.pdf(path=str(HERE / "kello-deck.pdf"), width="1920px", height="1080px", print_background=True)
    for i in range(6):
        pg.evaluate(f"document.querySelectorAll('.slide')[{i}].scrollIntoView()")
        pg.screenshot(path=str(DECK_OUT / f"deck-{i+1}.png"))
    b.close()
tmp.unlink()
print("wrote", HERE / "kello-deck.pdf")
