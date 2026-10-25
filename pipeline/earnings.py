"""Earnings history for Docs › UPS / FedEx › Earnings reports (data/earnings.json). Runs after markets.py.

1. New quarters (B32). For each date in data/earnings_next.json that has passed, find the company's release on its
   investor-relations page, read revenue and adjusted EPS, and add the quarter with "checked": false. It is added only
   when a second, separate read of the release gives the same headline and figures; otherwise it waits in
   data/review.json. Package figures come later from the 10-Q (or FedEx's statistical book) and are entered with their
   source; they are never estimated, so a new quarter starts with "vol": null. A quarter is never built from a news story.
2. Year-over-year revenue change: filled from the release's revenue against the same quarter a year earlier
   (rev_m against rev_prior_m) when the row has both and no stated figure; "yoy_src" says where it came from.
3. How the stock moved (B28 part 3), from Yahoo daily closes (period1/period2, never range=1y): the base is the last
   close before the release (before the open: the session before the report day; after the close: the report day's own
   close), and the windows count trading sessions in the price series (1, 5 and 21), never calendar days. The S&P 500
   (^GSPC) is measured over the same sessions. Until 21 sessions have passed the row is "final": false with the windows
   so far; a "final": true row is never recalculated. A failed fetch keeps the last good figures and never writes zeros.
4. Checks: FedEx's four fiscal-2026 quarterly package averages should average within 3% of the 10-K's full-year figure;
   a package block ("vol") must carry its source and check date. Problems go to data/review.json for a person.

Never calculates revenue per package from total revenue and packages: the figure is the company's own or it is null."""
import datetime as dt, html, re, sys, time
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
from common import load, save, get

ET = ZoneInfo("America/New_York")
SYM = {"UPS": "UPS", "FedEx": "FDX", "FedEx Freight": "FDXF"}
SPX = "^GSPC"
# when a row has no release time of its own: UPS reports before the market opens, FedEx after the close
SESSION = {"UPS": "pre", "FedEx": "post"}
WINDOWS = (("d1", 1), ("d5", 5), ("d21", 21))
BEFORE = 5                       # sessions before the base kept in the small chart's series
SPLIT = "2026-06-01"             # FedEx Freight separated from FedEx
# full-year package averages printed in the 10-K, for the quarterly data check (thousands a day)
FY_ADV = {("FedEx", "FY26"): {"adv_k": 17558, "us_adv_k": 14585, "src": "FedEx 10-K for the year ended May 31, 2026, Federal Express segment"}}


def today_et():
    return dt.datetime.now(ET).date()


def review_add(review, entry):
    """One entry per key; returns True when it was new."""
    if any(isinstance(r, dict) and r.get("key") == entry["key"] for r in review):
        return False
    review.append(entry)
    return True


# ------------------------------------------------------------------ stock reaction
def closes(sym, start, end):
    """Daily closes [(YYYY-MM-DD, close)] between two dates, dated in the exchange's own time zone."""
    p1 = int(dt.datetime.combine(start, dt.time(0), dt.timezone.utc).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0), dt.timezone.utc).timestamp())
    j = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d").json()["chart"]["result"][0]
    return series_of(j)


def series_of(j):
    off = int(j["meta"].get("gmtoffset") or 0)
    out = []
    for t, c in zip(j.get("timestamp") or [], j["indicators"]["quote"][0]["close"]):
        if c is None or not c > 0:
            continue
        d = (dt.datetime.fromtimestamp(t, dt.timezone.utc) + dt.timedelta(seconds=off)).date().isoformat()
        if out and out[-1][0] == d:
            out[-1] = (d, float(c))
        else:
            out.append((d, float(c)))
    return out


def session_of(row):
    """'pre' (before the open), 'post' (after the close) or None, from the release time ("06:00 ET", "16:05 ET")."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})", str(row.get("rel_time") or ""))
    if m:
        hm = int(m.group(1)) * 60 + int(m.group(2))
        return "pre" if hm < 9 * 60 + 30 else "post" if hm >= 16 * 60 else None
    return SESSION.get(row.get("company"))


def pct(a, b):
    return round((a / b - 1) * 100, 2)


def reaction(px, spx, report_d, session, checked):
    """The stock and S&P 500 move after a report, or None when the price series can't place the base close."""
    px = [x for x in px if x[0] < checked]               # today's bar may still be trading: it counts from tomorrow
    dates = [d for d, _ in px]
    if session == "pre":                                 # before the open: the close of the session before the report day
        idx = [i for i, d in enumerate(dates) if d < report_d]
    elif session == "post":                              # after the close: the report day's own close
        idx = [i for i, d in enumerate(dates) if d <= report_d]
        if idx and dates[idx[-1]] != report_d:
            return None
    else:
        return None
    if not idx:
        return None
    b = idx[-1]
    sp = dict(spx)
    bd, bc = px[b]
    if bd not in sp:
        return None
    sb = sp[bd]
    rx = {"src": "Yahoo daily close", "checked": checked, "session": session, "base": {"d": bd, "c": round(bc, 2)}}
    for k, n in WINDOWS:
        i = b + n
        if i >= len(px) or px[i][0] not in sp:
            break
        d, c = px[i]
        rx[k] = {"d": d, "pct": pct(c, bc), "spx": pct(sp[d], sb)}
    if "d1" not in rx:
        return None                                      # nothing after the report yet
    rx["series"] = [[d, pct(c, bc), pct(sp[d], sb) if d in sp else None] for d, c in px[max(0, b - BEFORE): b + 22]]
    rx["final"] = "d21" in rx
    return rx


