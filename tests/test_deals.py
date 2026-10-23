"""Deals: one card per transaction, followed from announcement to its end, and telling the same story as its storyline."""
import json, os, re, sys
import pytest
import common
from common import deal_tokens, deal_same, deal_status, deal_forward, deal_advance, deals_merged, record_deal
from conftest import ROOT
from test_app import site  # noqa: F401  (the local web server fixture)

sys.path.insert(0, str(ROOT / "tools"))

SEED_UNI = {"buyer": "MAK Acquisition Corp. (SPAC)", "target": "UniUni"}
# what the writer produced for MAK's termination notice on Oct. 20, 2026 (the deal that opened a second UniUni card)
TERMINATION = {"title": "MAK Acquisition terminates UniUni deal", "buyer": "MAK Acquisition Corp.", "target": "UniUni (Uni Express Inc.)",
               "value": "Undisclosed", "status": "Announced", "ann": "2026-05-15", "closed": None,
               "sum": "MAK Acquisition Corp. terminated its May 15, 2026 purchase agreement with Uni Express Inc. (UniUni).",
               "parties": [{"name": "MAK Acquisition Corp.", "role": "Buyer", "realm": "SPAC / public markets"},
                           {"name": "UniUni (Uni Express Inc.)", "role": "Target", "realm": "Regional / last-mile carrier"}]}
TERM_STORY = {"id": "afb6fa67940a7", "date": "2026-10-20", "title": "MAK Acquisition terminates UniUni purchase agreement",
              "url": "https://www.manilatimes.net/2026/10/20/tmt-newswire/globenewswire/mak-acquisition-terminates-purchase-agreement-with-uniuni/2449899",
              "src": "The Manila Times", "cat": "M&A"}


def test_fuzzy_matching():
    assert deal_tokens("MAK Acquisition Corp. (SPAC)") == ["mak"]
    assert deal_tokens("UniUni (Uni Express Inc.)") == ["uniuni"]
    assert deal_tokens("C.H. Robinson Worldwide") == ["ch", "robinson", "worldwide"]
    assert deal_same(SEED_UNI, TERMINATION)
    assert deal_same({"buyer": "Evri", "target": "Cross Border Connect"}, {"buyer": "Evri Group", "target": "Cross Border Connect"})
    assert deal_same({"buyer": "C.H. Robinson", "target": "RXO"}, {"buyer": "C.H. Robinson Worldwide", "target": "RXO"})
    assert deal_same({"buyer": "WWEX Group", "target": "Auctane"}, {"buyer": "Auctane", "target": "WWEX Group"})     # a merger either way round
    # different transactions stay apart
    assert not deal_same({"buyer": "C.H. Robinson", "target": "RXO"}, {"buyer": "C.H. Robinson", "target": "Coyote Logistics"})
    assert not deal_same({"buyer": "FedEx", "target": "InPost"}, {"buyer": "UPS", "target": "InPost"})
    assert not deal_same({"buyer": "Corp.", "target": "Inc."}, {"buyer": "Corp.", "target": "Inc."})               # nothing left to compare


def test_status_lifecycle():
    assert deal_status({"status": "Announced"}, "MAK Acquisition terminates UniUni deal") == "Terminated"
    assert deal_status({"status": "pending"}) == "Pending"
    assert deal_status({"status": "Withdrawn"}) == "Withdrawn"
    assert deal_status({"status": "Pending"}, "Regulators blocked the merger") == "Blocked"
    assert deal_forward("Terminated", "Pending") == "Terminated" and deal_forward("Closed", "Announced") == "Closed"
    assert deal_forward("Pending", "Announced") == "Pending" and deal_forward("Pending", "Terminated") == "Terminated"
    cur = {**SEED_UNI, "title": "UniUni to go public through MAK Acquisition", "ann": "2026-05-15", "d": "2026-05-15", "status": "Pending",
           "story": "60", "sum": "UniUni agreed to go public.", "checked": "2026-10-10", "srcs": [{"src": "GlobeNewswire", "url": "https://g/1"}]}
    ov = deal_advance(cur, TERMINATION, {**TERM_STORY, "srcs": [{"src": "The Manila Times", "url": TERM_STORY["url"]}]})
    assert ov["status"] == "Terminated" and ov["ended"] == "2026-10-20"
    assert ov["ann"] == "2026-05-15" and ov["title"] == cur["title"] and ov["story"] == "60"       # the card keeps its name and start
    assert (ov["buyer"], ov["target"]) == (SEED_UNI["buyer"], SEED_UNI["target"])
    assert [u["d"] for u in ov["updates"]] == ["2026-05-15", "2026-10-20"] and ov["updates"][-1]["story"] == "afb6fa67940a7"
    assert ov["sum"] == TERMINATION["sum"] and "Terminated" in ov["latest"]
    assert [s["url"] for s in ov["srcs"]] == ["https://g/1", TERM_STORY["url"]]
    # a late write-up still calling it pending doesn't reopen it, and keeps the end date
    later = deal_advance({**cur, **ov}, {**TERMINATION, "status": "Pending"}, {"id": "zz", "date": "2026-10-25", "title": "UniUni weighs options"})
    assert later["status"] == "Terminated" and later["ended"] == "2026-10-20" and len(later["updates"]) == 3


