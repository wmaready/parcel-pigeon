"""Coop: Ask Coop answers from the pricing history, verified company facts and stories with their dates kept apart,
links each story (#s=) and company page (#c=), and says "unconfirmed"; storyline narration follows the same date rules."""
import json, os, re
import pytest
import common
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local server fixture)


# ---------------------------------------------------------------- storyline narration (news.py)
def test_milestone_line_keeps_dates_apart_and_flags():
    import news as N
    s = {"id": "a1", "date": "2026-10-13", "title": "GOFO adds fuel surcharge", "sum": "From Oct. 26.", "ann": "2026-10-10",
         "act": "2026-10-26", "offc": True, "unconf": True}
    line = N.milestone_line(s)
    assert "reported 2026-10-13" in line
    assert "announced 2026-10-10; takes effect 2026-10-26" in line
    assert "OFF-CYCLE" in line and "UNCONFIRMED" in line
    # a missing date is said to be missing, never borrowed from the other one or the reported date
    only = N.milestone_line({"id": "a2", "date": "2026-10-13", "title": "t", "sum": "s", "act": "2026-11-01"})
    assert "announced date not stated; takes effect 2026-11-01" in only
    plain = N.milestone_line({"id": "a3", "date": "2026-10-13", "title": "t", "sum": "s"})
    assert "announced" not in plain and "UNCONFIRMED" not in plain


def test_narration_prompt_has_the_date_and_unconfirmed_rules():
    import news as N
    assert "Never call a takes-effect date an announcement date" in N.BEATS
    assert "UNCONFIRMED" in N.BEATS and "reportedly" in N.BEATS
    assert N.BEATS_V >= 3


def test_narration_drops_unconfirmed_line_stated_as_fact(data_dir, monkeypatch):
    import news as N
    S = [{"id": "s1", "date": "2026-10-01", "c": ["UPS"], "title": "UPS adds a fee", "sum": "UPS adds a fee on Nov. 2.", "act": "2026-11-02"},
         {"id": "s2", "date": "2026-10-05", "c": ["UPS"], "title": "UPS fee widened", "sum": "A blog says UPS widens the fee.", "unconf": True},
         {"id": "s3", "date": "2026-10-07", "c": ["UPS"], "title": "UPS fee clarified", "sum": "Another blog says more.", "unconf": True}]
    common.save("news.json", S)
    common.save("threads.json", {"t": {"n": "UPS fee", "ids": ["s1", "s2", "s3"], "last": "2026-10-07"}})
    sent = []

    def fake(model, system, user, max_tokens=0):
        sent.append(user)
        return json.dumps({"intro": "UPS is changing a fee.", "beats": {"s1": "UPS adds the fee.", "s2": "UPS widens the fee.",
                                                                         "s3": "UPS reportedly clarifies the fee."}})
    monkeypatch.setattr(N, "claude", fake)
    N.write_beats()
    cx = common.load("threads.json", {})["t"]["cx"]
    assert "s2" not in cx["beats"]          # stated as fact: dropped, the app shows a plain date cue
    assert cx["beats"]["s3"].startswith("UPS reportedly") and "s1" in cx["beats"]
    assert "UNCONFIRMED" in sent[0] and "takes effect 2026-11-02" in sent[0]


def test_narration_context_uses_verified_facts_and_labels_dates(data_dir):
    import news as N
    pj = common.load("players.json", {})
    pj.setdefault("facts", {})["ups"] = {"hq": "Testville, GA, USA", "yr": "1907", "vf": "2026-10-21", "src": []}
    common.save("players.json", pj)
    common.save("almanac.json", [{"carrier": "UPS", "year": 2026, "kind": "surcharge", "announced": "2026-09-01",
                                  "effective": "2026-10-20", "headline": "UPS test surcharge", "id": "x"}])
    ctx = N.thread_context([{"id": "s", "date": "2026-10-01", "c": ["UPS"], "title": "t"}], common.load("seed.json", {}), [])
    assert "HQ Testville, GA, USA" in ctx
    assert "PRICING HISTORY UPS: UPS test surcharge; announced 2026-09-01; takes effect 2026-10-20." in ctx


# ---------------------------------------------------------------- Ask Coop in the browser
def _page(p, url, width=390):
    b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
    pg = b.new_page(viewport={"width": width, "height": 860})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())     # the test never leaves this machine
    pg.goto(url, wait_until="load", timeout=60000)
    pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && window.askCoopAnswer", timeout=60000)
    return b, pg, errors


ASK = "q => askCoopAnswer(q).then(a => ({h: a.h, ctx: a.ctx, al: a.al.map(e => ({id: e.id, carrier: e.carrier, kind: e.kind, " \
      "announced: e.announced, effective: e.effective})), pl: a.pl.map(p => p.id), ns: a.ns.map(n => ({id: n.id, unconf: !!n.unconf, offc: !!n.offc}))}))"


