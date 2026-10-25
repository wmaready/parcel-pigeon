"""Stock watch prices (B15): the day's change is measured from the previous session's close, never from the close a
year ago; a move over 15% is held for a person; the range is the 52-week closing range. Saved fixtures, no network."""
import datetime as dt
import pytest
import markets
from common import load


def chart(closes, px, cur="USD", exch="NYSE", last_is_today=True, off=-14400):
    """A Yahoo v8 chart result: one bar per weekday ending Oct 23, 2026 (or Oct 22 when today's bar isn't in yet)."""
    days, d = [], dt.date(2026, 10, 23 if last_is_today else 22)
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    days.reverse()
    ts = [int(dt.datetime(x.year, x.month, x.day, 13, 30, tzinfo=dt.timezone.utc).timestamp()) for x in days]
    now = int(dt.datetime(2026, 10, 23, 20, 0, tzinfo=dt.timezone.utc).timestamp())
    return {"meta": {"regularMarketPrice": px, "regularMarketTime": now, "currency": cur, "fullExchangeName": exch, "gmtoffset": off,
                     "chartPreviousClose": closes[0], "previousClose": None},
            "timestamp": ts, "indicators": {"quote": [{"close": closes}]}}


def test_change_uses_yesterdays_close_not_a_year_ago():
    closes = [190.0] + [250.0] * 248 + [290.0, 295.0]          # a year ago 190, yesterday 290, today 295
    q = markets.from_chart(chart(closes, 295.0))
    assert q["prev"] == 290.0 and q["prev_date"] == "2026-10-22"
    assert q["ch"] == 5.0 and q["chp"] == 1.72
    assert q["lo"] == 190.0 and q["hi"] == 295.0 and q["range"] == "52-week closing range"
    assert q["asof"] == "Oct 23, 2026 20:00 UTC" and q["cur"] == "USD"


def test_today_not_yet_a_bar_still_uses_the_last_completed_session():
    closes = [190.0] + [250.0] * 248 + [290.0]                  # the last bar is yesterday's
    q = markets.from_chart(chart(closes, 291.0, last_is_today=False))
    assert q["prev_date"] == "2026-10-22" and q["prev"] == 290.0 and q["chp"] == 0.34
    assert q["hi"] == 291.0


def test_dhl_is_the_xetra_listing_in_euros():
    assert markets.SYMS["DHL"][0] == "DHL.DE"
    q = markets.from_chart(chart([40.0, 57.0, 57.28], 57.28, cur="EUR", exch="XETRA", off=7200))
    assert q["cur"] == "EUR" and q["exch"] == "XETRA"


def run(monkeypatch, quotes):
    monkeypatch.setattr(markets, "yahoo", lambda s: quotes[s] if not isinstance(quotes[s], Exception) else (_ for _ in ()).throw(quotes[s]))
    monkeypatch.setattr(markets, "stooq", lambda s: {"px": 99.0, "asof": "2026-10-23 22:00"})
    monkeypatch.setattr(markets, "SYMS", {"UPS": ("UPS", "ups.us", "United Parcel Service"), "FDX": ("FDX", "fdx.us", "FedEx")})
    markets.main()
    return load("markets.json", {}), load("review.json", [])


def test_a_move_over_15_percent_keeps_the_last_good_values(data_dir, monkeypatch):
    big = markets.from_chart(chart([100.0, 100.0, 120.0], 120.0))          # +20% in a day
    ok = markets.from_chart(chart([100.0, 100.0, 101.0], 101.0))
    before = load("markets.json", {})["UPS"]
    mk, rv = run(monkeypatch, {"UPS": big, "FDX": ok})
    assert mk["UPS"] == before                                             # untouched
    assert mk["FDX"]["chp"] == 1.0 and mk["FDX"]["prev_date"] == "2026-10-22"
    held = [r for r in rv if r.get("type") == "market-move"]
    assert len(held) == 1 and held[0]["sym"] == "UPS" and held[0]["chp"] == 20.0
    mk, rv = run(monkeypatch, {"UPS": big, "FDX": ok})                     # the next run doesn't log it twice
    assert len([r for r in rv if r.get("type") == "market-move"]) == 1 and mk["UPS"] == before
    rv[[i for i, r in enumerate(rv) if r.get("type") == "market-move"][0]]["approved"] = True   # a person checked it
    (data_dir / "review.json").write_text(__import__("json").dumps(rv))
    mk, _ = run(monkeypatch, {"UPS": big, "FDX": ok})
    assert mk["UPS"]["px"] == 120.0 and mk["UPS"]["chp"] == 20.0


def test_stooq_fallback_never_keeps_an_old_change(data_dir, monkeypatch):
    ok = markets.from_chart(chart([100.0, 100.0, 101.0], 101.0))
    mk, _ = run(monkeypatch, {"UPS": RuntimeError("blocked"), "FDX": ok})
    assert mk["UPS"]["px"] == 99.0 and mk["UPS"]["ch"] is None and mk["UPS"]["chp"] is None and mk["UPS"]["prev_date"] is None


def test_range_request_never_reads_chart_previous_close():
    src = open(markets.__file__).read()
    assert "chartPreviousClose" not in src.split('"""', 2)[2]
