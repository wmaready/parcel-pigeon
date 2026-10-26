"""Update fuel surcharges and diesel prices. Free sources first; optional keys add more.

- OnTrac: read straight from ontrac.com (no key needed).
- DHL Express: weekly export/import fuel surcharges read from dhl.com's U.S. surcharges page (no key needed).
- UPS and FedEx: OilPriceAPI parcel fuel endpoints if OILPRICE_API_KEY is set (free tier available).
- Diesel: U.S. EIA weekly on-highway diesel if EIA_API_KEY is set (free key from eia.gov).
- Jet fuel and crude oil: EIA's weekly spot price table (U.S. Gulf Coast jet fuel, WTI, Brent; no key needed).
Writes data/fuel.json; keeps old values when a source fails.
"""
import datetime as dt, os, re, sys
from common import load, save, get

MONTHS = {m: i for i, m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}


def iso(month, day, year):
    return f"{int(year):04d}-{MONTHS[month]:02d}-{int(day):02d}"


def ontrac(fuel):
    html = get("https://www.ontrac.com/surchargesandrates/").text
    text = re.sub(r"<[^>]+>", " ", html)
    rows = re.findall(r"([A-Z][a-z]+) (\d{1,2}), (\d{4}) to [A-Z][a-z]+ \d{1,2}, \d{4}\s*\|?\s*([\d.]+)%", text)
    hist = fuel.setdefault("hist", {}).setdefault("OnTrac", {})
    for m, d, y, pct in rows:
        if m in MONTHS:
            hist[iso(m, d, y)] = float(pct)
    return len(rows)


def dhl_express(fuel):
    """DHL Express posts export and import fuel surcharges by week (Monday to Sunday) on its U.S. surcharges page."""
    html = get("https://www.dhl.com/us-en/home/express/products-and-solutions/products-and-services-overview/surcharges.html").text
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    rows = re.findall(r"([A-Z][a-z]+) (\d{1,2})\s*[-\u2013]\s*(?:[A-Z][a-z]+ )?\d{1,2},? (\d{4})\s*\|?\s*([\d.]+)%\s*\|?\s*([\d.]+)%", text)
    out = fuel.setdefault("dhl", {})
    for m, d, y, exp, imp in rows:
        if m in MONTHS:
            out[iso(m, d, y)] = [float(exp), float(imp)]
    return len(rows)


def oilprice(fuel, carrier, key):
    base = f"https://api.oilpriceapi.com/v1/fuel-surcharge/parcel/{carrier.lower()}"
    hdr = {"Authorization": f"Token {key}"}
    import requests
    r = requests.get(base + "/latest", headers=hdr, timeout=20)
    r.raise_for_status()                      # a 401/403/500 is a failure, not an empty week
    latest = r.json().get("data", {})
    cur = fuel.setdefault("current", {}).setdefault(carrier, {})
    for row in latest.get("service_levels", latest if isinstance(latest, list) else []):
        name = (row.get("service_level") or row.get("name") or "").lower()
        val = row.get("surcharge_percent")
        if val is None: continue
        if "ground" in name and "international" not in name: cur["ground"] = float(val)
        elif ("air" in name or "express" in name) and "international" not in name: cur.setdefault("air", float(val))
    r = requests.get(base + "/history", params={"service_level": "ground"}, headers=hdr, timeout=20)
    r.raise_for_status()
    hist = r.json().get("data", {}).get("history", [])
    if not hist:
        raise RuntimeError("the service returned no weekly history")
    h = fuel.setdefault("hist", {}).setdefault(carrier, {})
    for w in hist:
        h[w["effective_date"][:10]] = float(w["surcharge_percent"])
    return len(hist)


def eia(fuel, key):
    url = ("https://api.eia.gov/v2/petroleum/pri/gnd/data/?frequency=weekly&data[0]=value"
           "&facets[series][]=EMD_EPD2D_PTE_NUS_DPG&sort[0][column]=period&sort[0][direction]=desc&length=12&api_key=" + key)
    rows = get(url).json()["response"]["data"]
    old = {d: v for d, v in fuel.get("diesel", [])}
    old.update({r["period"]: float(r["value"]) for r in rows})
    fuel["diesel"] = sorted([[d, v] for d, v in old.items()])
    return len(rows)


def fred_diesel(fuel):
    """No-key fallback: FRED's copy of the EIA weekly U.S. on-highway diesel series."""
    text = get("https://fred.stlouisfed.org/data/GASDESW.txt").text
    rows = []
    for line in text.splitlines():
        p = line.split()
        if len(p) == 2 and p[0][:4].isdigit() and p[0] >= "2016-12-26":
            try: rows.append([p[0], float(p[1])])
            except ValueError: pass
    if rows:
        old = {d: v for d, v in fuel.get("diesel", [])}
        old.update({d: v for d, v in rows})
        fuel["diesel"] = sorted([[d, v] for d, v in old.items()])
    return len(rows)


