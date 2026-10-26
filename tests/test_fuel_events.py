"""Oct 26, 2026: the fuel chart's world events stay honest and current (pipeline/fuel.py fuel_events)."""
import json, re
import fuel as FU
from conftest import ROOT

HTML = (ROOT / "index.html").read_text()
DIESEL = json.loads(re.search(r"const DIESELDB=(\[.*?\]);", HTML).group(1))
EVENTS = json.loads((ROOT / "data" / "fuel_events.json").read_text())["events"]


def test_every_event_sits_on_a_real_diesel_move():
    review = []
    events, notes = FU.fuel_events({"diesel": DIESEL}, [], [dict(e) for e in EVENTS], review, today="2026-10-05")
    assert not [n for n in notes if n.startswith("flat")], notes
    assert all(e.get("url") and e.get("src") for e in events)


def test_an_event_on_flat_prices_goes_to_review():
    review = []
    fake = {"d": "2019-06-03", "title": "Something that didn't move diesel", "why": "x", "url": "https://example.com", "src": "X", "dir": "up"}
    FU.fuel_events({"diesel": DIESEL}, [], [fake], review, today="2019-07-01")
    assert any(r["type"] == "fuel-event" and r["key"].startswith("fuel-event-flat") for r in review)


def test_a_new_big_move_takes_a_sourced_story_or_asks():
    d = [list(x) for x in DIESEL if x[0] <= "2026-10-05"] + [["2026-10-12", 6.199 + 0.45]]
    story = {"id": "zz1", "date": "2026-10-08", "title": "Refinery outage lifts diesel futures", "sum": "A Gulf Coast refinery outage lifted diesel. More.",
             "src": "Reuters", "url": "https://example.com/r", "lvl": 2}
    off = {"id": "zz2", "date": "2026-10-09", "title": "UPS adds drones in Texas", "url": "https://example.com/u"}
    review = []
    events, notes = FU.fuel_events({"diesel": d}, [off, story], [dict(e) for e in EVENTS], review, today="2026-10-13")
    new = [e for e in events if e.get("story") == "zz1"]
    assert new and new[0]["auto"] and new[0]["url"] == story["url"] and new[0]["why"] == "A Gulf Coast refinery outage lifted diesel."
    assert any(r["key"] == "fuel-event-auto|zz1" for r in review)
    review = []                                        # no oil story that week: nothing is invented, a person is asked
    events, notes = FU.fuel_events({"diesel": d}, [off], [dict(e) for e in EVENTS], review, today="2026-10-13")
    assert not any(e.get("auto") for e in events) and any(r["key"].startswith("fuel-event-missing|2026-10-12") for r in review)


def test_history_is_not_reflagged():
    review = []
    FU.fuel_events({"diesel": DIESEL}, [], [dict(e) for e in EVENTS], review, today="2026-10-26")
    assert not any(r["key"].startswith("fuel-event-missing") for r in review), review
