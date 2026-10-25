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


if __name__ == "__main__":
    main()