def update_reactions(rows, checked, fetch=closes):
    """Adds or extends rx on every reported quarter that isn't final. Returns the list of failures (kept going)."""
    fails = []
    todo = [r for r in rows if r.get("d") and r["d"] <= checked and not (r.get("rx") or {}).get("final")
            and SYM.get(r.get("company")) and session_of(r)]
    if not todo:
        return fails
    lo = min(dt.date.fromisoformat(r["d"]) for r in todo) - dt.timedelta(days=14)
    hi = min(max(dt.date.fromisoformat(r["d"]) for r in todo) + dt.timedelta(days=45), dt.date.fromisoformat(checked))
    try:
        spx = fetch(SPX, lo, hi)
    except Exception as e:
        return [f"S&P 500 prices: {e}"]
    px = {}
    for r in todo:
        sym = SYM[r["company"]]
        if sym not in px:
            try:
                px[sym] = fetch(sym, lo, hi)
            except Exception as e:
                px[sym] = None
                fails.append(f"{sym} prices: {e}")
        if not px[sym]:
            continue                                     # the last good rx stays
        rx = reaction(px[sym], spx, r["d"], session_of(r), checked)
        if rx is None:
            continue
        old = r.get("rx") or {}
        if old and len([k for k, _ in WINDOWS if k in old]) > len([k for k, _ in WINDOWS if k in rx]):
            continue                                     # a shorter price series never replaces a longer one
        r["rx"] = rx
    return fails


# ------------------------------------------------------------------ revenue change
def fill_yoy(rows):
    for r in rows:
        if r.get("comparable") is False:
            if r.get("revYoY") is not None and r.get("yoy_src") != "release":
                r["revYoY"], r["yoy_src"] = None, None
            continue
        if r.get("revYoY") is None and r.get("rev_m") and r.get("rev_prior_m"):
            r["revYoY"] = round((r["rev_m"] / r["rev_prior_m"] - 1) * 100, 1)
            r["yoy_src"] = "calc"


# ------------------------------------------------------------------ checks
def fedex_fy_check(rows, review):
    """The four fiscal-year quarters' package averages should average within 3% of the 10-K's full-year figure."""
    found = []
    for (co, fy), ref in FY_ADV.items():
        qs = [r for r in rows if r.get("company") == co and str(r.get("q", "")).startswith(fy + " Q")]
        vals = [(r.get("vol") or {}).get("adv_k") for r in qs]
        if len(qs) != 4 or any(v is None for v in vals):
            continue                                     # can't check until all four are entered
        avg = sum(vals) / 4
        if abs(avg / ref["adv_k"] - 1) > 0.03:
            found.append(fy)
            review_add(review, {"type": "earnings-check", "key": f"adv-check|{co}|{fy}|{round(avg)}", "company": co, "fy": fy,
                                "avg_adv_k": round(avg, 1), "fy_adv_k": ref["adv_k"], "src": ref["src"],
                                "note": f"{co} {fy}: the four quarterly packages-a-day figures average {avg:,.0f} thousand, more than 3% from the "
                                        f"full-year {ref['adv_k']:,} thousand. Check each quarter against its filing."})
    return found


def vol_problems(rows):
    """Package blocks missing their source or check date (every stored number needs both)."""
    return [f"{r.get('company')} {r.get('q')}" for r in rows if r.get("vol") and not (r["vol"].get("src") and r["vol"].get("checked"))]


# ------------------------------------------------------------------ new quarters from the release (B32)
def text_of(page):
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def read_release(url, fetch=None):
    """Headline, revenue ($ billions as printed) and adjusted diluted EPS from a release page."""
    page = (fetch or (lambda u: get(u).text))(url)
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page) or re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    head = text_of(m.group(1)) if m else ""
    t = text_of(page)
    rev = re.search(r"(?i)\b(?:consolidated\s+)?revenues?\s+(?:of|was|were|totaled)\s+\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*billion", t)
    eps = re.search(r"(?i)\badjusted\s+diluted\s+(?:earnings\s+per\s+share|EPS)\s+(?:of|was|were)\s+\$\s?(\d{1,2}\.\d{2})", t)
    return {"headline": head, "rev": float(rev.group(1)) if rev else None, "eps": float(eps.group(1)) if eps else None}


