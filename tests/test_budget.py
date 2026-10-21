"""Spend metering and pacing (common.cost, allowance, paused) and the once-a-day job gate (due.py)."""
import datetime as dt
import common
from common import cost, track, spent, allowance, paused, extras_ok, load, save


def test_cost_at_list_prices():
    assert round(cost("claude-sonnet-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000}), 4) == 3.0
    assert round(cost("claude-haiku-5-5", {"input_tokens": 100_000, "output_tokens": 1_000_000}), 4) == 0.51
    # cache reads at a tenth of input, writes at 1.25x
    assert round(cost("claude-sonnet-5-5", {"input_tokens": 0, "cache_read_input_tokens": 1_000_000,
                                             "cache_creation_input_tokens": 1_000_000, "output_tokens": 0}), 4) == 2.7
    # long Haiku prompts cost more; web searches are a cent each
    assert round(cost("claude-haiku-5-5", {"input_tokens": 200_000, "output_tokens": 1000}), 4) == 0.1025
    assert round(cost("claude-sonnet-5-5", {"input_tokens": 0, "output_tokens": 0, "server_tool_use": {"web_search_requests": 3}}), 4) == 0.03


def test_ledger_and_pacing(data_dir, monkeypatch):
    monkeypatch.setattr(common, "MONTHLY", 75.0)
    save("usage.json", {"carry": {"2026-10": 60}, "days": {"2026-10-20": 1.0, "2026-10-21": 0.5, "2026-09-30": 9.0}})
    save("usage_sweep.json", {"days": {"2026-10-21": 0.25}})
    today, month, before = spent("2026-10-21")
    assert (round(today, 2), round(month, 2), round(before, 2)) == (0.75, 61.75, 61.0)
    # $14 left over 11 days (Oct 21-31, today included)
    assert round(allowance("2026-10-21"), 4) == round(14 / 11, 4)
    # a new month starts fresh: the full limit over 30 days
    assert round(allowance("2026-11-01"), 2) == 2.5


def test_pause_and_extras(data_dir, monkeypatch):
    monkeypatch.setattr(common, "NOW", lambda: dt.datetime(2026, 10, 21, 19, 0, tzinfo=common.ET))   # evening: all built up
    monkeypatch.setattr(common, "MONTHLY", 75.0)
    monkeypatch.setattr(common, "API_KEY", "test-key")
    d = common.NOW().date()
    save("usage.json", {"carry": {d.isoformat()[:7]: 0}, "days": {}})
    a = allowance()
    assert paused() is None and extras_ok()
    track({"model": "claude-sonnet-5-5", "usage": {"input_tokens": 0, "output_tokens": int(a * 0.6 / 10 * 1e6)}})
    assert not extras_ok()                      # past half the day's allowance: extras stop
    assert paused() is None                     # the news keeps going
    common.PACE.clear()
    track({"model": "claude-sonnet-5-5", "usage": {"input_tokens": 0, "output_tokens": int(a * 0.5 / 10 * 1e6)}})
    assert paused() and "built up" in paused()
    try:
        common.claude("claude-haiku-5-5", "s", "u")
    except RuntimeError as e:
        assert "paused" in str(e)
    else:
        raise AssertionError("claude() should refuse once the day's allowance is used")


def test_report_writes_todays_spend(data_dir):
    save("usage.json", {"carry": {}, "days": {}})
    track({"model": "claude-haiku-5-5", "usage": {"input_tokens": 1000, "output_tokens": 1000}})
    common._usage_report()
    assert load("usage.json", {})["days"][common.NOW().date().isoformat()] == round(0.0006, 4)


def test_allowance_builds_up_through_the_eastern_day():
    """Last night one 10 p.m. run used the whole day's allowance and the next morning had no news. Days are Eastern now,
    and a quarter of the day's allowance is there at midnight, all of it by 6 p.m."""
    at = lambda h: dt.datetime(2026, 10, 21, h, 0, tzinfo=common.ET)
    assert common.built_up(1.0, at(0)) == 0.25
    assert round(common.built_up(1.0, at(8)), 3) == round(0.25 + 0.75 * 8 / 18, 3)
    assert common.built_up(1.0, at(18)) == common.built_up(1.0, at(23)) == 1.0


def test_due_once_a_day_from_the_hour(data_dir):
    from due import due, done
    save("due.json", {})
    t = lambda h, day=21: dt.datetime(2026, 10, day, h, 17, tzinfo=dt.timezone.utc)
    assert not due("players", 4, t(3))
    assert due("players", 4, t(5))              # a late start still runs
    assert due("players", 4, t(7))              # and keeps trying until a run finishes it
    done("players", t(7))
    assert not due("players", 4, t(9))          # once a day
    assert due("players", 4, t(4, 22))
    assert due("brief", 12, t(13))              # each job keeps its own day
