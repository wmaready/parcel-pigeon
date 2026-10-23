"""News intake: no headline is ever lost, the best outlet leads, and a story carries the date the news broke."""
import json, re
import pytest
import common
from common import h

SRCS = [("RiverheadLOCAL", 3, "riverheadlocal.com"), ("The Wall Street Journal", 1, "wsj.com"), ("FreightWaves", 2, "freightwaves.com")]
WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima",
         "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey"]


@pytest.fixture
def news(data_dir, monkeypatch):
    import news as N
    items = []
    for e in range(23):
        for k, (src, t, dom) in enumerate(SRCS if e == 0 else SRCS[2:]):
            items.append({"title": f"Carrier{e} story {WORDS[e]}", "url": f"https://{dom}/e{e}-{k}", "summary": "FedEx parcel",
                          "date": f"2026-10-1{5 - k if e == 0 else 8}", "src": src, "direct": False, "house": False, "tier": t})

    def fake_claude(model, system, user, max_tokens=0):
        if system == N.TRIAGE_SYSTEM:
            lines = [l for l in user.split("NEW ITEMS:\n")[1].splitlines() if l[:1].isdigit()]
            if int(lines[0].split(".")[0]) >= 20:
                raise RuntimeError("API down")          # the second screening batch fails
            return json.dumps([{"i": int(l.split(".")[0]), "keep": True, "carriers": ["FedEx"], "category": "Network & operations",
                                "kind": "News", "event": "ev" + l.split("story ")[1].split()[0], "same_as": None, "fit": "core", "thread": None}
                               for l in lines])
        hl = re.search(r"Headline: (.*)", user).group(1)
        return json.dumps({"title": hl, "sum": "FedEx closes a hub.", "plain": "No change to rates or service.", "imp": "info", "lvl": 1,
                           "carriers": ["FedEx"], "category": "Network & operations", "kind": "News"})

    monkeypatch.setattr(N, "collect", lambda cfg, primary_only=False: list(items))
    monkeypatch.setattr(N, "similar", lambda a, b: False)
    monkeypatch.setattr(N, "claude", fake_claude)
    monkeypatch.setattr(N, "article_text", lambda u: ("FedEx closes hub text " * 50, u))
    monkeypatch.setattr(N, "find_coverage", lambda t, days=14: [])
    monkeypatch.setattr(N, "find_primary", lambda q, c: None)
    monkeypatch.setattr(N, "lead_image", lambda u: None)
    monkeypatch.setattr(N, "is_covered", lambda t, days=4: ["FreightWaves"])
    monkeypatch.setattr(N, "publish_extras", lambda *a, **k: None)
    monkeypatch.setattr(common, "paused", lambda extra=False: None)   # the news is running (the paused case: test_lanes.py)
    monkeypatch.setattr(N, "MAX_NEW_PER_RUN", 3)
    monkeypatch.setattr(N, "MAX_SCREEN", 20)
    for f, v in (("news.json", []), ("seen.json", []), ("review.json", []), ("threads.json", {"x": {"n": "x", "ids": [], "last": "2000-01-01"}})):
        common.save(f, v)
    N.main()
    return items


def test_no_headline_is_lost(news):
    live, seen = common.load("news.json", []), set(common.load("seen.json", []))
    assert len(live) == 3
    unwritten = [i for i in news if not any(i["url"] in json.dumps(s) for s in live)]
    assert unwritten, "the test needs some events over budget"
    lost = [i["url"] for i in unwritten if h(i["url"]) in seen]
    assert not lost, f"marked seen but never written: {lost}"


def test_best_outlet_leads_and_dates_story(news):
    s0 = next(s for s in common.load("news.json", []) if "alpha" in s["title"])
    assert s0["srcs"][0]["src"] == "The Wall Street Journal"
    assert s0["date"] == "2026-10-14"        # the WSJ report, earlier than the local site's


def test_small_outlet_only_is_unconfirmed(news):
    live = common.load("news.json", [])
    assert all(not s.get("unconf") for s in live), "stories led by the WSJ or FreightWaves are confirmed"
    import news as N
    story = {"id": "x", "srcs": [{"src": "RiverheadLOCAL", "url": "https://riverheadlocal.com/a"}], "unconf": True}
    N.add_source(story, {"src": "Supply Chain Dive", "date": "2026-10-20"}, "https://www.supplychaindive.com/news/a")
    assert "unconf" not in story and story["srcs"][0]["src"] == "Supply Chain Dive"


def test_unconfirmed_rule():
    import news as N
    one_small = {"cat": "M&A", "srcs": [{"src": "Vietnam.vn", "url": "https://vietnam.vn/a"}]}
    assert N.unconfirmed(one_small)
    assert not N.unconfirmed({**one_small, "cat": "Drones & robots", "lvl": 1})                # low stakes: no mark
    assert not N.unconfirmed({**one_small, "srcs": one_small["srcs"] + [{"src": "City Limits", "url": "https://citylimits.org/b"}]})
    assert not N.unconfirmed({**one_small, "srcs": [{"src": "Reuters", "url": "https://www.reuters.com/a"}]})
    assert not N.unconfirmed({**one_small, "srcs": [{"src": "Sen. Merkley", "url": "https://www.merkley.senate.gov/a"}]})