# ---------------------------------------------------------------- world events on the fuel chart (data/fuel_events.json)
EV_SWING = 0.25          # an event must sit on a diesel swing of at least this many $/gal within EV_DAYS of its date
EV_DAYS = 28
EV_MOVE = 0.30           # a weekly diesel change this big (or a new all-time high) wants an event
EV_NEAR = 14             # ...unless one is already within this many days
EV_RECENT = 60           # only moves this recent are looked at (history was checked by hand)
OIL_WORDS = re.compile(r"\b(diesel|crude|oil|OPEC|refiner(y|ies)|Hormuz|pipeline|hurricane|sanction|tanker|barrel)\b", re.I)


def _d(s):
    return dt.date.fromisoformat(s)


def ev_swing(series, d, days=EV_DAYS):
    """The largest diesel price difference inside [d - days, d + days]."""
    w = [v for x, v in series if abs((_d(x) - _d(d)).days) <= days]
    return (max(w) - min(w)) if len(w) > 1 else 0.0


def fuel_events(fuel, news, events, review, today=None):
    """Keep the chart's world events honest and current. Returns (events, notes).
    1. Every event must sit on a real move: a diesel swing of EV_SWING within EV_DAYS. One that doesn't goes to review.
    2. A recent big move (weekly change of EV_MOVE or a new all-time high) with no event near it: the robot looks in the
       published news for an oil or fuel story from that week and adds it with that story's source, marked auto, for a
       person to confirm; with no such story, it asks in review. Never writes an event without a source."""
    today = today or dt.date.today().isoformat()
    series = sorted(v for v in (fuel.get("diesel") or []) if v and v[1] is not None)
    notes = []
    if len(series) < 10:
        return events, notes
    have = lambda kind, key: any(isinstance(r, dict) and r.get("key") == key for r in review)
    for e in events:
        if ev_swing(series, e["d"]) < EV_SWING and not e.get("checked_flat"):
            key = f"fuel-event-flat|{e['d']}|{e['title'][:40]}"
            if not have("x", key):
                review.append({"type": "fuel-event", "key": key, "event": e["title"], "d": e["d"],
                               "note": f"No diesel move of ${EV_SWING:.2f} within {EV_DAYS} days of this event. Check it still belongs on the chart."})
                notes.append(f"flat: {e['title']}")
    hi, moves = 0.0, []
    for i, (d, v) in enumerate(series):
        prev = series[i - 1][1] if i else None
        if (prev is not None and abs(v - prev) >= EV_MOVE) or (hi and v > hi):
            moves.append((d, v, (v - prev) if prev is not None else 0.0, hi and v > hi))
        hi = max(hi, v)
    cut = (_d(today) - dt.timedelta(days=EV_RECENT)).isoformat()
    used = {e.get("story") for e in events if e.get("story")}
    for d, v, ch, record in [m for m in moves if m[0] >= cut]:
        if any(abs((_d(e["d"]) - _d(d)).days) <= EV_NEAR for e in events):
            continue
        lo, up = (_d(d) - dt.timedelta(days=10)).isoformat(), (_d(d) + dt.timedelta(days=3)).isoformat()
        cand = [n for n in news if lo <= (n.get("date") or "") <= up and n.get("url") and n.get("id") not in used
                and OIL_WORDS.search(n.get("title") or "") and not n.get("unconfirmed")]
        cand.sort(key=lambda n: (-(int(n.get("lvl") or 1)), n.get("date") or ""))
        if cand:
            n = cand[0]
            why = re.split(r"(?<=[.!?])\s", (n.get("sum") or "").strip())[0]
            events.append({"d": n["date"], "title": n["title"], "why": why, "src": n.get("src") or "Source", "url": n["url"],
                           "dir": "up" if ch >= 0 else "down", "story": n["id"], "auto": True, "added": today})
            used.add(n["id"])
            review.append({"type": "fuel-event", "key": f"fuel-event-auto|{n['id']}", "event": n["title"], "d": n["date"],
                           "note": f"Added to the fuel chart for diesel's {'record ' if record else ''}move the week of {d} "
                                   f"(${v:.2f}, {'+' if ch >= 0 else '−'}${abs(ch):.2f}). Confirm it explains the move."})
            notes.append(f"added: {n['title']}")
        else:
            key = f"fuel-event-missing|{d}"
            if not have("x", key):
                review.append({"type": "fuel-event", "key": key, "d": d,
                               "note": f"Diesel {'set a record' if record else 'moved'} the week of {d} (${v:.2f}, {'+' if ch >= 0 else '−'}${abs(ch):.2f}) "
                                       "and no world event on the chart explains it. Add one with its source to data/fuel_events.json."})
                notes.append(f"missing: {d}")
    events.sort(key=lambda e: e["d"])
    return events, notes


