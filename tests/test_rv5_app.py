"""Review v5 app fixes (B6, B7, B8, B14, B20, B23-B27, B35): the app shows closed-out placeholders, corrected wording,
per-carrier fuel weeks, and the new layout pieces without page errors or sideways scrolling."""
import json, re
import pytest
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local web server fixture)
from test_polish import app
import contextlib, os


@contextlib.contextmanager
def app_with(site, width=390, files=None, news_extra=None):
    """The app with some data files replaced (files: {"data/x.json": obj, or None for a 404}) and extra live stories."""
    pw = pytest.importorskip("playwright.sync_api")
    files = dict(files or {})
    if news_extra:
        files["data/news.json"] = json.loads((ROOT / "data/news.json").read_text()) + news_extra
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        # no service worker: it would fetch data files itself, past the routes below
        pg = b.new_context(viewport={"width": width, "height": 900}, service_workers="block").new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        def handler(obj):
            body = None if obj is None else json.dumps(obj)
            return lambda route: route.fulfill(status=404, body="") if body is None else route.fulfill(status=200, content_type="application/json", body=body)
        for path, obj in files.items():
            pg.route(re.compile(r"/" + re.escape(path) + r"(\?.*)?$"), handler(obj))
        pg.goto(site, wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && NEWS.length > 150", timeout=60000)
        pg.wait_for_timeout(500)
        pg.errors = errors
        yield pg
        b.close()
    assert not errors, errors[:3]


@pytest.mark.parametrize("width", [390, 1280])
def test_clock_line_keeps_its_sub_items(site, width):
    """B5/B10: a story date's sub-items (fees) reach the rate clock line and are shown whole, escaped."""
    st = {"id": "zzsubapp", "date": "2026-10-23", "c": ["UPS"], "cat": "Pricing & GRI", "kind": "News", "lvl": 3, "imp": "up",
          "title": "UPS sets a test increase", "sum": "x", "plain": "x", "url": "https://x.example/subapp",
          "srcs": [{"src": "UPS", "url": "https://x.example/subapp"}],
          "dates": [{"d": "2030-12-21", "w": "UPS test rate increase: 5.9% average (Ground, Air, International)", "imp": "up",
                     "fees": ["Additional Handling minimum billable weight goes from 40 lb to 50 lb <b>x</b>", {"w": "Area Surcharge ZIP list", "v": "changes"}]}]}
    with app_with(site, width, news_extra=[st]) as pg:
        pg.click('nav.tabs [data-tab="clock"]')
        pg.wait_for_timeout(300)
        x = pg.evaluate("() => DATES.find(x => x.id === 'xzzsubapp0')")
        assert x and len(x["fees"]) == 2
        html = pg.evaluate("() => DATES.find(x => x.id === 'xzzsubapp0').fees.map(feeDiv).join('')")
        assert "Additional Handling minimum billable weight goes from 40 lb to 50 lb &lt;b&gt;x&lt;/b&gt;" in html
        assert "Area Surcharge ZIP list<b>changes</b>" in html
        assert pg.evaluate(OVERFLOW) is None


@pytest.mark.parametrize("width", [390, 1280])
def test_ups_2027_placeholders_closed_out(site, width):
    """B6: the Docs placeholder points to UPS's Oct 23, 2026 announcement; the 'Still waiting' story is gone."""
    with app(site, width) as pg:
        assert pg.evaluate("() => NEWS.some(n => n.id === 'w84705482dd2f')")
        assert not pg.evaluate("() => NEWS.some(n => n.id === '07' || /still waiting on ups/i.test(n.title))")
        pg.click('nav.tabs [data-tab="docs"]')
        pg.wait_for_timeout(400)
        pg.evaluate("() => { docCar = 'UPS'; renderDocs() }")
        d = pg.evaluate("() => DOCS.find(d => d.c === 'UPS' && d.n === 'UPS 2027 general rate increase')")
        assert d["eff"] == "2026-12-21" and d["story"] == "w84705482dd2f"
        assert "Not yet published" not in d["d"] and "Rate previews not yet published by UPS" in d["d"]
        row = pg.evaluate("""() => { const d = DOCS.find(d => d.c === 'UPS' && d.n === 'UPS 2027 general rate increase');
            const el = document.getElementById(docDomId(d)); return el && el.textContent }""")
        assert row and "Announced Oct 23, 2026" in row and "Not public" not in row and "UPS announcement" in row
        assert pg.evaluate("""() => { const d = DOCS.find(d => d.c === 'UPS' && d.n === 'UPS 2027 general rate increase');
            const el = document.getElementById(docDomId(d)); return !!el.querySelector('button[data-open="w84705482dd2f"]') }""")
        assert pg.evaluate(OVERFLOW) is None


@pytest.mark.parametrize("width", [390, 1280])
def test_built_in_rate_clock_wording(site, width):
    """B7: shoulder-rate fees by service, FedEx zone change wording, DHL surcharge note."""
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="clock"]')
        pg.wait_for_timeout(300)
        D = pg.evaluate("() => Object.fromEntries(DATES.filter(x => ['e09','e11','e13','e15'].includes(x.id)).map(x => [x.id, x]))")
        assert "Ground residential fees return to $0.50" in D["e09"]["note"] and "UPS Air $1.35" in D["e09"]["note"]
        assert "Per-package fees return to $0.50" not in D["e09"]["note"]
        assert D["e13"]["w"] == "FedEx zones change for select U.S. domestic ZIP pairs"
        assert "has not listed" not in D["e15"]["note"] and "Elevated Risk" in D["e15"]["note"]
        assert "USPS holiday prices Jan 16" in D["e11"]["note"]   # PRC Order 9703: prices roll back on Jan 17, 2027
        assert pg.evaluate(OVERFLOW) is None


