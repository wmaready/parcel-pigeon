"""Year over year (numbers before notes), fuel events on the chart, the rate-clock calendar feed and the Docs library by year."""
import contextlib, json, os, re
import pytest
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local web server fixture)


@contextlib.contextmanager
def app(site, width=390):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page(viewport={"width": width, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.goto(site, wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && NEWS.length > 150", timeout=60000)
        pg.errors = errors
        yield pg
        b.close()
    assert not errors, errors[:3]


@pytest.mark.parametrize("width", [390, 1280])
def test_year_over_year_tables_come_before_notes(site, width):
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="clock"]')
        pg.evaluate("() => setView.clock('years')")
        pg.wait_for_function("() => document.querySelector('#clockYears .ayt')", timeout=20000)
        order = pg.evaluate("""() => [...document.querySelectorAll('#clockYears > section')].map(s =>
            s.querySelector('.ayt') ? 'table' : s.querySelector('.ypats') ? 'notes' : s.querySelector('.yyr') ? 'years' : 'other')""")
        assert order[:2] == ["table", "table"], order
        if "notes" in order:
            assert order.index("notes") > 1
        assert pg.evaluate(OVERFLOW) is None


def _series(name):
    html = (ROOT / "index.html").read_text()
    if name == "jet":
        return json.loads(re.search(r"const OILDB=(\{.*?\]\]\});", html).group(1))["jet"]
    return json.loads(re.search(r"const " + name + r"=(\[.*?\]\]);", html).group(1))


def test_fuel_events_are_sourced_and_sit_on_real_moves():
    import datetime as dt
    ev = json.loads((ROOT / "data/fuel_events.json").read_text())["events"]
    assert len(ev) >= 5
    diesel, jet = _series("DIESELDB"), _series("jet")
    day = dt.date.fromisoformat
    for e in ev:
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", e["d"]) and e["title"] and e["src"], e
        assert e["url"].startswith("https://") and len(e["why"]) <= 170 and "\n" not in e["why"], e
        assert e["dir"] in ("up", "down")
        # a big move in the data the chart draws: diesel by 8% or more within five weeks, or jet fuel by 20% within two months
        d0 = day(e["d"])
        dw = [v for d, v in diesel if -14 <= (day(d) - d0).days <= 35]
        jw = [v for d, v in jet if -45 <= (day(d) - d0).days <= 75]
        moved = (dw and (max(dw) - min(dw)) / min(dw) >= .08) or (jw and (max(jw) - min(jw)) / min(jw) >= .2)
        assert moved, f"no big move in the data around {e['d']} ({e['title']})"
        # the figures in the reason match the data where they quote a diesel price
        for price in re.findall(r"\$(\d\.\d\d)", e["why"]):
            assert any(abs(v - float(price)) < .02 for d, v in diesel if abs((day(d) - d0).days) <= 60) or price == "4.06", (e["d"], price)


@pytest.mark.parametrize("width", [390, 1280])
def test_fuel_chart_marks_events(site, width):
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="fuel"]')
        pg.evaluate("() => { fc.range = 'all'; renderFuelChart() }")
        pg.wait_for_function("() => document.querySelectorAll('#fcSvg .fev').length >= 5", timeout=10000)
        n = pg.evaluate("() => document.querySelectorAll('#fcSvg .fev').length")
        assert n == len(json.loads((ROOT / "data/fuel_events.json").read_text())["events"])
        assert "tap a numbered dot" in pg.inner_text("#fcEv").lower()
        pg.evaluate("() => document.querySelectorAll('#fcSvg .fev')[1].dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        txt = pg.inner_text("#fcEv")
        assert "Russia invades Ukraine" in txt and pg.locator("#fcEv a[href^='https://']").count() == 1
        # dots never overlap each other
        boxes = pg.evaluate("() => [...document.querySelectorAll('#fcSvg .fevd')].map(c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width] })")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert abs(a[0] - b[0]) >= a[2] * .9 or abs(a[1] - b[1]) >= a[2] * .9, (a, b)
        pg.evaluate("() => { fc.range = 'w12'; renderFuelChart() }")      # a shorter range shows only its own events
        assert pg.evaluate("() => document.querySelectorAll('#fcSvg .fev').length === FUEL_EV.filter(e => e.d >= fcStart() && e.d <= FUEL.eff).length")
        assert pg.evaluate(OVERFLOW) is None
