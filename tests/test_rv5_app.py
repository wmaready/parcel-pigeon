"""Review v5 app fixes (B6, B7, B8, B14, B20, B23-B27, B35): the app shows closed-out placeholders, corrected wording,
per-carrier fuel weeks, and the new layout pieces without page errors or sideways scrolling."""
import json, re
import pytest
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local web server fixture)
from test_polish import app


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
