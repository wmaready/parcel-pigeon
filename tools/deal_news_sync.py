"""Oct 26, 2026: News and M&A disagreed. The editor pass took four deal stories off News ("not parcel") while their M&A
cards stayed. Two are delivery deals and come back to News; two have nothing to do with delivery and leave M&A.
Idempotent; safe to re-run after main's robot commits."""
import json
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data"
load = lambda f: json.loads((D / f).read_text())
def save(f, v): (D / f).write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n")

BACK = {"a3bcc80e64163", "a3341a802bc1a"}                       # Instacart sale talks; C.H. Robinson-RXO
OUT = {"Melar SPAC merges with Everli Global", "Duncan Solutions sells Pioneer Credit Recovery"}

drop = [d for d in load("drop.json") if (d if isinstance(d, str) else d.get("id")) not in BACK]
save("drop.json", drop)

deals = load("deals.json")
by_story = {d.get("story"): d for d in deals}
news = load("news.json")
have = {n["id"] for n in news}

ic = by_story.get("a3bcc80e64163")
if ic and "a3bcc80e64163" not in have:
    news.append({
        "id": "a3bcc80e64163", "date": "2026-10-23", "c": ["Industry"], "cat": "M&A", "kind": "News",
        "title": "Instacart explores sale after early talks with Uber, DoorDash",
        "sum": ic["sum"],
        "imp": "watch", "lvl": 1,
        "plain": "No change to rates or service. " + ic["note"],
        "why": ic["why"].split(" That outlet's")[0],
        "tie": "Uber partnered with Instacart in 2024; DoorDash discussed buying it in 2021.",
        "act": None, "dates": [], "src": ic["srcs"][0]["src"], "url": ic["srcs"][0]["url"], "srcs": ic["srcs"],
        "auto": True, "added": "2026-10-23T00:00:00Z", "restored": "2026-10-26"})

ch = by_story.get("a3341a802bc1a")
if ch and "a3341a802bc1a" not in have:
    news.append({
        "id": "a3341a802bc1a", "date": "2026-10-05", "c": ["Industry"], "cat": "M&A", "kind": "News",
        "title": "C.H. Robinson to buy RXO in stock-and-cash deal",
        "sum": "C.H. Robinson Worldwide plans to acquire brokerage and transportation services provider RXO in a stock-and-cash "
               "transaction with a $5.8 billion implied transaction value, the companies announced. The deal is expected to close "
               "in the first half of 2027, subject to regulatory clearance and RXO shareholder approval.",
        "imp": "watch", "lvl": 1,
        "plain": "No change to rates or service has been announced. The deal is expected to close in the first half of 2027, "
                 "subject to regulatory clearance and RXO shareholder approval.",
        "tie": "RXO bought UPS's Coyote Logistics for $1.025 billion in 2024.",
        "act": None, "dates": [], "src": ch["srcs"][0]["src"], "url": ch["srcs"][0]["url"], "srcs": ch["srcs"],
        "auto": True, "updated": "2026-10-05", "restored": "2026-10-26"})

news.sort(key=lambda n: n.get("date") or "", reverse=True)
save("news.json", news)
save("deals.json", [d for d in deals if d.get("title") not in OUT])
print("news", len(news), "deals", len([d for d in deals if d.get("title") not in OUT]))