@pytest.mark.parametrize("width", [390, 1280])
def test_fuel_weeks_per_carrier_and_one_current_value(site, width):
    """B8: each carrier shows its own effective week ("last confirmed week of ..." in amber when over 8 days old); the
    ticker and the Fuel tab read the same current value; the next posted week is shown apart; the UPS Nov 2 table change
    is a dated notice, not an increase."""
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="fuel"]')
        pg.wait_for_timeout(400)
        r = pg.evaluate("""() => {
          const cards = {UPS: document.querySelector('#fuelNow .fcard.c-ups'), FedEx: document.querySelector('#fuelNow .fcard.c-fdx'), OnTrac: document.querySelector('#fuelNow .fcard.c-ontrac')};
          const out = {};
          [['UPS', 1], ['FedEx', 2], ['OnTrac', 3]].forEach(([c, i]) => {
            const cur = FUELDB.filter(r => r[0] <= TODAY && r[i] != null).at(-1), nx = FUELDB.find(r => r[0] > TODAY && r[i] != null);
            const card = cards[c], wk = card.querySelector('.fwk');
            out[c] = {d: cur[0], v: cur[i], old: (Date.parse(TODAY) - Date.parse(cur[0])) / 864e5 > 8, wk: wk.textContent,
                      amber: wk.classList.contains('fstale'), shown: card.querySelector('.frow:not(.fhd) .fval').textContent,
                      cur: FUEL.current[c].ground, exp: card.querySelector('.fexp').textContent, next: nx ? [nx[0], nx[i]] : null};
          });
          out.ticker = document.getElementById('ticker').textContent;
          out.sum = document.getElementById('fuelSum').textContent;
          out.head = document.getElementById('fuelNowH').textContent;
          out.notice = document.getElementById('fuelNotice').textContent;
          return out }""")
        for c in ("UPS", "FedEx", "OnTrac"):
            x = r[c]
            assert x["cur"] == x["v"] and x["shown"] == f"{x['v']:g}%", (c, x)
            assert x["wk"].startswith("Last confirmed week of" if x["old"] else "Week of") and x["amber"] == x["old"], (c, x)
            if x["next"]:
                assert f"{x['next'][1]:g}% posted" in x["exp"], (c, x)
        assert f"{r['OnTrac']['v']:g}%" in r["ticker"]
        if r["UPS"]["old"]:
            assert "this week" not in r["sum"] and r["head"] == "Latest posted rates"
        assert "Nov 2, 2026" in r["notice"] and "not labeled an increase" in r["notice"]
        assert pg.evaluate(OVERFLOW) is None


ASK = "async q => { const a = await askCoopAnswer(q); const d = document.createElement('div'); d.innerHTML = a.h; return d.textContent }"


