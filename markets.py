"""Share prices for the Today page: UPS and FedEx up top, plus the stock watch (Amazon, DHL Group, FedEx Freight, DoorDash, Uber, Pitney Bowes). Free, no key: Yahoo Finance chart endpoint,
with Stooq as a fallback for the last price. Writes data/markets.json; keeps the old file if both fail."""
import datetime as dt, sys
from common import load, save, get

# app symbol: (Yahoo symbol, Stooq symbol, name)
SYMS = {"UPS": ("UPS", "ups.us", "United Parcel Service"), "FDX": ("FDX", "fdx.us", "FedEx"),
        "AMZN": ("AMZN", "amzn.us", "Amazon"), "DHL": ("DHL.DE", "dhl.de", "DHL Group"), "FDXF": ("FDXF", "fdxf.us", "FedEx Freight"),
        "DASH": ("DASH", "dash.us", "DoorDash"), "UBER": ("UBER", "uber.us", "Uber"), "PBI": ("PBI", "pbi.us", "Pitney Bowes")}


def yahoo(sym):
    j = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d",
).json()["chart"]["result"][0]
    m = j["meta"]
    closes = [c for c in j["indicators"]["quote"][0]["close"] if c is not None]
    px = float(m["regularMarketPrice"])
    prev = float(m.get("previousClose") or m.get("chartPreviousClose") or closes[-2])
    t = dt.datetime.fromtimestamp(m.get("regularMarketTime", 0), dt.timezone.utc)
    return {"px": round(px, 2), "ch": round(px - prev, 2), "chp": round((px / prev - 1) * 100, 2),
            "lo": round(min(closes + [px]), 2), "hi": round(max(closes + [px]), 2),
            "asof": t.strftime("%b %d, %Y %H:%M UTC")}


def stooq(sym):
    rows = get(f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlc&h&e=csv").text.strip().splitlines()
    s, d, t, o, h, l, c = rows[1].split(",")
    return {"px": round(float(c), 2), "asof": f"{d} {t}"}


def main():
    out = load("markets.json", {})
    for sym, (ysym, ssym, name) in SYMS.items():
        try:
            q = yahoo(ysym)
        except Exception as e:
            print(f"{sym} yahoo failed: {e}", file=sys.stderr)
            try: q = {**out.get(sym, {}), **stooq(ssym)}
            except Exception as e2:
                print(f"{sym} stooq failed: {e2}", file=sys.stderr); continue
        out[sym] = {**out.get(sym, {}), **q, "n": name}
    save("markets.json", out)
    print("markets:", {k: v.get("px") for k, v in out.items()})


if __name__ == "__main__":
    main()
