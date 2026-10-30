"""B6 / B14: when a carrier's general rate increase lands as a Pricing & GRI story, the "not yet published" Docs note, the
"still waiting" story and the almanac's "not yet announced" entry for that carrier and year are closed (or sent to review).
Nothing keeps saying "not yet announced" once the announcement is on file."""
import json, re
import pytest
import themes as T
from common import load, save
from conftest import ROOT

GRI = {"id": "w847", "date": "2026-10-23", "c": ["UPS"], "cat": "Pricing & GRI", "imp": "up", "lvl": 3, "act": "2026-12-21",
       "title": "UPS announces Dec 21, 2026 rate increase, ZIP changes",
       "sum": "Effective December 21, 2026, Daily Rates for Ground, Air and International services rise an average net 5.9%.",
       "url": "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates",
       "srcs": [{"src": "UPS Rate and Service Guides", "url": "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates"}],
       "changes": [{"what": "Average Daily Rate increase for UPS Ground, UPS Air and International services",
                    "after": "Average net increase of 5.9%", "effective": "2026-12-21"}]}
WAIT = {"id": "07", "date": "2026-10-03", "c": ["UPS"], "cat": "Pricing & GRI", "imp": "watch", "lvl": 2,
        "title": "UPS has not yet announced 2027 rates", "sum": "UPS hasn't announced its 2027 GRI.", "url": "https://x.example/a"}
PLACE = {"carrier": "UPS", "year": 2027, "kind": "gri", "announced": None, "effective": None, "pct": None,
         "headline": "UPS 2027 general rate increase not yet announced", "details": ["No UPS 2027 GRI announcement found"],
         "sources": [], "conf": "partial", "note": "Do not show a 2027 UPS figure.", "id": "ups-2027-gri"}
FEDEX = {"carrier": "FedEx", "year": 2027, "kind": "gri", "announced": None, "effective": "2027-01-04", "pct": 5.9,
         "headline": "FedEx 2027 GRI: 5.9% average", "id": "fedex-2027-gri"}
DOC = {"c": "UPS", "t": "GRI notice", "n": "UPS 2027 general rate increase", "y": 2027, "eff": None, "u": None,
       "d": "Not yet published as of Oct 9, 2026", "cur": False, "checked": "2026-10-09"}
HUB = {"c": "UPS", "t": "Rate guide", "n": "UPS Shipping Zones and Rates hub", "y": 2026,
       "u": "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates", "d": "Hub"}


@pytest.fixture
def files(data_dir):
    save("news.json", [GRI])
    save("seed.json", {"news": [WAIT], "docs": [HUB, DOC]})
    save("docs.json", [dict(HUB), dict(DOC)])
    save("drop.json", [])
    save("review.json", [])
    return data_dir


def said_not_yet(e):
    return re.search(r"not yet (been )?announced", json.dumps(e), re.I)


def test_gri_story_closes_every_placeholder(files):
    alm = [dict(PLACE), dict(FEDEX)]
    done = T.close_placeholders(alm, today="2026-10-25")
    assert done
    ups = [e for e in alm if e["carrier"] == "UPS" and e["year"] == 2027 and e["kind"] == "gri"]
    assert ups and not any(said_not_yet(e) for e in ups)
    e = ups[0]
    assert e["pct"] == 5.9 and e["effective"] == "2026-12-21" and e["story"] == "w847" and e["conf"] == "review"
    assert e["announced"] is None                       # no announcement date stated in the story: never guessed
    assert next(x for x in alm if x["carrier"] == "FedEx") == FEDEX, "a real entry with its figure is left alone"
    doc = next(d for d in load("docs.json", []) if d["n"] == "UPS 2027 general rate increase")
    assert "not yet" not in doc["d"].lower() and doc["closed_by"] == "w847" and doc["cur"] is True
    assert doc["d"] == "UPS 2027 rate increase first reported Oct 23, 2026; takes effect Dec 21, 2026."
    # the hub page is already its own Docs entry: the app matches by address first, so the link goes in "see"
    assert doc["u"] is None and doc["see"] == HUB["u"]
    hub = next(d for d in load("docs.json", []) if d["n"] == HUB["n"])
    assert hub == HUB
    assert {"id": "07", "why": "Superseded by w847: " + GRI["title"]} in load("drop.json", [])
    assert any(r["type"] == "almanac-placeholder" and "not yet announced" in r["note"] for r in load("review.json", []))
    assert T.close_placeholders(alm, today="2026-10-25") == []          # nothing left to close; nothing repeated


def test_real_entry_replaces_the_placeholder(files):
    real = {"carrier": "UPS", "year": 2027, "kind": "gri", "announced": "2026-10-22", "effective": "2026-12-21", "pct": 5.9,
            "headline": "UPS 2027 GRI: 5.9% average", "id": "ups-2027-gri-2026-12-21"}
    alm = [dict(PLACE), real]
    T.close_placeholders(alm, today="2026-10-25")
    assert alm == [real]


