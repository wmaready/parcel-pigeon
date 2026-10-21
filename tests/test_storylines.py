"""Storylines: one company's saga is one storyline, whichever outlet reports the next chapter, and a story is tied only to
the companies it is about."""
import json, sys
import common
from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))


def test_data_has_one_uniuni_storyline():
    threads = json.loads((ROOT / "data" / "threads.json").read_text())
    uni = [k for k, t in threads.items() if "uniuni" in (k + " " + (t.get("n") or "") + " " + (t.get("co") or "")).lower()]
    assert uni == ["uniuni"], uni
    t = threads["uniuni"]
    assert {"afb6fa67940a7", "accf814d7d663", "nr4f8ee6", "60"} <= set(t["ids"])
    assert {"uniuni-mak-acquisition", "uniuni-delivery-complaints"} <= set(t["was"])
    for gone in ("royal-mail-dm26", "cbp-low-value-import-filing", "ups-parcel-pivot"):
        assert gone not in threads


def test_merge_tool_is_idempotent():
    import merge_storylines as M
    threads = json.loads((ROOT / "data" / "threads.json").read_text())
    dates = {s["id"]: s.get("date") for s in common.load("seed.json", {}).get("news", []) + common.load("news.json", [])}
    before = json.dumps(threads, sort_keys=True)
    assert M.run(threads, dates) == []
    assert json.dumps(threads, sort_keys=True) == before


def test_merge_threads_keeps_ids_beats_and_newest_status():
    import news as N
    threads = {
        "acme-deal": {"n": "Acme deal", "s": "old", "ids": ["a1", "a3"], "last": "2026-05-01", "c": ["Regional"], "rv": "x",
                      "cx": {"sig": "s", "v": 2, "beats": {"a1": "First step.", "zz": "gone"}, "intro": "About Acme.", "now": "Old now."}},
        "acme-complaints": {"n": "Acme complaints", "s": "newest", "ids": ["a2"], "last": "2026-10-01", "c": ["Industry"],
                            "cx": {"sig": "t", "v": 2, "beats": {"a2": "Second step."}, "now": "New now."}},
    }
    live = [{"id": "a2", "thread": "acme-complaints"}]
    dates = {"a1": "2026-01-01", "a2": "2026-10-01", "a3": "2026-05-01"}
    t = N.merge_threads(threads, "acme-complaints", "acme-deal", dates, live)
    assert list(threads) == ["acme-deal"]
    assert t["ids"] == ["a1", "a3", "a2"] and t["first"] == "2026-01-01" and t["last"] == "2026-10-01"
    assert t["s"] == "newest" and t["cx"]["now"] == "New now." and t["cx"]["intro"] == "About Acme."
    assert t["cx"]["beats"] == {"a1": "First step.", "a2": "Second step."}
    assert t["cx"]["sig"] is None and "rv" not in t          # narration and review run again
    assert t["was"] == ["acme-complaints"] and t["c"] == ["Industry", "Regional"]
    assert live[0]["thread"] == "acme-deal"
    assert N.resolve_thread(threads, "acme-complaints") == "acme-deal"


