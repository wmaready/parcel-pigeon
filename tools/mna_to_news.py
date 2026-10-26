#!/usr/bin/env python3
"""Oct 26, 2026: every M&A card has its story in regular News, tied back to the card.
Two built-in cards (ReturnPro-iF Returns, the FedEx-led InPost deal) had no story, and the editor pass had taken the Uber-ezCater
story off News while its card stayed. This writes the two missing stories from their cards, links the cards to them, and puts
ezCater back. Idempotent. Run: python3 tools/mna_to_news.py && node pipeline/export_seed.js index.html data/seed.json"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
load = lambda f: json.loads((ROOT / "data" / f).read_text())
save = lambda f, v: (ROOT / "data" / f).write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n")

STORIES = [
    {"id": "dl-returnpro-ifreturns", "match": "ReturnPro buys iF Returns", "date": "2026-09-21", "c": ["Industry"],
     "title": "ReturnPro buys Madrid returns-software platform iF Returns"},
    {"id": "dl-inpost-fedex", "match": "FedEx-led group buys control of InPost", "date": "2026-09-30", "c": ["FedEx"],
     "title": "FedEx-led group completes €7.8B takeover of InPost"},
]


def first_sentence(t):
    return re.split(r"(?<=[.!?])\s", t.strip())[0]


def apply():
    html_p = ROOT / "index.html"
    html = html_p.read_text()
    drop = load("drop.json")
    news = load("news.json")
    have = {n["id"] for n in news}
    seed = {d["title"]: d for d in load("seed.json").get("deals", [])}
    changed = 0
    for s in STORIES:
        d = seed.get(s["match"])
        if not d:
            continue
        if s["id"] not in have:
            srcs = d.get("srcs") or []
            news.append({"id": s["id"], "date": s["date"], "c": s["c"], "cat": "M&A", "kind": "News", "title": s["title"],
                         "sum": d["sum"], "imp": "watch", "lvl": 1,
                         "plain": "No change to rates or service has been announced. " + first_sentence(d["why"]),
                         "why": d["why"], "tie": (d.get("ties") or [{}])[0].get("t") if d.get("ties") else None,
                         "act": None, "dates": [], "src": srcs[0]["src"] if srcs else "", "url": srcs[0]["url"] if srcs else "",
                         "srcs": srcs, "auto": True, "added": s["date"] + "T00:00:00Z", "restored": "2026-10-26"})
            changed += 1
        if f"story:'{s['id']}'" not in html:
            if s["match"] == "ReturnPro buys iF Returns":
                a = "  title:'ReturnPro buys iF Returns',"
                html = html.replace(a, f"  story:'{s['id']}',\n" + a, 1)
            else:
                a = "Object.assign(G('InPost'),{title:'FedEx-led group buys control of InPost',"
                html = html.replace(a, f"Object.assign(G('InPost'),{{story:'{s['id']}',title:'FedEx-led group buys control of InPost',", 1)
            changed += 1
    keep = [x for x in drop if (x if isinstance(x, str) else x.get("id")) != "nrc72492"]      # Uber-ezCater is back in News
    if len(keep) != len(drop):
        save("drop.json", keep)
        changed += 1
    save("news.json", news)
    html_p.write_text(html)
    return changed


if __name__ == "__main__":
    print("changed", apply())