def test_ask_coop_closes_not_yet_announced_placeholders(site):
    """B14: once a Pricing & GRI story for the carrier and year exists, Coop never answers "not yet announced"."""
    alm = json.loads((ROOT / "data/almanac.json").read_text())
    ph = lambda y: {"carrier": "UPS", "year": y, "kind": "gri", "announced": None, "effective": None, "pct": None, "id": f"ups-{y}-gri",
                    "headline": f"UPS {y} general rate increase not yet announced", "details": [], "sources": [], "conf": "partial",
                    "note": "Forecasts are not announcements."}
    story = {"id": "zzgri2028", "date": "2027-10-22", "c": ["UPS"], "cat": "Pricing & GRI", "kind": "News", "lvl": 3, "imp": "up",
             "title": "UPS sets its 2028 rate increase, effective Dec 20, 2027", "sum": "x", "plain": "x", "act": "2027-12-20",
             "url": "https://x.example/gri2028", "srcs": [{"src": "UPS", "url": "https://x.example/gri2028"}]}
    with app_with(site, 1280, files={"data/almanac.json": alm + [ph(2028), ph(2029)]}, news_extra=[story]) as pg:
        a = pg.evaluate(ASK, "UPS 2028 rate increase")
        assert "not yet announced" not in a.lower() and "UPS sets its 2028 rate increase" in a
        # no story for 2029: the placeholder still answers, so the rule only closes what a story has replaced
        assert "not yet announced" in pg.evaluate(ASK, "UPS 2029 rate increase").lower()
        # the live UPS Dec 21, 2026 story closes the real 2027 placeholder the same way
        assert "not yet announced" not in pg.evaluate(ASK, "UPS 2027 rate increase").lower()


def test_ask_coop_programs_fuel_weeks_and_excerpts(site):
    """B14: program questions answer from data/programs.json first and only for that carrier; fuel names each carrier's own
    week; guide excerpts show document, year and effective date, and other carriers' notes stay out."""
    progs = {"programs": [{"id": "ups-sbr", "carrier": "UPS", "program": "UPS Small Business Rates",
                           "inclusions": [{"text": "Delivery Area Surcharge", "src": "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates", "checked": "2026-10-24"},
                                          {"text": "Fuel Surcharge <b>", "checked": "2026-10-24"}],
                           "no_fees": ["Address Correction"], "src": "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates", "checked": "2026-10-24"}]}
    with app_with(site, 1280, files={"data/programs.json": progs}) as pg:
        a = pg.evaluate(ASK, "Small Business Rates fuel")
        assert a.startswith("UPS Small Business Rates: advertised as including Delivery Area Surcharge; Fuel Surcharge <b>")
        assert "Spee-Dee" not in a and "FedEx Ground" not in a and "UPS Ground" in a
        assert "<b>" not in pg.evaluate("async q => (await askCoopAnswer(q)).h.replace(/<\\/?b>/g, '').replace(/<b class[^>]*>/g, '')", "SBR fuel").replace("&lt;b&gt;", "")
        f = pg.evaluate(ASK, "UPS fuel surcharge")
        wk = pg.evaluate("() => FUEL_API.wk(FUEL.wk.UPS.ground)")
        assert f"({wk})" in f and "in effect from" not in f and "OnTrac" not in f
        d = pg.evaluate(ASK, "FedEx dim divisor")
        assert "USPS applies dimensional weight" not in d
        g = pg.evaluate("""async q => { const a = await askCoopAnswer(q); const box = document.createElement('div'); box.innerHTML = a.h;
            return [...box.querySelectorAll('.ak-guide')].map(b => b.textContent) }""", "delivery area surcharge")
        assert g and all(re.search(r"(20\d\d|Year not stated) · (effective|effective date not on file)", x) for x in g), g
        cy = int(pg.evaluate("() => TODAY.slice(0, 4)"))
        for x in g:
            m = re.search(r"(20\d\d) · ", x)
            if not m or int(m.group(1)) < cy:
                assert "check the carrier's current version" in x, x
    # data/programs.json missing: no error, generic answer
    with app_with(site, 390, files={"data/programs.json": None}) as pg:
        assert "Fuel" in pg.evaluate(ASK, "Small Business Rates fuel")
