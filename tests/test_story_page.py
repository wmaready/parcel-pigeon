"""The story page: a headline, one synopsis and one "What it affects" block, with every fact kept and none repeated.
New stories carry a written synopsis (syn) and "affects" list (aff); both pass the same numbers check as the rest."""
import json, os, re
import pytest
import common
from test_app import site  # noqa: F401  (the local web server fixture)

STORY = {"id": "zz-test-story", "date": "2026-10-20", "c": ["UPS"], "cat": "Pricing & GRI", "kind": "News",
         "title": "UPS adds a $1.25 test surcharge", "imp": "up", "lvl": 2, "offc": True, "unconf": True,
         "sum": "UPS will add a $1.25 surcharge on test parcels from Nov. 2, the company said. The fee covers 40 ZIP codes.",
         "why": "UPS will add a $1.25 surcharge on test parcels from Nov. 2. About 12,000 shippers use the service.",
         "plain": "From Nov. 2, shippers pay $1.25 more per test parcel.",
         "tie": "UPS last changed test fees in March 2025.",
         "new": "The surcharge covers 40 ZIP codes. UPS also named Nov. 30 as a review date.",
         "act": "2026-11-02", "ann": "2026-10-15", "dates": [], "srcs": [{"src": "UPS", "url": "https://www.ups.com/x"}],
         "url": "https://www.ups.com/x", "src": "UPS"}