def test_update_overlays_the_existing_deal(data_dir):
    """A later step of a tracked deal is written keyed by that deal's buyer and target: one card, never a second one."""
    common.save("deals.json", [])
    seed = common.load("seed.json", {})["deals"]
    out = record_deal(dict(TERMINATION), dict(TERM_STORY))
    dl = common.load("deals.json", [])
    assert len(dl) == 1 and (dl[0]["buyer"], dl[0]["target"]) == (SEED_UNI["buyer"], SEED_UNI["target"])
    assert dl[0]["status"] == "Terminated" and dl[0]["ended"] == "2026-10-20" and dl[0]["ann"] == "2026-05-15"
    merged = deals_merged(seed, dl)
    assert len(merged) == len(seed)
    uni = [d for d in merged if "uniuni" in (d["buyer"] + d["target"]).lower()]
    assert len(uni) == 1 and uni[0]["status"] == "Terminated" and uni[0]["title"] == "UniUni to go public through MAK Acquisition"
    assert out["status"] == "Terminated"
    record_deal(dict(TERMINATION), dict(TERM_STORY))                      # the same story again changes nothing
    again = common.load("deals.json", [])
    assert len(again) == 1 and len(again[0]["updates"]) == len(dl[0]["updates"])
    # a new transaction still gets its own card
    record_deal({"title": "Acme buys Widget Co", "buyer": "Acme", "target": "Widget Co", "status": "Announced", "ann": "2026-10-21"},
                {"id": "new1", "date": "2026-10-21", "title": "Acme to buy Widget", "url": "https://x/1", "src": "X"})
    assert len(common.load("deals.json", [])) == 2


def test_terminated_deal_doesnt_set_owner(data_dir):
    import news as N
    mp = common.load("players.json", {"players": [], "edges": []})
    mp["edges"].append({"a": "mak", "b": "uniuni", "k": "acquired", "y": "2026", "t": "MAK agrees to buy UniUni (pending)", "url": "u", "story": "60"})
    mp.setdefault("moves", []).append({"id": "uniuni", "k": "pending", "pend": "mak", "d": "2026-05-15", "t": "pending"})
    common.save("players.json", mp)
    N.update_market_map({**TERMINATION, "status": "Terminated", "ended": "2026-10-20"}, dict(TERM_STORY))
    mp = common.load("players.json", {})
    assert not [p for p in mp["players"] if p["n"] == "UniUni (Uni Express Inc.)"]          # found as the UniUni already on the map
    assert not [e for e in mp["edges"] if {e["a"], e["b"]} == {"mak", "uniuni"} and e["k"] in ("acquired", "merged", "owns")]
    assert not [m for m in mp["moves"] if m.get("id") == "uniuni" and "mak" in (m.get("pend"), m.get("parent"))]
    # a closed deal still moves the target under its buyer
    N.update_market_map({"buyer": "MAK Acquisition Corp.", "target": "UniUni", "status": "Closed", "closed": "2026-11-01"},
                        {**TERM_STORY, "id": "c1", "title": "MAK completes UniUni deal"})
    mp = common.load("players.json", {})
    assert any(m.get("id") == "uniuni" and m.get("parent") == "mak" for m in mp["moves"])


