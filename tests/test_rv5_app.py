"""Review v5 app fixes (B6, B7, B8, B14, B20, B23-B27, B35): the app shows closed-out placeholders, corrected wording,
per-carrier fuel weeks, and the new layout pieces without page errors or sideways scrolling."""
import json, re
import pytest
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local web server fixture)
from test_polish import app
import contextlib, os


@contextlib.contextmanager
def app_with(site, width=390, files=None, news_extra=None, tz=None):
    """The app with some data files replaced (files: {"data/x.json": obj, or None for a 404}) and extra live stories."""
    pw = pytest.importorskip("playwright.sync_api")
    files = dict(files or {})
    if news_extra:
        files["data/news.json"] = json.loads((ROOT / "data/news.json").read_text()) + news_extra
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        # no service worker: it would fetch data files itself, past the routes below
        pg = b.new_context(viewport={"width": width, "height": 900}, service_workers="block", **({"timezone_id": tz} if tz else {})).new_page()
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


MAP_ASSETS = ("leaflet.js", "leaflet.css", "MarkerCluster.css", "leaflet.markercluster.js")


def test_map_assets_live_in_their_folder(site):
    """B20: the four map files are in map-assets/ and served from there (the address mx.js asks for first), so the map
    makes no failed requests on a first visit."""
    import urllib.request
    base = site.rsplit("/", 1)[0]
    for f in MAP_ASSETS:
        assert (ROOT / "map-assets" / f).is_file(), f
        assert not (ROOT / f).exists(), f"{f} is still at the top level"
        with urllib.request.urlopen(f"{base}/map-assets/{f}") as r:
            assert r.status == 200 and len(r.read()) > 500, f
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_context(viewport={"width": 390, "height": 900}, service_workers="block").new_page()
        seen = []
        pg.on("response", lambda r: seen.append((r.url, r.status)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.goto(site, wait_until="load")
        pg.wait_for_function("() => typeof PL !== 'undefined' && NEWS.length > 150", timeout=60000)
        pg.click('nav.tabs [data-tab="mna"]')
        pg.wait_for_timeout(300)
        pg.evaluate("() => { const b = document.querySelector('[data-m=\"geo\"]'); b && b.click() }")
        pg.wait_for_function("() => window.L && L.markerClusterGroup", timeout=20000)
        b.close()
    got = {u.rsplit("/", 2)[-2] + "/" + u.rsplit("/", 1)[-1]: s for u, s in seen if any(u.endswith("/" + f) for f in MAP_ASSETS)}
    assert all(got.get(f"map-assets/{f}") == 200 for f in MAP_ASSETS), got
    assert all(s == 200 for s in got.values()), got


@pytest.mark.parametrize("width", [390, 1280])
def test_seed_ownership_and_history_corrections(site, width):
    """B23: InPost-Yodel dated Apr 17, 2025 (95.5% of Judge Logistics, PayPoint 4.5%, InPost's release); Canada Post's
    history line; FedEx's 19.9% of FedEx Freight as a dated connection at separation, June 1, 2026."""
    with app(site, width) as pg:
        E = pg.evaluate("() => PEDGES.filter(e => e.a === 'fedex' && e.b === 'fdxfreight')")
        # the built-in InPost-Yodel lines (live data later folds Yodel into InPost, which retires them at run time)
        src = (ROOT / "index.html").read_text(encoding="utf-8")
        y = json.loads(re.search(r"^const PEDGES=(\[.*\]);$", src, re.M).group(1))
        y = [e for e in y if e["a"] == "inpost" and e["b"] == "yodel"]
        assert len(y) == 2 and all(e["d"] == "2025-04-17" and "95.5% of Judge Logistics" in e["t"] and "PayPoint" in e["t"]
                         and "Strategic%20Takeover%20of%20Yodel.pdf" in e["url"] for e in y), y
        f = [e for e in E if e["b"] == "fdxfreight" and e["k"] == "invested"]
        assert len(f) == 1 and f[0]["d"] == "2026-06-01" and "19.9%" in f[0]["t"] and "at separation, June 1, 2026" in f[0]["t"]
        assert pg.evaluate("() => PL.canadapost.yr") == "1851 (postal service); federal department 1867; Crown corporation 1981"
        ev = pg.evaluate("() => coEvents(PL.fdxfreight, []).filter(x => /19.9%/.test(x.t)).map(x => x.d)")
        assert ev == ["2026-06-01"]
        pg.evaluate("() => openCompany('canadapost')")
        pg.wait_for_timeout(400)
        assert "Crown corporation 1981" in pg.inner_text("body")
        assert pg.evaluate(OVERFLOW) is None


@pytest.mark.parametrize("width", [390, 1280])
def test_map_coverage_line_follows_the_filter(site, width):
    """B24: above the map, 'Headquarters only, not service coverage. X of Y companies have a mapped location.', both
    numbers from the current sector filter."""
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="mna"]')
        pg.wait_for_timeout(300)
        pg.evaluate("() => { const b = document.querySelector('[data-m=\"geo\"]'); b && b.click() }")
        pg.wait_for_function("() => /companies have a mapped location/.test(document.getElementById('mxGcov').textContent)", timeout=20000)
        rx = r"^Headquarters only, not service coverage\. (\d+) of (\d+) companies have a mapped location\.$"
        m = re.match(rx, pg.inner_text("#mxGcov"))
        total = int(re.search(r"(\d+) companies", pg.inner_text("#mxStats")).group(1))
        assert m and int(m.group(2)) == total and 0 < int(m.group(1)) <= total
        assert pg.evaluate("() => { const g = document.getElementById('mxGcov'), m = document.getElementById('mxGeo'); return g.compareDocumentPosition(m) & Node.DOCUMENT_POSITION_FOLLOWING }")
        chip = pg.evaluate("() => { const b = [...document.querySelectorAll('#mxChips [data-r]')].find(b => b.dataset.r !== '*' && +b.querySelector('em').textContent > 0); b.click(); return +b.querySelector('em').textContent }")
        pg.wait_for_timeout(300)
        m2 = re.match(rx, pg.inner_text("#mxGcov"))
        assert m2 and int(m2.group(2)) == chip and int(m2.group(1)) <= chip
        assert pg.evaluate(OVERFLOW) is None


@pytest.mark.parametrize("width", [390, 1280])
def test_phone_first_screen(site, width):
    """B25: the tour offer sits in the page under Today's heading and closes on the first section change; Help has "Take
    the tour"; the brief's controls are 44x44 named buttons with a visible keyboard focus; the header tagline folds after
    the first scroll on a phone; times show in the reader's zone with UTC on tap; Presentation mode quiets the page."""
    with app_with(site, width, tz="America/Chicago") as pg:
        pg.wait_for_selector(".ptoffer", timeout=8000)
        o = pg.evaluate("""() => { const o = document.querySelector('.ptoffer'); return [getComputedStyle(o).position,
            !!(o.previousElementSibling && o.previousElementSibling.classList.contains('shead')), o.closest('#s-today') != null] }""")
        assert o == ["static", True, True]
        pg.click('nav.tabs [data-tab="news"]')
        pg.wait_for_timeout(500)
        assert pg.evaluate("() => !document.querySelector('.ptoffer')")
        pg.click('nav.tabs [data-tab="today"]')
        pg.wait_for_timeout(300)
        B = pg.evaluate("() => [...document.querySelectorAll('#cfly .cbbtn, #cfly .cbdot')].map(b => { const r = b.getBoundingClientRect(); return [r.width, r.height, b.tagName, b.getAttribute('aria-label') || ''] })")
        assert len(B) >= 4 and all(w >= 44 and h >= 44 and t == "BUTTON" and l for w, h, t, l in B), B
        pg.focus('#cfly .cbbtn[data-cb="prev"]')
        pg.keyboard.press("Tab")
        f = pg.evaluate("() => { const a = document.activeElement; return [a.className, getComputedStyle(a).outlineStyle, getComputedStyle(a).outlineWidth] }")
        assert "cbdot" in f[0] and f[1] == "solid" and f[2] != "0px", f
        t = pg.inner_text("#tdayTime")
        assert "CDT" in t or "CST" in t, t
        pg.click("#tdayTime")
        assert "UTC" in pg.inner_text("#tdayTime")
        pg.evaluate("() => window.scrollTo(0, 400)")
        pg.wait_for_timeout(200)
        hidden = pg.evaluate("() => getComputedStyle(document.querySelector('.logo .ltag')).display === 'none'")
        assert hidden == (width <= 700)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.click("#presentBtn")
        st = pg.evaluate("() => [document.body.classList.contains('present'), reduceMotion(), getComputedStyle(document.querySelector('.ticker .track')).animationName, document.getElementById('presentBtn').getAttribute('aria-pressed')]")
        assert st == [True, True, "none", "true"], st
        assert pg.evaluate(OVERFLOW) is None
        pg.click("#presentBtn")
        assert not pg.evaluate("() => document.body.classList.contains('present')")
        pg.click(".tdhelp [data-tour]")
        pg.wait_for_selector(".ptour", timeout=5000)
        pg.keyboard.press("Escape")


def test_docs_snapshot_links_and_announcement_link(site):
    """B35: a watched page's dated pictures (data/docwatch.json docs[url].snap) show under its Docs entry, after any change
    text, opening in a new tab, escaped; nothing when absent. B6: a closed placeholder's 'see' link is its link."""
    hub = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates"
    dw = json.loads((ROOT / "data/docwatch.json").read_text())
    dw["docs"][hub] = {**dw["docs"].get(hub, {}), "snap": {"d": "2026-10-24", "img": "data/snapshots/ups-hub/2026-10-24.jpg",
                                                           "prev": "data/snapshots/ups-hub/2026-09-30.jpg"}}
    docs = json.loads((ROOT / "data/docs.json").read_text())
    for d in docs:
        if d.get("c") == "UPS" and d.get("n") == "UPS 2027 general rate increase":
            d.update({"u": None, "see": "https://about.ups.example/2027-rates?a=1&b=2", "d": "Announced Oct 23, 2026; rate previews not yet published by UPS"})
    with app_with(site, 390, files={"data/docwatch.json": dw, "data/docs.json": docs}) as pg:
        pg.click('nav.tabs [data-tab="docs"]')
        pg.wait_for_timeout(500)
        pg.evaluate("() => { docCar = 'UPS'; renderDocs() }")
        r = pg.evaluate("""hub => { const row = d => document.getElementById(docDomId(d));
            const h = row(DOCS.find(d => d.u === hub)), g = row(DOCS.find(d => d.c === 'UPS' && d.n === 'UPS 2027 general rate increase'));
            const other = row(DOCS.find(d => d.c === 'UPS' && d.u && d.u !== hub));
            const L = [...h.querySelectorAll('.dsnap a')];
            return {links: L.map(a => [a.textContent, a.getAttribute('href'), a.target, a.getAttribute('aria-label')]),
                    after: h.innerHTML.indexOf('dsnap') > Math.max(h.innerHTML.indexOf('class="dd"'), h.innerHTML.indexOf('class="dm"')),
                    other: other.querySelectorAll('.dsnap').length, see: g.querySelector('a.dn').getAttribute('href'), gtxt: g.textContent} }""", hub)
        assert r["links"][0][:3] == ["Page as it read on Oct 24, 2026 ↗", "data/snapshots/ups-hub/2026-10-24.jpg", "_blank"]
        assert r["links"][1][:3] == ["Before: Sep 30, 2026 ↗", "data/snapshots/ups-hub/2026-09-30.jpg", "_blank"]
        assert "UPS" in r["links"][0][3] and "Oct 24, 2026" in r["links"][0][3]
        assert r["after"] and r["other"] == 0
        assert r["see"] == "https://about.ups.example/2027-rates?a=1&b=2" and "Announced" in r["gtxt"] and "Not yet published" not in r["gtxt"]
        assert pg.evaluate(OVERFLOW) is None


FOUND = ["transimpact", "shipware", "reveel", "sifted", "ljmgroup", "shipmatrix", "lojistic", "intelligentaudit"]


def test_company_foundation_is_the_supplied_file():
    """B27: company-foundation.js is added exactly as supplied (not regenerated), loaded before company-search.js and before
    the page builds its company indexes, and the nightly research now takes parcel consultancies."""
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    assert src.index('<script src="company-foundation.js"></script>') < src.index("const PLAYERS=") < src.index("const PL=Object.fromEntries(PLAYERS")
    assert src.index('<script src="company-foundation.js"></script>') < src.index('<script src="company-search.js"></script>')
    hook = src.index("window.ppCompanyFoundation.merge(PLAYERS)")
    assert src.index("const PLAYERS=") < hook < src.index("function indexPlayers(){")
    import hashlib
    assert hashlib.sha256((ROOT / "company-foundation.js").read_bytes()).hexdigest() == "e2d7c50a89479d479c37ce34a74062d75752d16003ef597743d50003922494c9"
    import players
    assert "consultancy" in players.REALMS
    assert "Parcel consultancies, parcel-spend and invoice-audit firms ARE players" in players.RESEARCH
    assert "parcel-spend consultancies\nand invoice-audit firms;" not in players.RESEARCH


@pytest.mark.parametrize("width", [390, 1280])
def test_consultancies_on_the_map_and_in_search(site, width):
    """B27: "Shipware" finds Shipware, never Costco; merging twice adds nothing; existing ids and ownership are kept; no
    coordinates or ownership are invented; the profile lists its sources and the date the record was checked."""
    with app(site, width) as pg:
        ids = pg.evaluate("() => PLAYERS.filter(p => p.foundation).map(p => p.id)")
        assert sorted(ids) == sorted(FOUND)
        hits = pg.evaluate("() => ppCompanySearch('Shipware', PLAYERS, PEDGES, RL).map(x => x.p.id)")
        assert hits and hits[0] == "shipware" and "costco" not in hits
        assert pg.evaluate("() => { const n = PLAYERS.length; ppCompanyFoundation.merge(PLAYERS); return PLAYERS.length === n }")
        kept = pg.evaluate("""() => { const L = [{id: 'tix', n: 'TransImpact', al: ['TI'], own: 'pe', parent: 'acme', tk: null, hq: 'Somewhere, NC', yr: '1990'}];
            ppCompanyFoundation.merge(L); ppCompanyFoundation.merge(L); return L }""")
        t = [p for p in kept if p["id"] == "tix"]
        assert len(t) == 1 and t[0]["own"] == "pe" and t[0]["parent"] == "acme" and t[0]["hq"] == "Somewhere, NC" and t[0]["yr"] == "1990"
        assert len([p for p in kept if p["n"] == "TransImpact"]) == 1
        fresh = pg.evaluate("() => PLAYERS.filter(p => p.foundation).map(p => ({id: p.id, own: p.own, parent: p.parent, tk: p.tk, geo: p.geo || null, realm: p.realm}))")
        assert all(f["own"] is None and f["parent"] is None and f["tk"] is None and f["geo"] is None and f["realm"] == "consultancy" for f in fresh), fresh
        assert not pg.evaluate("() => PEDGES.some(e => ['transimpact','shipware','reveel','sifted','ljmgroup','shipmatrix','lojistic','intelligentaudit'].includes(e.a) || ['transimpact','shipware','reveel','sifted','ljmgroup','shipmatrix','lojistic','intelligentaudit'].includes(e.b))")
        assert pg.evaluate("() => RL.consultancy") == "Consultancies & shipping intelligence"
        assert pg.evaluate("() => PLAYERS.filter(p => p.foundation).every(p => !(wmLoc(p) || {}).g)")
        assert pg.evaluate("() => PSITE.shipware") == "shipware.com"
        # the market-map profile: every source and "Record checked Oct 18, 2026"
        pg.click('nav.tabs [data-tab="mna"]')
        pg.wait_for_timeout(300)
        pg.fill("#mxQ", "Shipware")
        pg.wait_for_selector('#mxSugg [data-go="shipware"]', timeout=5000)
        pg.click('#mxSugg [data-go="shipware"]')
        pg.wait_for_timeout(400)
        co = pg.inner_text("#mxCo")
        assert "Record checked Oct 18, 2026" in co and "Source: shipware.com" in co and "Consultancies & shipping intelligence" in co
        assert pg.evaluate(OVERFLOW) is None


def test_service_worker_saved_copies(site):
    """B26: an error answer is a failure (the saved copy is used); when saved copies are used the page says "Offline -
    saved <time>"; data/snapshots/ is never cached; the cache version is bumped."""
    sw = (ROOT / "sw.js").read_text()
    assert "const C='pp-v36'" in sw and "data\\/snapshots" in sw
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        ctx = b.new_context(viewport={"width": 390, "height": 900})
        ctx.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(site, wait_until="load")
        pg.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
        pg.reload(wait_until="load")          # now controlled: the page and its data are saved as they load
        pg.wait_for_function("() => typeof PL !== 'undefined' && NEWS.length > 150", timeout=60000)
        pg.wait_for_timeout(1500)
        assert pg.evaluate("() => !!navigator.serviceWorker.controller")
        assert pg.is_hidden("#offlineNote")
        # a picture under data/snapshots/ is fetched from the network only, never saved
        pg.evaluate("() => fetch('data/snapshots/none/2026-10-24.jpg').catch(() => null)")
        pg.wait_for_timeout(300)
        keys = pg.evaluate("() => caches.open('pp-v36').then(c => c.keys()).then(K => K.map(r => r.url))")
        assert any(k.endswith("/data/news.json") for k in keys) and not any("/data/snapshots/" in k for k in keys)
        # a 500 for data the page already saved: the saved copy answers, and the page says so
        bad = re.compile(r".*/data/fuel\.json(\?.*)?$")
        ctx.route(bad, lambda r: r.fulfill(status=500, body="boom"))
        st = pg.evaluate("() => fetch('data/fuel.json', {cache: 'no-store'}).then(r => [r.status, r.headers.get('x-pp-saved')])")
        assert st[0] == 200 and st[1], st
        pg.wait_for_function("() => !document.getElementById('offlineNote').hidden", timeout=5000)
        assert re.match(r"^Offline — saved [A-Z][a-z]{2} \d{1,2}, \d{4}", pg.inner_text("#offlineNote"))
        ctx.unroute(bad)
        # fully offline: the saved app and data load, with the notice
        ctx.set_offline(True)
        pg.reload(wait_until="load")
        pg.wait_for_function("() => typeof PL !== 'undefined' && NEWS.length > 150", timeout=60000)
        pg.wait_for_function("() => !document.getElementById('offlineNote').hidden", timeout=8000)
        assert pg.inner_text("#offlineNote").startswith("Offline — saved ")
        assert pg.evaluate(OVERFLOW) is None
        b.close()
    assert not errors, errors[:3]