SPOT_ROWS = {"jet": "Kerosene-Type Jet Fuel", "wti": "WTI", "brent": "Brent"}


def eia_spot(fuel):
    """EIA 'Spot Prices for Crude Oil and Petroleum Products', weekly (Friday) values for the last six weeks."""
    html = get("https://www.eia.gov/dnav/pet/pet_pri_spt_s1_w.htm").text
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", html))
    dates = re.findall(r"(\d{2})/(\d{2})/(\d{2})", text.split("WTI")[0])[-6:]
    dates = [f"20{y}-{m}-{d}" for m, d, y in dates]
    spot = fuel.setdefault("spot", {})
    n = 0
    for key, label in SPOT_ROWS.items():
        i = text.find(label)
        if i < 0 or len(dates) != 6:
            continue
        vals = re.findall(r"\|\s*(\d+\.\d+)\s*", text[i:i + 600])[:6]
        if len(vals) != 6:
            continue
        old = {d: v for d, v in spot.get(key, [])}
        old.update({d: float(v) for d, v in zip(dates, vals)})
        spot[key] = sorted([[d, v] for d, v in old.items()])
        n += 1
    return n


def loud(msg):
    """A failure a person must see: a GitHub Actions error annotation (shown on the run page) plus the log line."""
    print(f"::error title=Fuel surcharges::{msg}", file=sys.stderr)


def carriers(fuel):
    """UPS and FedEx weekly fuel. A missing key or a failing service is logged loudly and recorded in fuel.json "health",
    never skipped quietly: without it the app keeps showing the last confirmed week (marked as such)."""
    key = os.environ.get("OILPRICE_API_KEY")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    health = fuel.setdefault("health", {})
    for c in ("UPS", "FedEx"):
        if not key:
            loud(f"OILPRICE_API_KEY is not set, so {c} weekly fuel was NOT updated. Add the secret in GitHub (Settings > Secrets).")
            health[c] = {"ok": False, "why": "OILPRICE_API_KEY not set", "at": now, "last_ok": (health.get(c) or {}).get("last_ok")}
            continue
        try:
            n = oilprice(fuel, c, key)
            print(c, n)
            health[c] = {"ok": True, "at": now, "last_ok": now}
        except Exception as e:
            loud(f"{c} weekly fuel was NOT updated: the fuel-price service failed ({str(e)[:200]}).")
            health[c] = {"ok": False, "why": str(e)[:200], "at": now, "last_ok": (health.get(c) or {}).get("last_ok")}


def main():
    fuel = load("fuel.json", {})
    for name, fn in [("OnTrac", lambda: ontrac(fuel)), ("DHL Express", lambda: dhl_express(fuel)), ("EIA spot (jet, WTI, Brent)", lambda: eia_spot(fuel))]:
        try: print(name, fn())
        except Exception as e: print(f"{name} failed: {e}", file=sys.stderr)
    carriers(fuel)
    if os.environ.get("EIA_API_KEY"):
        try: print("diesel", eia(fuel, os.environ["EIA_API_KEY"]))
        except Exception as e: print(f"diesel failed: {e}", file=sys.stderr)
    try: print("diesel (FRED)", fred_diesel(fuel))
    except Exception as e: print(f"diesel FRED failed: {e}", file=sys.stderr)
    # current ground = latest history week that has started
    today = dt.date.today().isoformat()
    for c, h in fuel.get("hist", {}).items():
        past = sorted(k for k in h if k <= today)
        if past:
            fuel.setdefault("current", {}).setdefault(c, {})["ground"] = h[past[-1]]
            fuel.setdefault("eff", {})[c] = past[-1]
    fuel["updated"] = dt.datetime.utcnow().isoformat(timespec="minutes") + "Z"
    save("fuel.json", fuel)
    try:
        fe, review = load("fuel_events.json", {}), load("review.json", [])
        n0 = len(review)
        events, notes = fuel_events(fuel, load("news.json", []), list(fe.get("events") or []), review)
        if notes:
            fe["events"] = events
            save("fuel_events.json", fe)
            print("fuel events:", "; ".join(notes))
        if len(review) != n0:
            save("review.json", review)
    except Exception as e:
        print(f"::warning title=fuel events::{e}")


if __name__ == "__main__":
    main()