def test_data_has_one_deal_per_transaction():
    seed = json.loads((ROOT / "data" / "seed.json").read_text())
    dl = json.loads((ROOT / "data" / "deals.json").read_text())
    merged = deals_merged(seed["deals"], dl)
    for i, d in enumerate(merged):
        assert not [e for e in merged[i + 1:] if deal_same(d, e)], d["title"]
    uni = [d for d in merged if "uniuni" in (d["buyer"] + d["target"]).lower()]
    assert len(uni) == 1
    u = uni[0]
    assert (u["status"], u["ann"], u["ended"]) == ("Terminated", "2026-05-15", "2026-10-20")
    assert [x["story"] for x in u["updates"]] == ["60", "nr4f8ee6", "afb6fa67940a7"] and u["latest"]
    players = json.loads((ROOT / "data" / "players.json").read_text())
    assert not [e for e in players["edges"] if {e["a"], e["b"]} <= {"mak", "uniuni", "uniuniuniexpre"} and e["k"] in ("acquired", "merged", "owns")]
    assert not [p for p in players["players"] if p["id"] == "uniuniuniexpre"]
    import repair_deals                                                    # the repair is deterministic: run again, nothing changes
    stories = {s["id"]: s for s in seed["news"]}
    assert repair_deals.fold(seed["deals"], dl, stories)[0] == dl


def test_audit_flags_deal_and_storyline_disagreeing():
    import audit
    seed = json.loads((ROOT / "data" / "seed.json").read_text())
    stories = {s["id"]: s for s in seed["news"] + json.loads((ROOT / "data" / "news.json").read_text())}
    threads = json.loads((ROOT / "data" / "threads.json").read_text())
    stale = [dict(d) for d in seed["deals"]]                               # the built-in card alone still says Pending
    bad = audit.deal_storyline_issues(stale, threads, stories)
    assert any(ids == ["uniuni", "afb6fa67940a7"] and "terminated" in msg and "Pending" in msg for ids, msg in bad), bad
    good = deals_merged(seed["deals"], json.loads((ROOT / "data" / "deals.json").read_text()))
    assert audit.deal_storyline_issues(good, threads, stories) == []


def test_app_shows_one_terminated_uniuni_deal(site):
    """The M&A list shows UniUni once, as terminated, linked to the UniUni storyline; the storyline shows the deal's status;
    and the terminated deal draws no ownership line from MAK to UniUni on the market map."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page(viewport={"width": 390, "height": 860})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.goto(site, wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && THREADS.uniuni"
                             " && DEALS.some(x => x.status === 'Terminated')", timeout=60000)
        assert pg.evaluate("() => DEALS.filter(x => /uniuni/i.test(x.buyer + ' ' + x.target)).length") == 1
        pg.click('nav.tabs [data-tab="mna"]')
        pg.evaluate("() => goTo('mna', 'deals')")
        pg.evaluate("() => renderDeals()")
        cards = pg.evaluate("""() => [...document.querySelectorAll('#nDeals article.deal2')].filter(a => /uniuni/i.test(a.querySelector('h3').textContent))
            .map(a => ({st: a.dataset.status, dates: a.querySelector('.ddates').textContent, thr: [...a.querySelectorAll('[data-thread]')].map(x => x.dataset.thread),
                        steps: a.querySelectorAll('.dsteps li').length, xs: a.querySelector('.xstage').textContent}))""")
        assert len(cards) == 1, cards
        c = cards[0]
        assert c["st"] == "Terminated" and "Announced May 15, 2026" in c["dates"] and "Terminated Oct 20, 2026" in c["dates"], c
        assert c["thr"] == ["uniuni"] and c["steps"] == 3
        # the walkthrough's deal step reads Announced -> Terminated, not "Closed / Not yet"
        steps = pg.evaluate("() => { const i = DEALS.findIndex(x => x.target === 'UniUni'); const s = dealScenes(DEALS[i]).find(z => z.k === 'deal'); return sceneVis(s, DEALS[i]) }")
        assert "Terminated" in steps and "Not yet" not in steps
        # the storyline shows the deal's status
        line = pg.evaluate("() => thrDeals('uniuni').map(x => dealStLine(x)).join('')")
        assert "Terminated" in line and "MAK" in line and "UniUni" in line
        # no ownership from a terminated deal
        assert pg.evaluate("() => PEDGES.filter(e => ['mak','uniuni'].includes(e.a) && ['mak','uniuni'].includes(e.b) && OWNK.has(e.k)).length") == 0
        assert pg.evaluate("() => [PL.uniuni.parent, PL.uniuni.pend || null, PL.uniuni.own]") == [None, None, "private"]
        assert pg.evaluate("() => coEvents(PL.uniuni, []).some(e => e.kind === 'ended' && /terminated oct 20, 2026/i.test(e.t))")
        b.close()
    assert not errors, errors[:5]
