"""B16: an article's own publish date decides whether it is news (the 2018 Amazon story shown as Oct 2026 news).
B17: a story's link must lead to a page that names its people, companies and places (the Larsen interview that linked to
an unrelated Amazon Germany page). Saved page fixtures; no network."""
import json, re
import pytest
import common
import news as N

MASHABLE = """<html><head><title>Amazon close to launching Shipping With Amazon delivery service, WSJ report says</title>
<meta property="article:published_time" content="2018-02-09T19:21:44Z"></head><body>
<p>Amazon is getting closer to launching its own delivery service, called Shipping With Amazon, according to a new report.</p></body></html>"""
JSONLD = """<html><head><title>Amazon close to launching Shipping With Amazon</title>
<script type="application/ld+json">{"@type":"NewsArticle","headline":"Amazon close to launching Shipping With Amazon","datePublished":"2018-02-09T14:00:00-05:00"}</script>
</head><body><p>Amazon is getting closer to launching its own delivery service, called Shipping With Amazon, according to a report.</p></body></html>"""
GERMANY = """<html><head><title>Amazon announces plan to invest €16 billion in Germany in 2027</title>
<meta property="article:published_time" content="2026-10-15T08:00:00Z"></head><body>
<p>Amazon today announced it plans to invest more than €16 billion in Germany in 2027, expanding its logistics and cloud infrastructure.</p></body></html>"""
INTERVIEW = """<html><head><title>Amazon's Larsen says logistics network opened after seller demand</title>
<meta property="article:published_time" content="2026-10-16T08:00:00Z"></head><body>
<p>Amazon's Udit Larsen said the company opened its logistics network to outside shippers after demand from sellers grew.</p></body></html>"""

OLD_TITLE = "Amazon close to launching Shipping With Amazon, WSJ report says"
LARSEN = "Amazon's Larsen says logistics network opened after seller demand"


def test_page_meta_reads_the_articles_own_date():
    assert N.page_meta(MASHABLE)["published"] == "2018-02-09"
    assert N.page_meta(JSONLD)["published"] == "2018-02-09"
    m = N.page_meta(GERMANY)
    assert m["title"].startswith("Amazon announces plan to invest") and m["first"].startswith("Amazon today announced")


def test_old_article_is_kept_out(monkeypatch):
    monkeypatch.setattr(N, "META", {"https://mashable.com/2018/02/09/amazon-shipping": N.page_meta(MASHABLE)})
    texts = [({"title": OLD_TITLE}, "https://mashable.com/2018/02/09/amazon-shipping", "text " * 100)]
    srcs = [{"src": "Mashable", "url": "https://mashable.com/2018/02/09/amazon-shipping"}]
    keep, srcs2, problems = N.vet_sources(texts, srcs, today="2026-10-18")
    assert keep == [] and srcs2 == [] and "2018-02-09" in problems[0]
    # a fresh article passes: 30 days is the line
    monkeypatch.setitem(N.META, "https://mashable.com/2018/02/09/amazon-shipping", dict(N.page_meta(MASHABLE), published="2026-09-18"))
    assert N.vet_sources(texts, srcs, today="2026-10-18")[0] == texts


def test_unrelated_destination_is_not_verified():
    assert N.content_verified(N.page_meta(GERMANY), LARSEN) is False          # names Amazon, never Larsen
    assert N.content_verified(N.page_meta(INTERVIEW), LARSEN) is True
    assert N.content_verified({}, LARSEN) is None                              # nothing read: nothing claimed either way
    assert N.key_names(LARSEN) == ["Amazon", "Larsen"]


@pytest.fixture
def run(data_dir, monkeypatch):
    """One news run over three headlines: the 2018 article, the Larsen story linked to the Germany page, and a good one."""
    pages = {"https://mashable.com/2018/02/09/amazon-shipping": MASHABLE,
             "https://www.aboutamazon.eu/news/germany-invest": GERMANY,
             "https://trade.example/larsen-interview": INTERVIEW}
    items = [{"title": OLD_TITLE, "url": "https://mashable.com/2018/02/09/amazon-shipping", "summary": "Amazon", "date": "2026-10-18",
              "src": "Mashable", "direct": False, "house": False, "tier": 2},
             {"title": LARSEN, "url": "https://www.aboutamazon.eu/news/germany-invest", "summary": "Amazon", "date": "2026-10-16",
              "src": "About Amazon", "direct": False, "house": False, "tier": 2},
             {"title": "Amazon's Larsen explains why the logistics network opened", "url": "https://trade.example/larsen-interview",
              "summary": "Amazon", "date": "2026-10-16", "src": "Trade", "direct": False, "house": False, "tier": 2}]
    items[2]["title"] = LARSEN

    def fake_claude(model, system, user, max_tokens=0):
        if system == N.TRIAGE_SYSTEM:
            lines = [l for l in user.split("NEW ITEMS:\n")[1].splitlines() if l[:1].isdigit()]
            return json.dumps([{"i": int(l.split(".")[0]), "keep": True, "carriers": ["Amazon"], "category": "Network & operations",
                                "kind": "News", "event": "ev" + l.split(".")[0], "same_as": None, "fit": "core", "thread": None} for l in lines])
        hl = re.search(r"Headline: (.*)", user).group(1)
        return json.dumps({"title": hl, "sum": "Amazon opened its network.", "plain": "No change to rates or service.", "imp": "info",
                           "lvl": 1, "carriers": ["Amazon"], "category": "Network & operations", "kind": "News"})

    def fake_article(u):
        N.META[u] = N.page_meta(pages[u])
        return ("Amazon logistics network text " * 40, u)
    monkeypatch.setattr(N, "META", {})
    monkeypatch.setattr(N, "collect", lambda cfg, primary_only=False: list(items))
    monkeypatch.setattr(N, "similar", lambda a, b: False)
    monkeypatch.setattr(N, "claude", fake_claude)
    monkeypatch.setattr(N, "article_text", fake_article)
    monkeypatch.setattr(N, "find_coverage", lambda t, days=14: [])
    monkeypatch.setattr(N, "find_primary", lambda q, c: None)
    monkeypatch.setattr(N, "lead_image", lambda u: None)
    monkeypatch.setattr(N, "is_covered", lambda t, days=4: ["FreightWaves"])
    monkeypatch.setattr(N, "publish_extras", lambda *a, **k: None)
    monkeypatch.setattr(common, "paused", lambda extra=False: None)
    for f, v in (("news.json", []), ("seen.json", []), ("review.json", []), ("threads.json", {})):
        common.save(f, v)
    N.main()


def test_news_run_keeps_old_and_mislinked_stories_out(run):
    live, review = common.load("news.json", []), common.load("review.json", [])
    urls = json.dumps(live)
    assert "mashable.com" not in urls and "germany-invest" not in urls
    assert any("larsen-interview" in s["url"] for s in live)                    # the real interview page publishes
    old = next(r for r in review if r["type"] == "old-article")
    assert old["title"] == OLD_TITLE and "Reminder or Background" in old["note"]
    bad = next(r for r in review if r["type"] == "content-mismatch")
    assert bad["content_verified"] is False and "germany-invest" in bad["url"]