def test_new_storyline_for_same_company_joins_its_saga(data_dir, monkeypatch):
    """The model proposes a new key for a company that already has a storyline: it is asked whether it's the same saga,
    and on yes the story joins the existing storyline instead of opening a second one."""
    import news as N
    asked = []

    def fake_claude(model, system, user, max_tokens=0):
        if system == N.TRIAGE_SYSTEM:
            assert "acme-funding: Acme funding and SPAC deal [Acme]" in user          # storylines show their company
            return json.dumps([{"i": 0, "keep": True, "carriers": ["Regional"], "company": "Acme", "category": "Regional & alternative",
                                "kind": "News", "event": "e0", "same_as": None, "fit": "core", "thread": "acme-delivery-complaints"}])
        if system == N.SAGA:
            asked.append(user)
            return json.dumps({"same": "acme-funding"})
        return json.dumps({"title": "Acme responds to delivery complaints", "sum": "Acme said it is reviewing complaints.",
                           "plain": "No change to rates or service.", "imp": "info", "lvl": 1, "carriers": ["Regional"],
                           "category": "Regional & alternative", "kind": "News", "thread_name": "Acme complaints", "status": "Under review."})

    item = {"title": "Acme responds to delivery complaints", "url": "https://www.freightwaves.com/acme", "summary": "Acme parcel",
            "date": "2026-10-20", "src": "FreightWaves", "direct": False, "house": False, "tier": 2}
    monkeypatch.setattr(N, "collect", lambda cfg, primary_only=False: [dict(item)])
    monkeypatch.setattr(N, "claude", fake_claude)
    monkeypatch.setattr(N, "article_text", lambda u: ("Acme parcel delivery complaints text " * 40, u))
    for name, fn in (("find_coverage", lambda t, days=14: []), ("find_primary", lambda q, c: None), ("lead_image", lambda u: None),
                     ("is_covered", lambda t, days=4: ["FreightWaves"]), ("publish_extras", lambda *a, **k: None)):
        monkeypatch.setattr(N, name, fn)
    import datetime as dt
    recent = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    common.save("news.json", [{"id": "old1", "date": recent, "title": "Acme to go public through a SPAC", "c": ["Regional"]}])
    common.save("seen.json", []); common.save("review.json", [])
    common.save("threads.json", {"acme-funding": {"n": "Acme funding and SPAC deal", "co": "Acme", "ids": ["old1"], "first": recent, "last": recent}})
    N.main()
    threads = common.load("threads.json", {})
    assert asked, "the same-saga check ran"
    assert set(threads) == {"acme-funding"}
    story = next(s for s in common.load("news.json", []) if s["id"] != "old1")
    assert story["thread"] == "acme-funding" and threads["acme-funding"]["ids"][-1] == story["id"]
    assert threads["acme-funding"]["n"] == "Acme funding and SPAC deal"      # an existing storyline keeps its name


def test_saga_candidates_need_the_same_company():
    import news as N
    import datetime as dt
    d = dt.date.today().isoformat()
    threads = {"uniuni": {"n": "UniUni: funding, SPAC deal and complaints", "co": "UniUni", "last": d},
               "gofo-network": {"n": "GOFO network growth", "last": d},
               "old-uniuni": {"n": "UniUni something", "last": "2020-01-01"}}
    assert N.saga_candidates(threads, "UniUni") == ["uniuni"]
    assert N.saga_candidates(threads, "Uni") == []
    assert N.saga_candidates(threads, None) == []


def test_story_tags_only_companies_it_is_about():
    import news as N
    # a story about Amazon that mentions its rivals is an Amazon story only
    assert N.subject_tags({"title": "Amazon close to launching Shipping With Amazon, WSJ report says",
                           "c": ["Amazon", "UPS", "FedEx", "USPS"]}) == ["Amazon"]
    # a carrier stays when the headline names it, its parent or one of its arms
    assert N.subject_tags({"title": "Amazon passes USPS as largest U.S. parcel carrier by volume", "c": ["Amazon", "USPS", "UPS"]}) == ["Amazon", "USPS"]
    assert N.subject_tags({"title": "Omaha Steaks offers Roadie same-day delivery from all 44 stores", "c": ["UPS"]}) == ["UPS"]
    # no company in the headline: the tags stand (an industry report, a USPS leadership story)
    assert N.subject_tags({"title": "Report: Postmaster General has told associates he wants to resign", "c": ["USPS"]}) == ["USPS"]
    # nothing left: an industry story
    assert N.subject_tags({"title": "Sereact robots sort Zalando returns at two CEVA sites in Europe", "c": ["UPS", "Amazon"]}) == ["Industry"]
    # smaller companies' own tags are never dropped
    assert N.subject_tags({"title": "SPAC sends UniUni breach notice", "c": ["UniUni", "MAK Acquisition"]}) == ["UniUni", "MAK Acquisition"]


def test_live_stories_have_no_borrowed_big_carrier_tags():
    """data/news.json: no live story carries a big-carrier tag for a carrier it only mentions."""
    import news as N
    bad = [(s["id"], s["c"], s["title"]) for s in common.load("news.json", []) if N.subject_tags(s) != list(s.get("c") or [])]
    assert not bad, bad
