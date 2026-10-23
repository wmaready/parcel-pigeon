"""Year over year (numbers before notes), fuel events on the chart, the rate-clock calendar feed and the Docs library by year."""
import contextlib, os, re
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
