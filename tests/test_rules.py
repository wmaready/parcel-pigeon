"""The accuracy rules behind the market map and the year-over-year history."""
import json
import sweep as W
import news as N
import themes as T
import common


def test_fact_needs_primary_or_two_real_sources():
    ok = W.fact_ok
    assert ok({"v": "Chantilly, VA, USA", "src": ["https://www.ontrac.com/about"], "primary": True})
    assert not ok({"v": "X", "src": ["https://pitchbook.com/x"], "primary": True})                     # a directory never counts alone
    assert not ok({"v": "X", "src": ["https://en.wikipedia.org/a", "https://pitchbook.com/b"]})
    assert ok({"v": "X", "src": ["https://en.wikipedia.org/a", "https://www.freightwaves.com/b"]})
    assert not ok({"v": "X", "src": ["https://a.com/1", "https://b.com/2"], "disputed": True})
    assert not ok({"v": None, "src": ["https://a.com/1"], "primary": True})


def test_only_market_movers():
    for n in ("Smith & Co CPAs", "Kirkland & Ellis LLP", "Accenture Consulting", "Baker Tilly Advisors"):
        assert N.NOT_MOVER.search(n), n
    for n in ("OnTrac", "Veho", "Better Trucks", "Apollo Global Management", "Roadie"):
        assert not N.NOT_MOVER.search(n), n


def test_almanac_skips_figures_not_in_story(data_dir, monkeypatch):
    story = {"id": "s1", "date": "2026-09-18", "title": "FedEx sets 5.9% average increase for 2027", "sum": "Effective Jan. 4, 2027.",
             "plain": "", "c": ["FedEx"], "cat": "Pricing & GRI", "lvl": 3, "kind": "News", "srcs": [{"src": "FedEx", "url": "https://fedex.com/x"}]}
    common.save("news.json", [story])
    reply = [{"carrier": "FedEx", "year": 2027, "kind": "gri", "effective": "2027-01-04", "pct": 5.9, "headline": "FedEx 2027 GRI", "details": ["5.9% average"]},
             {"carrier": "FedEx", "year": 2027, "kind": "surcharge", "effective": "2027-01-04", "pct": 7.4, "headline": "made up", "details": ["7.4%"]}]
    monkeypatch.setattr(T, "claude", lambda *a, **k: json.dumps(reply))
    alm = []
    assert T.grow(alm, {}) == 1
    assert alm[0]["pct"] == 5.9 and alm[0]["story"] == "s1"