def test_program_story_or_waiting_story_closes_nothing(files):
    sbr = dict(GRI, id="sbr", title="UPS raises Small Business Rates 4.5% and adds a 5% fuel surcharge",
               sum="Small Business Rates increase 4.5% on average from Dec 21, 2026.")
    save("news.json", [sbr, dict(WAIT, cat="Pricing & GRI", imp="up", title="Still waiting on UPS's 2027 rate increase")])
    alm = [dict(PLACE)]
    assert T.close_placeholders(alm, today="2026-10-25") == []
    assert alm == [PLACE] and load("drop.json", []) == []


def test_no_carrier_source_goes_to_review(files):
    press = dict(GRI, srcs=[{"src": "Supply Chain Dive", "url": "https://www.supplychaindive.com/news/ups-2027/1"}],
                 url="https://www.supplychaindive.com/news/ups-2027/1")
    save("news.json", [press])
    T.close_placeholders([dict(PLACE)], today="2026-10-25")
    doc = next(d for d in load("docs.json", []) if d["n"] == "UPS 2027 general rate increase")
    assert doc == DOC, "never pointed at a press article"
    assert any(r["type"] == "placeholder" and r["title"] == DOC["n"] for r in load("review.json", []))


def test_rate_year():
    assert T.rate_year({"act": "2026-12-21"}) == 2027          # mid-December increases are next year's rates
    assert T.rate_year({"act": "2027-01-04"}) == 2027
    assert T.rate_year({"act": "2026-07-12"}) == 2026
    assert T.rate_year({"title": "FedEx sets 2027 rates"}) == 2027
    assert T.rate_year({"title": "FedEx sets new rates"}) is None


def test_ask_coop_never_says_not_yet_announced_once_the_story_exists(files, data_dir):
    """Ask "UPS 2027 rate increase" in the app, with the almanac, news and drop list this rule wrote."""
    pw = pytest.importorskip("playwright.sync_api")
    from test_coop import ASK
    import functools, http.server, threading
    alm = json.loads((ROOT / "data" / "almanac.json").read_text())
    alm = [e for e in alm if not (e.get("carrier") == "UPS" and e.get("year") == 2027 and e.get("kind") == "gri")] + [dict(PLACE)]
    T.close_placeholders(alm, today="2026-10-25")
    save("almanac.json", alm)
    live = json.loads((ROOT / "data" / "news.json").read_text())
    save("news.json", [GRI] + [s for s in live if s.get("id") != GRI["id"]])
    served = {"almanac.json": load("almanac.json", []), "news.json": load("news.json", []), "drop.json": load("drop.json", [])}
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            ctx_route = lambda route: route.fulfill(status=200, content_type="application/json",
                                                    body=json.dumps(served[route.request.url.split("?")[0].rsplit("/", 1)[-1]]))
            b = p.chromium.launch(executable_path=__import__("os").environ.get("PP_CHROMIUM") or None)
            # no service worker: its fetches would skip the routes below and serve the real data files
            pg = b.new_context(viewport={"width": 1280, "height": 860}, service_workers="block").new_page()
            pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
            pg.route(re.compile(r"/data/(almanac|news|drop)\.json"), ctx_route)
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html", wait_until="load", timeout=60000)
            pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && window.askCoopAnswer", timeout=60000)
            a = pg.evaluate(ASK, "UPS 2027 rate increase")
            b.close()
    finally:
        srv.shutdown()
    assert [e for e in a["al"] if e["carrier"] == "UPS"], "the pricing history answers the question"
    box = a["h"].split('ak-alm', 1)[-1].split("</div></div>", 1)[0] if "ak-alm" in a["h"] else ""
    assert box and "not yet announced" not in box.lower()
    assert "UPS 2027 rate increase announced" in a["h"]


def test_a_closed_docs_entry_is_never_rewritten(files):
    """Oct 25, 2026: the closed UPS 2027 entry still says "Rate previews not yet published", and the next run rewrote it."""
    T.close_placeholders([dict(PLACE)], today="2026-10-25")
    first = next(d for d in load("docs.json", []) if d["n"] == "UPS 2027 general rate increase")
    first["d"] = "Announced Oct 23, 2026. Rate previews not yet published by UPS."
    save("docs.json", [dict(HUB), first])
    T.close_placeholders([dict(PLACE)], today="2026-10-26")
    again = next(d for d in load("docs.json", []) if d["n"] == "UPS 2027 general rate increase")
    assert again == first


def test_a_dated_new_charge_that_says_its_amount_is_not_yet_published_is_not_a_placeholder(files):
    surcharge = {"id": "ups-origin-zip-surcharge", "date": "2026-10-23", "c": ["UPS"], "cat": "Pricing & GRI", "imp": "up", "lvl": 3,
                 "act": "2026-12-21", "title": "UPS adds a surcharge on Ground packages from certain origin ZIPs; details not yet released",
                 "sum": "Effective December 21, 2026 or later. UPS has not yet published the amount, the origin ZIPs or the qualifying customers.",
                 "url": "https://x.example/s"}
    save("news.json", [GRI, surcharge])
    T.close_placeholders([dict(PLACE)], today="2026-10-25")
    assert "ups-origin-zip-surcharge" not in {d["id"] for d in load("drop.json", [])}
    assert "07" in {d["id"] for d in load("drop.json", [])}            # the real "still waiting" note still goes