def _page(site, story):
    pw = pytest.importorskip("playwright.sync_api")
    p = pw.sync_playwright().start()
    b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
    pg = b.new_page(viewport={"width": 390, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
    pg.goto(site, wait_until="load", timeout=60000)
    pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && NEWS.length > 150", timeout=60000)
    pg.evaluate("s => { NEWS.push(s); openStory(s.id) }", story)
    pg.wait_for_selector("#storySheet.open .card.full", timeout=10000)
    return p, b, pg, errors


def test_story_page_is_one_synopsis_and_one_affects_block(site):
    p, b, pg, errors = _page(site, dict(STORY))
    try:
        body = pg.inner_text("#storySheet .card.full")
        html = pg.inner_html("#storySheet .card.full")
        # the old repeating boxes are gone
        for cls in ("why-line", "dsec", "snew", "srcd"):
            assert f'class="{cls}' not in html, cls
        assert pg.locator("#storySheet .syn").count() == 1 and pg.locator("#storySheet .aff").count() == 1
        # every figure from every field is still on the page
        src = " ".join(STORY[k] for k in ("sum", "why", "plain", "tie", "new"))
        for num in set(re.findall(r"\d[\d,.]*\d|\d", src)):
            assert num in body, f"lost the figure {num}"
        # and no sentence is said twice
        assert body.count("UPS will add a $1.25 surcharge on test parcels from Nov. 2") == 1
        assert body.count("The surcharge covers 40 ZIP codes") + body.count("The fee covers 40 ZIP codes") == 1
        aff = pg.inner_text("#storySheet .aff")
        # effective and announced dates kept apart, each in its own row
        assert re.search(r"Takes effect\s+Nov 2, 2026", aff) and re.search(r"Announced\s+Oct 15, 2026\s+18 days' notice", aff), aff
        assert "OFF-CYCLE" in aff.upper() and "UNCONFIRMED" in aff.upper()
        # the header no longer repeats those tags
        assert "Off-cycle" not in pg.inner_text("#storySheet .cardhd")
    finally:
        b.close(); p.stop()
    assert not errors, errors[:3]


def test_story_page_uses_written_synopsis_and_affects(site):
    s = dict(STORY, id="zz-test-story2", syn="UPS adds a $1.25 surcharge on test parcels from Nov. 2 across 40 ZIP codes.",
             aff=[{"who": "Test parcel shippers", "what": "Pay $1.25 more per parcel from Nov. 2."}])
    p, b, pg, errors = _page(site, s)
    try:
        aff = pg.inner_text("#storySheet .aff")
        assert "Test parcel shippers" in aff and "Pay $1.25 more per parcel" in aff
        syn = pg.inner_text("#storySheet .syn")
        assert syn.startswith("UPS adds a $1.25 surcharge on test parcels from Nov. 2 across 40 ZIP codes.")
        assert "12,000" in syn          # the "why" line still adds its one new figure
    finally:
        b.close(); p.stop()
    assert not errors, errors[:3]


def test_page_parts_cleans_reply():
    import news as N
    out = N.page_parts({"syn": "  Two  lines. ", "aff": [{"who": "Shippers", "what": " Pay more. "}, {"who": "x"}, "junk"]})
    assert out == {"syn": "Two lines.", "aff": [{"who": "Shippers", "what": "Pay more."}]}
    assert N.page_parts({"aff": "no"}) == {} and N.page_parts(None) == {}
    assert "syn" in N.WRITE_SYSTEM and '"aff"' in N.WRITE_SYSTEM


@pytest.fixture
def written(data_dir, monkeypatch):
    """One news run where Claude's synopsis is sound for one story and quotes a figure the sources don't have for another."""
    import news as N
    items = [{"title": f"FedEx story {w}", "url": f"https://www.freightwaves.com/{w}", "summary": "FedEx parcel", "date": "2026-10-18",
              "src": "FreightWaves", "direct": False, "house": False, "tier": 2} for w in ("good", "bad")]

    def fake_claude(model, system, user, max_tokens=0):
        if system == N.TRIAGE_SYSTEM:
            lines = [l for l in user.split("NEW ITEMS:\n")[1].splitlines() if l[:1].isdigit()]
            return json.dumps([{"i": int(l.split(".")[0]), "keep": True, "carriers": ["FedEx"], "category": "Network & operations",
                                "kind": "News", "event": "ev" + l.split("story ")[1].split()[0], "same_as": None, "fit": "core", "thread": None}
                               for l in lines])
        hl = re.search(r"Headline: (.*)", user).group(1)
        fee = "$4.10" if "bad" in hl else "$2.50"
        return json.dumps({"title": hl, "sum": "FedEx adds a $2.50 fee.", "plain": "Shippers pay $2.50 more.", "imp": "up", "lvl": 1,
                           "syn": f"FedEx adds a {fee} fee on hub parcels.", "aff": [{"who": "Hub shippers", "what": f"Pay {fee} more."}],
                           "carriers": ["FedEx"], "category": "Network & operations", "kind": "News"})

    monkeypatch.setattr(N, "collect", lambda cfg, primary_only=False: list(items))
    monkeypatch.setattr(N, "similar", lambda a, b: False)
    monkeypatch.setattr(N, "claude", fake_claude)
    monkeypatch.setattr(N, "article_text", lambda u: ("FedEx adds a $2.50 fee to hub parcels. " * 30, u))
    monkeypatch.setattr(N, "find_coverage", lambda t, days=14: [])
    monkeypatch.setattr(N, "find_primary", lambda q, c: None)
    monkeypatch.setattr(N, "lead_image", lambda u: None)
    monkeypatch.setattr(N, "is_covered", lambda t, days=4: ["FreightWaves"])
    monkeypatch.setattr(N, "publish_extras", lambda *a, **k: None)
    for f, v in (("news.json", []), ("seen.json", []), ("review.json", []), ("threads.json", {})):
        common.save(f, v)
    N.main()
    return {s["title"]: s for s in common.load("news.json", [])}


def test_synopsis_passes_the_numbers_check(written):
    good, bad = written["FedEx story good"], written["FedEx story bad"]
    assert good["syn"] == "FedEx adds a $2.50 fee on hub parcels." and good["aff"][0]["who"] == "Hub shippers"
    # $4.10 is not in the article: the story still publishes, with the checked summary and effect instead
    assert "syn" not in bad and "aff" not in bad and bad["sum"] == "FedEx adds a $2.50 fee."
