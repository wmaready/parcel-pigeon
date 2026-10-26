"""UPS and FedEx weekly fuel surcharges, read from the carriers' own pages (no API key), including international.

FedEx: the "Weekly fuel surcharge changes" page (this week and next) and its historical page (12 weeks). One row a week:
Ground / Home Delivery / International Ground, domestic package air, and the single international Export & Import
table (one table since June 22, 2026).
UPS: the 90-day history table on its fuel surcharge page, which the page fills in by script, so it is read from a
rendered copy (watch.yml has the browser). Columns: domestic ground, domestic air, international air export, international
air import, international ground.

Nothing is stored unless every week passes its checks: a Monday start, a week-long span, percentages in 0.25 steps in a
plausible range, and no gaps in the weeks read. A page that can't be read is a loud health note, never a quiet skip, and the
weeks already on file stay as they are."""
import datetime as dt, re, sys
from common import load, save
import filings

MONTH = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
FEDEX_URLS = ["https://www.fedex.com/en-us/shipping/fuel-surcharge.html", "https://www.fedex.com/en-us/shipping/historical-fuel-surcharge.html"]
UPS_URL = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges.page"
UPS_COLS = ["Domestic Ground Surcharge", "Domestic Air Surcharge", "International Air Export Surcharge", "International Air Import Surcharge",
            "International Ground Export Import Surcharge"]
DATE = r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})"


def parse_date(s):
    """'Oct. 26, 2026', 'Sept. 28, 2026', 'October 26, 2026', '10/26/2026' or '2026-10-26' -> '2026-10-26', else None."""
    s = s.strip()
    m = re.fullmatch(DATE, s)
    if m and m.group(1)[:3].lower() in MONTH:
        return f"{m.group(3)}-{MONTH[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    return s if m else None


def week_ok(start, vals, lo=5.0, hi=80.0):
    """A Monday start and 0.25-step percentages in a plausible range."""
    try:
        if dt.date.fromisoformat(start).weekday() != 0:
            return False
    except ValueError:
        return False
    return all(lo <= v <= hi and abs(v * 4 - round(v * 4)) < 1e-9 for v in vals)


def contiguous(starts):
    s = sorted(set(starts))
    return all((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days == 7 for a, b in zip(s, s[1:]))


def fedex_weeks(*texts):
    """Rows like 'Oct. 26, 2026–Nov. 1, 2026 | 29.00% | Oct. 19, 2026 | 32.50% | $0.716 per lb. | 45.00% | Oct. 16, 2026'
    (this week and next) and 'Oct. 12, 2026–Oct. 18, 2026 | 28.75% | 32.25% | $0.712 per lb. | 44.50%' (history). Returns
    {start: {ground, air, intl}}. Raises when a row doesn't check out or the weeks aren't consecutive."""
    out = {}
    for text in texts:
        for line in text.splitlines():
            m = re.match(rf"\s*{DATE}\s*[–—-]\s*{DATE}\s*\|(.*)$", line)
            if not m:
                continue
            start = parse_date(f"{m.group(1)} {m.group(2)}, {m.group(3)}")
            end = parse_date(f"{m.group(4)} {m.group(5)}, {m.group(6)}")
            pcts = [float(x) for x in re.findall(r"(\d{1,2}\.\d{2})%", m.group(7))]
            if not start or not end or len(pcts) != 3 or not week_ok(start, pcts) or (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days != 6:
                raise ValueError(f"a FedEx fuel row didn't check out: {line[:160]}")
            row = {"ground": pcts[0], "air": pcts[1], "intl": pcts[2]}
            if out.get(start, row) != row:
                raise ValueError(f"FedEx shows two different rows for the week of {start}")
            out[start] = row
    if len(out) < 4 or not contiguous(out):
        raise ValueError(f"FedEx weeks read: {sorted(out)} (too few, or a gap)")
    return out


def ups_weeks(text):
    """UPS's 90-day history, rendered: one row per Monday with the five surcharges in the page's column order. Refuses a
    page whose column headings aren't the five expected, in order."""
    i = [text.find(h) for h in UPS_COLS]
    if min(i) < 0 or i != sorted(i):
        raise ValueError("UPS history table: the column headings aren't the expected five, in order")
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"\s*\|\s*|\t", line) if c.strip()]
        if not cells:
            continue
        start = parse_date(cells[0])
        pcts = [float(x) for c in cells[1:] for x in re.findall(r"^(\d{1,2}(?:\.\d{1,2})?)\s*%$", c)]
        if not start or len(pcts) != 5:
            continue
        if not week_ok(start, pcts):
            raise ValueError(f"a UPS fuel row didn't check out: {line[:160]}")
        out[start] = dict(zip(("ground", "air", "intlExport", "intlImport", "intlGround"), pcts))
    if len(out) < 8 or not contiguous(out):
        raise ValueError(f"UPS weeks read: {len(out)} (too few, or a gap)")
    return out


def merge(fuel, carrier, weeks, keymap, today, via="page"):
    """Put the weeks into fuel.json: hist2[carrier][service][week], hist (ground), and the current week's values."""
    h2 = fuel.setdefault("hist2", {}).setdefault(carrier, {})
    for start, row in weeks.items():
        for svc, key in keymap.items():
            h2.setdefault(svc, {})[start] = row[key]
        fuel.setdefault("hist", {}).setdefault(carrier, {})[start] = row[keymap["ground"]]
    past = sorted(s for s in weeks if s <= today)
    if past:
        cur = fuel.setdefault("current", {}).setdefault(carrier, {})
        for svc, key in keymap.items():
            cur[svc] = weeks[past[-1]][key]
        fuel.setdefault("eff", {})[carrier] = past[-1]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    fuel.setdefault("health", {})[carrier] = {"ok": True, "via": via, "at": now, "last_ok": now, "latest": max(weeks)}


FEDEX_MAP = {"ground": "ground", "air": "air", "intlExport": "intl", "intlImport": "intl", "intlGround": "ground"}
UPS_MAP = {s: s for s in ("ground", "air", "intlExport", "intlImport", "intlGround")}


def fail(fuel, carrier, why):
    prev = (fuel.setdefault("health", {}).get(carrier) or {})
    fuel["health"][carrier] = {"ok": False, "via": "page", "why": str(why)[:300], "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                               "last_ok": prev.get("last_ok"), "latest": prev.get("latest")}
    print(f"::warning title={carrier} fuel page::{str(why)[:200]}")


def main(fetch_text=None, render_text=None):
    """fetch_text(url) -> page text; render_text(url) -> rendered page text (tests pass fakes)."""
    fuel, today = load("fuel.json", {}), dt.date.today().isoformat()
    if fetch_text is None or render_text is None:
        import fetch
        def fetch_text(u):                                                       # the project's carrier-page reader (pipeline/fetch.py)
            return filings.to_text(fetch.fetch(u).text)
        def render_text(u):
            html = fetch.render(u)
            if not html:
                raise RuntimeError("no browser available to render the page")
            return filings.to_text(html)
    try:
        merge(fuel, "FedEx", fedex_weeks(*[fetch_text(u) for u in FEDEX_URLS]), FEDEX_MAP, today)
        print("FedEx fuel page: ok")
    except Exception as e:
        fail(fuel, "FedEx", e)
    try:
        merge(fuel, "UPS", ups_weeks(render_text(UPS_URL)), UPS_MAP, today)
        print("UPS fuel page: ok")
    except Exception as e:
        fail(fuel, "UPS", e)
    save("fuel.json", fuel)


if __name__ == "__main__":
    main()
