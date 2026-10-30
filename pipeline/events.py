"""One event, every page. Ties what happened in the same week together: a carrier's earnings report and the rate, fee or guide
changes it posted around the same days. Writes data/events.json {"links": [{"a": story, "b": story, "why": text}]}; the app shows
each story's links as "Same week from <carrier>" on its page. Offline and cheap: it only reads data/.

Run: python pipeline/events.py
"""
import datetime as dt
import sys
from common import load, save

WINDOW = 7                                    # days either side of a report
RATE_CATS = {"Pricing & GRI", "Fees & rules", "Peak season", "Guide changes", "Fuel"}
CARRIERS = ("UPS", "FedEx", "USPS")


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def same_week_links(stories, rows, today):
    """Pairs (earnings story, rate/guide story) of one carrier whose dates are within a week of a report in the last 30 days."""
    links, seen = [], set()
    for r in rows:
        co, d = r.get("company"), r.get("d")
        if co not in CARRIERS or not d or d > today or days(d, today) > 30:
            continue
        earn = [s for s in stories if co in s.get("c", []) and s.get("cat") == "Earnings & markets" and -1 <= days(d, s["date"]) <= 3]
        rate = [s for s in stories if co in s.get("c", []) and s.get("cat") in RATE_CATS and s.get("lvl", 1) >= 2 and abs(days(d, s["date"])) <= WINDOW]
        if not earn:
            continue
        e = max(earn, key=lambda s: (s.get("lvl", 1), s["date"] == d))       # the report's lead story: one link, not one per article
        for t in rate:
            if (e["id"], t["id"]) not in seen:
                seen.add((e["id"], t["id"]))
                links.append({"a": e["id"], "b": t["id"], "why": f"{co} reported {r.get('label') or r['q']} on {d}"})
    return links


def main():
    today = dt.date.today().isoformat()
    stories = [s for s in load("news.json", []) if s.get("id") and s.get("date")]
    links = same_week_links(stories, load("earnings.json", []), today)
    old = load("events.json", {})
    if old.get("links") != links:
        save("events.json", {"links": links})
    print(f"events: {len(links)} same-week links")


if __name__ == "__main__":
    sys.exit(main())