def test_ask_coop_answers_from_history_facts_and_stories(site):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    alm = json.loads((ROOT / "data" / "almanac.json").read_text())
    with pw.sync_playwright() as p:
        b, pg, errors = _page(p, site)
        today = pg.evaluate("() => TODAY")

        # announced vs effective: two labelled dates, never swapped, a missing one said to be missing
        gri = next(e for e in alm if e["carrier"] == "UPS" and e["year"] == 2026 and e["kind"] == "gri")
        a = pg.evaluate(ASK, "When was the 2026 UPS GRI announced vs effective?")
        assert a["al"] and a["al"][0]["id"] == gri["id"]
        assert all(e["carrier"] == "UPS" for e in a["al"])
        eff = pg.evaluate("d => fmtD(d, {month: 'short', day: 'numeric', year: 'numeric'})", gri["effective"])
        ann = pg.evaluate("d => fmtD(d, {month: 'short', day: 'numeric', year: 'numeric'})", gri["announced"]) if gri["announced"] else "date not on file"
        assert f"Announced: {ann} · Takes effect: {eff}" in a["h"]
        assert any(f"Takes effect: {eff}" in c and f"Announced: {ann}" in c for c in a["ctx"])

        # off-cycle this year: only off-cycle changes, only FedEx, only this year
        a = pg.evaluate(ASK, "What off-cycle changes has FedEx made this year?")
        assert a["al"] or a["ns"], "nothing off-cycle found for FedEx"
        for e in a["al"]:
            assert e["carrier"] == "FedEx"
            assert pg.evaluate("e => cycleOf(e.carrier, e.kind, e.effective, e.announced)", e) == "off"
        assert all(s["offc"] for s in a["ns"])
        assert "Off-cycle" in a["h"]

        # company facts, with a #c= link to the company page
        a = pg.evaluate(ASK, "Where is UPS headquartered?")
        hq = pg.evaluate("() => PL.ups.hq")
        assert "ups" in a["pl"] and hq and hq in a["h"]
        assert 'href="#c=ups"' in a["h"]

        # whole words only: "OnTrac" is not the "ontrac" in "contract"
        a = pg.evaluate(ASK, "Who owns OnTrac?")
        for s in a["ns"]:
            t = pg.evaluate("id => { const n = NEWS.find(n => n.id === id); return n.title + ' ' + n.sum }", s["id"])
            assert re.search(r"\b(OnTrac|LaserShip)", t, re.I), t[:120]

        # an unconfirmed story says so, and links with #s=
        unc = pg.evaluate("() => { const n = NEWS.find(n => n.unconf && n.title && n.title.split(' ').length > 4); return n && {id: n.id, title: n.title} }")
        if unc:
            a = pg.evaluate(ASK, unc["title"])
            assert {"id": unc["id"], "unconf": True} in [{"id": s["id"], "unconf": s["unconf"]} for s in a["ns"]]
            assert f'href="#s={unc["id"]}"' in a["h"] and "Unconfirmed" in a["h"]
            assert any("UNCONFIRMED" in c for c in a["ctx"])

        # a vetted note whose figure has since changed carries a warning above it
        kb = json.loads((ROOT / "data" / "coop.json").read_text())
        dimnote = next((f for f in kb["facts"] if "usps" in f["k"] and "166" in f["t"]), None)
        moved = next((e for e in alm if e["carrier"] == "USPS" and re.search(r"from 166 to 139", e["headline"]) and e["effective"] <= today), None)
        if dimnote and moved:
            a = pg.evaluate(ASK, "USPS dim divisor")
            assert "Changed since this note" in a["h"] and "139" in a["h"]
        b.close()
    assert not errors, errors[:5]


def test_ask_coop_panel_links_open_story_and_company(site):  # noqa: F811
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b, pg, errors = _page(p, site)
        pg.evaluate("() => askCoop('Where is UPS headquartered?')")
        pg.wait_for_selector(".akout a[data-akc]", timeout=20000)
        wide = pg.evaluate(OVERFLOW)
        pw_ = pg.evaluate("() => { const r = document.querySelector('.akpanel').getBoundingClientRect(); return [r.left, r.right, innerWidth] }")
        assert pw_[0] >= 0 and pw_[1] <= pw_[2]
        pg.click(".akout a[data-akc='ups']")
        pg.wait_for_function("() => CO_OPEN === 'ups'", timeout=20000)
        assert pg.evaluate("() => document.querySelector('.akwrap').hidden")
        pg.evaluate("() => closeCompany && closeCompany()")
        pg.wait_for_timeout(300)
        sid = pg.evaluate("() => NEWS.find(n => /UPS/.test(n.title)).id")
        title = pg.evaluate("id => NEWS.find(n => n.id === id).title", sid)
        pg.evaluate("q => askCoop(q)", title)
        pg.wait_for_selector(f".akout a[data-aks='{sid}']", timeout=20000)
        pg.click(f".akout a[data-aks='{sid}']")
        pg.wait_for_function("id => STORY_OPEN === id", arg=sid, timeout=20000)
        b.close()
    assert not errors, errors[:5]
    assert not wide, wide
