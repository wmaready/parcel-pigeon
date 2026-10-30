"""The two lanes that skip the day's pacing, each with a hard cap: breaking news (news.py) and the nightly company
research slot (players.py --slot). Plus: a paused research run no longer stops the phone alerts."""
import datetime as dt, json, re
import pytest
import common
from common import h, save, load


# ---------------------------------------------------------------- breaking lane
def item(n, title, src="UPS", tier=0, date=None):
    date = date or (dt.date.today() - dt.timedelta(days=1)).isoformat()          # always inside the news window
    return {"title": title, "url": f"https://example.com/{n}", "summary": "parcel", "date": date, "src": src,
            "direct": True, "house": False, "tier": tier}


BIG = ["UPS sets 2026 peak demand surcharges for large packages", "FedEx raises 2027 shipping rates by 5.9 percent",
       "USPS proposes January postage increase for Ground Advantage", "Amazon Shipping adds a holiday peak fee for sellers",
       "UPS changes the residential surcharge on Ground Saver"]
ITEMS = [item(i, t, src=t.split()[0]) for i, t in enumerate(BIG)] + \
        [item(10, "UPS completes automation at four sortation sites", tier=2, src="FreightWaves"),
         item(11, "Local bakery ships holiday cookies", tier=3, src="Riverhead Local")]


@pytest.fixture
def lane(data_dir, monkeypatch):
    import news as N
    calls = {"triage": [], "write": 0, "unpaced": []}

    def fake_claude(model, system, user, max_tokens=0):
        calls["unpaced"].append(common.UNPACED["on"])
        if system == N.TRIAGE_SYSTEM:
            lines = [l for l in user.split("NEW ITEMS:\n")[1].splitlines() if l[:1].isdigit()]
            calls["triage"].append(len(lines))
            out = []
            for l in lines:
                i = int(l.split(".")[0])
                price = bool(N.PRICE_RX.search(l))
                out.append({"i": i, "keep": True, "carriers": ["UPS"], "category": "Pricing & GRI" if price else "Network & operations",
                            "kind": "News", "event": f"ev{i}", "same_as": None, "fit": "core", "thread": None, "score": 6})
            return json.dumps(out)
        calls["write"] += 1
        hl = re.search(r"Headline: (.*)", user).group(1)
        car = {"Amazon": "Amazon"}.get(hl.split()[0], hl.split()[0])
        return json.dumps({"title": hl, "sum": f"{car} announced the change.", "plain": "Shippers pay more.", "imp": "up", "lvl": 2,
                           "carriers": [car], "category": "Pricing & GRI", "kind": "News"})

    monkeypatch.setattr(N, "collect", lambda cfg, primary_only=False: [dict(x) for x in ITEMS])
    monkeypatch.setattr(N, "similar", lambda a, b: False)
    monkeypatch.setattr(N, "claude", fake_claude)
    monkeypatch.setattr(N, "article_text", lambda u: ("The carrier set 2026 and 2027 prices, up 5.9 percent. " * 50, u))
    monkeypatch.setattr(N, "find_coverage", lambda t, days=14: [])
    monkeypatch.setattr(N, "find_primary", lambda q, c: None)
    monkeypatch.setattr(N, "find_effective_date", lambda s: None)
    monkeypatch.setattr(N, "lead_image", lambda u: None)
    monkeypatch.setattr(N, "is_covered", lambda t, days=4: ["FreightWaves"])
    monkeypatch.setattr(N, "publish_extras", lambda *a, **k: None)
    monkeypatch.setattr(common, "paused", lambda extra=False: "$1.25 spent today of the $1.22 built up so far")
    monkeypatch.setattr(common, "month_full", lambda: None)          # not the real month's spend: the live ledger can be near the limit
    for f, v in (("news.json", []), ("seen.json", []), ("review.json", []), ("breaking.json", {}),
                 ("threads.json", {"x": {"n": "x", "ids": [], "last": "2000-01-01"}})):
        save(f, v)
    return N, calls


