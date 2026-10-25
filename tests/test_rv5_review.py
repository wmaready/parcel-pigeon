"""Defects found by the bug review of the review-v5 merge."""
import json
from pathlib import Path


def test_page_meta_keeps_apostrophes_and_skips_banners():
    import news as N
    html = ('<meta property="og:title" content="UPS\'s new surcharge hits Ground Saver shippers">'
            '<meta name="description" content="The carrier\'s fee applies from Dec. 21.">'
            '<p>Subscribe to our newsletter for the latest freight and parcel headlines every morning.</p>'
            '<p>UPS said Tuesday it will add a new surcharge to Ground Saver shipments starting Dec. 21, 2026.</p>')
    m = N.page_meta(html)
    assert m["title"] == "UPS's new surcharge hits Ground Saver shippers"
    assert m["desc"] == "The carrier's fee applies from Dec. 21."
    assert m["first"].startswith("UPS said Tuesday")


def test_a_rate_increase_that_keeps_the_promise_is_not_a_removed_benefit():
    from common import benefit_removed, load
    progs = (load("programs.json", {}) or {}).get("programs") or load("programs.json", [])
    progs = progs if isinstance(progs, list) else []
    assert progs, "data/programs.json should hold the SBR record"
    keeps = "UPS Small Business Rates, which include the fuel surcharge at no extra cost, will rise 4.5% on Dec. 21."
    assert benefit_removed(progs, text=keeps) is None
    adds = "From Dec. 21, 2026 a 5% fuel surcharge applies to all UPS Small Business Rates shipments."
    assert benefit_removed(progs, text=adds) is not None


def test_no_published_story_carries_robot_notes():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
    from changeaudit import robot_leaks
    news = json.loads((Path(__file__).resolve().parent.parent / "data" / "news.json").read_text())
    assert not [s["id"] for s in news if robot_leaks(s)]