def find_release(nx, ir, known, fetch=None):
    """The release's address on the company's investor-relations page: the first link that contains the next-date
    entry's "match" text and isn't already in the history."""
    if not nx.get("match") or not ir.get(nx["c"]):
        return None
    page = (fetch or (lambda u: get(u).text))(ir[nx["c"]])
    year = nx["d"][:4]
    for href in re.findall(r'href="([^"]+)"', page):
        u = urljoin(ir[nx["c"]], html.unescape(href))
        if nx["match"].lower() in u.lower() and year in u and u not in known:
            return u
    return None


def add_new_quarters(rows, nxt, review, today, fetch=None, pause=2.0):
    added = []
    ir = nxt.get("ir") or {}
    known = {r.get("release") for r in rows}
    for nx in nxt.get("next") or []:
        if not nx.get("c") or not nx.get("d") or nx["d"] > today:
            continue
        if any(r.get("company") == nx["c"] and r.get("q") == nx["q"] for r in rows):
            continue
        key = f"earnings-new|{nx['c']}|{nx['q']}"
        try:
            url = find_release(nx, ir, known, fetch)
        except Exception as e:
            print(f"earnings: {nx['c']} release page: {e}", file=sys.stderr)
            url = None
        if not url:
            late = (dt.date.fromisoformat(today) - dt.date.fromisoformat(nx["d"])).days
            if late >= 2 or not nx.get("match"):
                review_add(review, {"type": "earnings-missing", "key": key + "|missing", "company": nx["c"], "q": nx["q"], "d": nx["d"], "ir": ir.get(nx["c"]),
                                    "note": "The release wasn't found automatically. Add this quarter by hand from the company's release: revenue, adjusted EPS, then packages a day, operating days and revenue per piece from the 10-Q."})
            continue
        r1 = read_release(url, fetch)
        time.sleep(pause)
        r2 = read_release(url, fetch)                    # a second, separate read
        if not (r1["headline"] and r1["rev"] is not None and r1["eps"] is not None and r1 == r2):
            review_add(review, {"type": "earnings-unconfirmed", "key": key + "|unconfirmed", "company": nx["c"], "q": nx["q"], "url": url, "read1": r1, "read2": r2,
                                "note": "Two reads of the release didn't give the same headline, revenue and EPS (or one was missing). Add the quarter by hand from the release."})
            continue
        p = nx.get("period") or {}
        comparable = p.get("months") == 3
        row = {"company": nx["c"], "q": nx["q"], "d": nx["d"], "rev": r1["rev"], "revYoY": None, "eps": r1["eps"], "take": None,
               "release": url, "transcript": None, "webcast": None, "filing": None, "period": p or None, "label": nx.get("label") or nx["q"],
               "rel_time": None, "rev_m": None, "rev_prior_m": None, "yoy_src": None, "comparable": comparable, "vol": None,
               "checked": False, "headline": r1["headline"]}
        if nx["c"] == "FedEx" and (p.get("start") or nx["d"]) >= SPLIT:
            row["note"] = "Excludes FedEx Freight, which separated June 1, 2026"
        if not comparable:
            row["note"] = (row.get("note", "") + "; " if row.get("note") else "") + f"{p.get('months') or 'Not a'}-month period, not compared with a year earlier"
        rows.append(row)
        known.add(url)
        added.append(f"{nx['c']} {nx['q']}")
        review_add(review, {"type": "earnings-new", "key": key, "company": nx["c"], "q": nx["q"], "url": url,
                            "note": "Added automatically from the release (checked: false). Check revenue, EPS and the period against the release; "
                                    "add the summary line, call and filing links, and packages a day, operating days and revenue per piece from the 10-Q "
                                    "with its address and check date; then set checked: true."})
    return added


def main():
    rows = load("earnings.json", [])
    nxt = load("earnings_next.json", {})
    review = load("review.json", [])
    n_review = len(review)
    today = today_et().isoformat()
    fails = []
    try:
        added = add_new_quarters(rows, nxt, review, today)
    except Exception as e:
        added, fails = [], [f"new quarters: {e}"]
    fill_yoy(rows)
    fails += update_reactions(rows, today)
    bad = fedex_fy_check(rows, review)
    for x in vol_problems(rows):
        fails.append(f"{x}: package figures without a source or check date")
    save("earnings.json", rows)
    if len(review) != n_review:
        save("review.json", review)
    print("earnings:", {"added": added, "rx": sum(1 for r in rows if r.get("rx")), "final": sum(1 for r in rows if (r.get("rx") or {}).get("final")),
                        "adv_check": bad})
    if fails:
        for f in fails:
            print("earnings:", f, file=sys.stderr)
        sys.exit(1)                                      # the workflow shows a warning; the last good figures are kept


if __name__ == "__main__":
    main()