def test_breaking_lane_writes_big_news_while_paused_and_caps_the_day(lane):
    N, calls = lane
    N.main()
    live, seen = load("news.json", []), set(load("seen.json", []))
    assert len(live) == N.BREAKING_PER_DAY == 3, "big news is written even though the day's pacing has paused the news"
    assert {s["title"] for s in live} <= set(BIG)
    assert calls["unpaced"] and all(calls["unpaced"]), "every lane call runs outside the day's pacing"
    assert common.UNPACED["on"] is False, "the lane switches itself off"
    # the T3 local item is never screened by the lane; the trade-press network item is screened but isn't big news
    assert calls["triage"] == [6]
    assert h("https://example.com/11") not in seen and h("https://example.com/10") not in seen, \
        "headlines that aren't breaking stay unseen, so the full screen takes them when the news resumes"
    assert load("breaking.json", {})["n"] == 3

    # a second paused run the same day: the cap is used up, nothing more is screened or written
    N.main()
    assert len(load("news.json", [])) == 3
    assert calls["triage"] == [6] and calls["write"] == 3


def test_breaking_lane_is_off_when_the_news_is_running(lane, monkeypatch):
    N, calls = lane
    monkeypatch.setattr(common, "paused", lambda extra=False: None)
    N.main()
    assert len(load("news.json", [])) == 7, "with the news running, every kept item is written as usual"
    assert not any(calls["unpaced"])
    assert load("breaking.json", {}) == {}


def test_breaking_lane_stops_near_the_monthly_limit(lane, monkeypatch):
    N, calls = lane
    monkeypatch.setattr(common, "month_full", lambda: "$73.60 of $75 spent this month")
    N.main()
    assert load("news.json", []) == [] and calls["triage"] == []


def test_what_counts_as_breaking():
    import news as N
    ups = {"title": "UPS sets peak demand surcharges for 2026", "tier": 2}
    v = lambda **k: {"keep": True, "fit": "core", "carriers": ["UPS"], "category": "Network & operations", "score": 5, **k}
    assert N.breaking_worthy(v(), ups)                                            # a major carrier's surcharge, by headline
    assert N.breaking_worthy(v(category="Pricing & GRI"), {"title": "FedEx sets 2027 GRI", "tier": 1})
    assert N.breaking_worthy(v(score=9, carriers=["Industry"]), {"title": "Senate passes de minimis bill", "tier": 1})
    assert not N.breaking_worthy(v(), {"title": "UPS opens a hub in Clark", "tier": 2})
    assert not N.breaking_worthy(v(carriers=["OnTrac"]), {"title": "OnTrac adds a peak surcharge", "tier": 2})
    assert not N.breaking_worthy(v(fit="edge", score=9), ups)
    assert not N.breaking_worthy(v(keep=False), ups)


def test_claude_skips_the_day_pacing_only_inside_the_lane(monkeypatch):
    import requests
    monkeypatch.setattr(common, "API_KEY", "k")
    monkeypatch.setattr(common, "PACE", {"why": "paused for the day"})
    monkeypatch.setattr(common, "month_full", lambda: None)

    class R:
        status_code = 200
        def json(self):
            return {"model": "claude-haiku-5-5", "usage": {"input_tokens": 10, "output_tokens": 10}, "content": [{"type": "text", "text": "ok"}]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="paused"):
        common.claude("claude-haiku-5-5", "s", "u")
    with common.unpaced():
        assert common.claude("claude-haiku-5-5", "s", "u") == "ok"
    assert common.UNPACED["on"] is False
    monkeypatch.setattr(common, "month_full", lambda: "$74 of $75 spent this month")
    with common.unpaced(), pytest.raises(RuntimeError, match="this month"):
        common.claude("claude-haiku-5-5", "s", "u")


# ---------------------------------------------------------------- nightly company research slot
def cand(i, name):
    return {"id": f"c{i}", "n": name, "realm": "regional", "s": "parcel carrier", "al": [], "src": f"https://news.example/{i}",
            "auto": True, "added": "2026-10-22"}


