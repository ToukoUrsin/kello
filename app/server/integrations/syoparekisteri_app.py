"""Drive the Finnish Cancer Registry statistics app (R Shiny, no API) in a real browser and
let Gemini read the resulting table: lung cancer (C33-34) for every area at once.

    python -m integrations.syoparekisteri_app [--append]
"""

from __future__ import annotations

import json
import sys

from . import gemini_reader as g

APP_URL = "https://tilastot.syoparekisteri.fi/syovat/"
LUNG = "21L"  # Keuhkot, henkitorvi (C33-34)

# (theme, classification suffix, value-type suffix, hint)
VIEWS = [
    ("theme_inc", "_latest5", ".rate_finland_2014",
     "lung cancer incidence per 100 000, age-standardised (Finland 2014), latest 5-year period, per area: "
     "indicator lung_incidence_per_100k; say 'age-standardised (Finland 2014)' in the label"),
    ("theme_inc", "_latest5", ".obs",
     "number of new lung cancer cases in the latest 5-year period per area: indicator lung_incidence_n"),
    ("theme_mort", "_latest5", ".rate_finland_2014",
     "lung cancer mortality per 100 000, age-standardised (Finland 2014), latest 5-year period, per area: "
     "indicator lung_deaths_per_100k; say 'age-standardised (Finland 2014)' in the label"),
    ("theme_inc", "_stage", ".obs",
     "lung cancer cases by stage at diagnosis (syövän levinneisyys) per area: one item per area and stage "
     "class, indicator lung_stage_<class>_n, the stage class in the label"),
]


def make_actions(theme: str, tabu_suffix: str, value_suffix: str):
    set_js = """([id, val]) => { const sz = document.getElementById(id).selectize; sz.setValue(val); return sz.getValue(); }"""
    pick_js = """([id, suf]) => { const sz = document.getElementById(id).selectize;
        const k = Object.keys(sz.options).filter(k => k.endsWith(suf)).sort((a, b) => a.length - b.length)[0]; if (!k) return 'no option *' + suf + ' in ' + Object.keys(sz.options).join(',');
        sz.setValue(k); return k; }"""

    def act(page):
        page.wait_for_function("() => { const e = document.getElementById('value_theme'); return !!(e && e.selectize); }", timeout=120000)
        page.wait_for_timeout(2500)
        page.evaluate(set_js, ["value_theme", theme])
        page.wait_for_timeout(4000)
        chosen = [page.evaluate(pick_js, ["tabu", tabu_suffix])]
        page.wait_for_timeout(3000)
        chosen.append(page.evaluate(pick_js, ["value_type", value_suffix]))
        page.wait_for_timeout(2500)
        # the filters are re-rendered when the theme / classification changes: set them last and re-check
        filt_js = """(lung) => { const g = id => document.getElementById(id) && document.getElementById(id).selectize;
            const sx = g('in.subset.sex'), ar = g('in.subset.area'), si = g('in.subset.sites'); if (!sx || !ar || !si) return null;
            if (sx.getValue().join() !== '-1L') sx.setValue(['-1L']);
            const all = Object.keys(ar.options); if (ar.getValue().length !== all.length) ar.setValue(all);
            if (si.getValue().join() !== lung) si.setValue([lung]);
            return { sex: sx.getValue(), areas: ar.getValue().length, sites: si.getValue() }; }"""
        state = None
        for _ in range(3):
            state = page.evaluate(filt_js, LUNG)
            page.wait_for_timeout(2500)
        chosen.append(state)
        page.get_by_role("button", name="Näytä").first.click()
        page.wait_for_timeout(8000)
        page.locator("a[data-value='2']").first.click()  # "Taulukko" tab
        page.wait_for_timeout(4000)
        page.evaluate("""() => { try { $('table.dataTable').each(function () { $(this).DataTable().page.len(-1).draw(); }); } catch (e) {}
                               try { const s = document.querySelector('.dataTables_length select'); if (s) { s.value = s.options[s.options.length-1].value; s.dispatchEvent(new Event('change', {bubbles:true})); } } catch (e) {} }""")
        page.wait_for_timeout(3000)
        act.chosen = chosen

    return act


def read_view(theme: str, tabu_suffix: str, value_suffix: str, hint: str) -> dict:
    act = make_actions(theme, tabu_suffix, value_suffix)
    res = g.read_report(
        APP_URL, actions=act, source_url=APP_URL,
        hint=("This is the Finnish Cancer Registry statistics app showing a table for lung cancer "
              "(Keuhkot, henkitorvi C33-34), both sexes together, one row per area. " + hint +
              ". Extract the value for EVERY area row. Use the period shown in the table."),
    )
    res["view"] = {"theme": theme, "selected": getattr(act, "chosen", None)}
    return res


def main(argv: list[str]) -> int:
    append = "--append" in argv
    views = VIEWS
    if "--view" in argv:  # run one view (0-based), so several can run side by side
        views = [VIEWS[int(argv[argv.index("--view") + 1])]]
    out = []
    for theme, tabu, vt, hint in views:
        try:
            res = read_view(theme, tabu, vt, hint)
        except Exception as exc:
            print(f"view {theme}{tabu}{vt}: FAILED {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
            continue
        rows = g.to_rows(res)
        print(f"view {res['view']}: {len(res['extracted'])} values, {len(rows)} mapped rows, {res['seconds']} s",
              file=sys.stderr)
        if append:
            g.append_rows(rows)
        out.append(res)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
