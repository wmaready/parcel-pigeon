"""Share prices for the Today page: UPS and FedEx up top, plus the stock watch (Amazon, DHL Group, FedEx Freight, DoorDash, Uber, Pitney Bowes). Free, no key: Yahoo Finance chart endpoint,
with Stooq as a fallback for the last price. Writes data/markets.json; keeps the old file if both fail.

The day's change is measured against the previous completed session's close (closes[-2], stored with its date as
prev_date), never against Yahoo's chartPreviousClose: for a one-year range request that is the close before the
one-year window, which turned a year's move into "today's" change. A daily move over 15% is held back: the last good
values stay and the move waits in data/review.json for a person. The low and high are the 52-week closing range."""
import datetime as dt, sys
from common import load, save, get

# app symbol: (Yahoo symbol, Stooq symbol, name)
# DHL is DHL Group's primary listing, Xetra in Frankfurt (DHL.DE), quoted in euros.
SYMS = {"UPS": ("UPS", "ups.us", "United Parcel Service"), "FDX": ("FDX", "fdx.us", "FedEx"),
        "AMZN": ("AMZN", "amzn.us", "Amazon"), "DHL": ("DHL.DE", "dhl.de", "DHL Group"), "FDXF": ("FDXF", "fdxf.us", "FedEx Freight"),
        "DASH": ("DASH", "dash.us", "DoorDash"), "UBER": ("UBER", "uber.us", "Uber"), "PBI": ("PBI", "pbi.us", "Pitney Bowes")}
MAX_DAY_MOVE = 15.0      # percent; a bigger one-day move is held for review instead of shown


def from_chart(j):
    """One quote from a Yahoo v8 chart result (range=1y, interval=1d)."""
    m = j["meta"]
    off = int(m.get("gmtoffset") or 0)
    day = lambda t: (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(seconds=off)).date()
    rows = [(day(t), float(c)) for t, c in zip(j.get("timestamp") or [], j["indicators"]["quote"][0]["close"]) if c is not None]
    if len(rows) < 2:
        raise ValueError("fewer than two closes")
    px = float(m["regularMarketPrice"])
    t = dt.datetime.fromtimestamp(m.get("regularMarketTime", 0), dt.timezone.utc)
    # the previous completed session: the last close before the session the price belongs to (normally closes[-2])
    today = day(m.get("regularMarketTime", 0))
    before = [r for r in rows if r[0] < today]
    prev_d, prev = before[-1] if before else rows[-2]
    closes = [c for _, c in rows]
    if rows[-1][0] < today:          # the price's own session isn't a bar yet: it still counts toward the range
        closes = closes + [px]
    else:
        closes[-1] = px
    return {"px": round(px, 2), "ch": round(px - prev, 2), "chp": round((px / prev - 1) * 100, 2),
            "prev": round(prev, 2), "prev_date": prev_d.isoformat(),
            "lo": round(min(closes), 2), "hi": round(max(closes), 2), "range": "52-week closing range",
            "cur": m.get("currency") or None, "exch": m.get("fullExchangeName") or m.get("exchangeName") or None,
            "asof": t.strftime("%b %d, %Y %H:%M UTC")}


def yahoo(sym):
    return from_chart(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d").json()["chart"]["result"][0])


def stooq(sym):
    rows = get(f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlc&h&e=csv").text.strip().splitlines()
    s, d, t, o, h, l, c = rows[1].split(",")
    return {"px": round(float(c), 2), "asof": f"{d} {t}"}


def hold(sym, q, review):
    """A daily move too big to trust is held back: True means keep the last good values. It shows once a person has
    checked it and set "approved": true on its data/review.json entry. Returns (hold it?, review changed?)."""
    key = f"{sym}|{q['prev_date']}"
    entry = next((r for r in review if isinstance(r, dict) and r.get("type") == "market-move" and r.get("key") == key), None)
    if entry and entry.get("approved"):
        return False, False
    print(f"{sym}: {q['chp']:+.2f}% since the {q['prev_date']} close is over {MAX_DAY_MOVE:.0f}%; keeping the last good values", file=sys.stderr)
    if entry:
        return True, False
    review.append({"type": "market-move", "key": key, "sym": sym, "px": q["px"], "prev": q["prev"], "prev_date": q["prev_date"],
                   "chp": q["chp"], "asof": q["asof"],
                   "note": f"One-day move over {MAX_DAY_MOVE:.0f}% held back from the Stock watch. Check the quote; if it is right, add \"approved\": true here and it shows on the next run."})
    return True, True


def main():
    out = load("markets.json", {})
    review = load("review.json", [])
    flagged = False
    for sym, (ysym, ssym, name) in SYMS.items():
        try:
            q = yahoo(ysym)
        except Exception as e:
            print(f"{sym} yahoo failed: {e}", file=sys.stderr)
            try:
                # Stooq has the last price only: the change and its date are unknown, so they are cleared, not kept from an older run
                q = {**out.get(sym, {}), **stooq(ssym), "ch": None, "chp": None, "prev": None, "prev_date": None}
            except Exception as e2:
                print(f"{sym} stooq failed: {e2}", file=sys.stderr); continue
        if q.get("chp") is not None and abs(q["chp"]) > MAX_DAY_MOVE:
            keep, changed = hold(sym, q, review)
            flagged |= changed
            if keep:
                continue                  # the last good values stay (or none are shown) until a person approves the move
        out[sym] = {**out.get(sym, {}), **q, "n": name}
    save("markets.json", out)
    if flagged:
        save("review.json", review)
    print("markets:", {k: v.get("px") for k, v in out.items()})


if __name__ == "__main__":
    main()