@pytest.fixture
def research(data_dir, monkeypatch):
    import players as P
    seen = {"companies": [], "unpaced": []}

    def fake_ask(user, use_search=True, system=None, max_tokens=2500, strict=False, searches=5):
        seen["unpaced"].append(common.UNPACED["on"])
        common.track({"model": "claude-sonnet-5-5", "usage": {"input_tokens": 0, "output_tokens": 10_000}})   # $0.10 a call
        P.ask.searches = 1
        if system == P.VERIFY:
            return json.dumps({"exists": True, "name_ok": True, "parcel_relevant": True, "us_relevant": True, "status": "active",
                               "fields": {"hq": "confirmed"}, "links": [], "evidence": ["https://a.example"]})
        name = re.search(r"Company: (.*)", user).group(1)
        seen["companies"].append(name)
        return json.dumps({"is_player": True, "mover": True, "n": name, "status": "active", "serves_us": True, "realm": "regional",
                           "hq": "Dallas, TX, USA", "lat": 32.8, "lon": -96.8, "s": "Regional parcel carrier.",
                           "sources": [{"url": "https://a.example/x"}, {"url": "https://b.example/y"}], "links": []})

    monkeypatch.setattr(P, "ask", fake_ask)
    monkeypatch.setattr(P, "API_KEY", "k")
    save("players.json", {"players": [cand(i, n) for i, n in enumerate(["Alpha Parcel", "Bravo Courier", "Charlie Express",
                                                                          "Delta Delivery", "Olo"])], "edges": []})
    save("sweep_review.json", [{"d": "2026-10-20", "kind": "new player", "n": "Olo", "why": "not parcel", "urls": []}])
    return P, seen


def test_nightly_slot_researches_three_even_when_extras_are_paused(research, monkeypatch):
    P, seen = research
    monkeypatch.setattr(common, "paused", lambda extra=False: "extras pause at half of today's allowance")
    monkeypatch.setattr(common, "month_full", lambda: None)
    monkeypatch.setattr(P, "SLOT_USD", 10.0)
    assert P.main(slot=True) is True
    assert seen["companies"] == ["Alpha Parcel", "Bravo Courier", "Charlie Express"], "up to 3 candidates, queue order"
    assert all(seen["unpaced"]) and common.UNPACED["on"] is False
    players = {p["n"]: p for p in load("players.json", {})["players"]}
    assert all(players[n].get("enriched") for n in ("Alpha Parcel", "Bravo Courier", "Charlie Express"))
    assert "Olo" not in players, "a candidate research already turned down is not paid for again"


def test_nightly_slot_stops_at_its_dollar_cap(research, monkeypatch):
    P, seen = research
    monkeypatch.setattr(common, "month_full", lambda: None)
    monkeypatch.setattr(P, "SLOT_USD", 0.35)            # research + check is $0.20 a company here
    P.main(slot=True)
    assert seen["companies"] == ["Alpha Parcel", "Bravo Courier"]


def test_nightly_slot_tops_up_from_discovery_when_the_queue_is_short(research, monkeypatch):
    P, seen = research
    import sweep
    monkeypatch.setattr(common, "month_full", lambda: None)
    save("players.json", {"players": [cand(0, "Alpha Parcel")], "edges": []})
    # start from an empty discovery queue: the live sweep_state.json copied from data/ holds real names waiting
    # (e.g. Lalamove, Spoke), and the slot rightly takes those before searching again
    save("sweep_state.json", {"queue": []})

    def fake_discover(st, mp, seed, segs):
        st.setdefault("queue", []).extend({"n": n, "what": "courier", "url": "https://d.example", "realm": "regional"} for n in ("Echo Freight", "Foxtrot Lockers", "Golf Returns"))
        return 3
    monkeypatch.setattr(sweep, "discover", fake_discover)
    monkeypatch.setattr(P, "SLOT_USD", 10.0)
    P.main(slot=True)
    assert seen["companies"] == ["Alpha Parcel", "Echo Freight", "Foxtrot Lockers"]
    assert [x["n"] for x in load("sweep_state.json", {})["queue"]] == ["Golf Returns"], "the rest wait for the next night"


def test_paused_research_returns_instead_of_exiting(research, monkeypatch):
    """players.main() used to sys.exit(1) when paused. alerts.py calls it first, and SystemExit isn't an Exception, so on
    Oct 22 every run after 3 p.m. logged "alerts.py failed" and no phone alert went out."""
    P, seen = research
    monkeypatch.setattr(common, "paused", lambda extra=False: "extras pause at half of today's allowance" if extra else None)
    assert P.main() is False
    assert seen["companies"] == []
