"""Draft the 60-second brief: the three newest developments a parcel shipper hasn't seen yet.
Runs every pipeline run; rewrites the brief only when there is something new. You can edit data/brief.json after."""
import datetime as dt
from common import load, save, claude, parse_json, MODEL_WRITE

SYSTEM = """Write the "60-second brief" for Parcel Pigeon, a news app for small parcel shippers.
Pick the THREE most important things the reader has NOT already seen. Priority order:
1. Newly reported developments from the last 7 days (new programs, deals, filings, price or service changes announced for the
   first time, lawsuits, regulatory moves), especially anything marked FIRST TO REPORT.
2. Developments that change what a shipper pays or which carriers they can use.
Do NOT use: scheduled items readers already know about (a peak fee or GRI that was announced weeks ago and is now taking
effect, a weekly fuel move, a rate already on the rate clock), or anything listed under ALREADY BRIEFED, unless there is
genuinely no new important news; in that case you may use at most one such item.
Each item: a bold lead of 4-9 words, then one or two plain sentences with the key numbers. Use only facts in the stories.
Neutral trade-press tone: no advice, no predictions. Return JSON: [{"id":"story id","text":"<b>Lead.</b> Sentence."}, x3]"""


def main():
    today = dt.date.today()
    brief = load("brief.json", {})
    stories = sorted(load("news.json", []) + [s for s in load("seed.json", {}).get("news", [])], key=lambda s: s["date"], reverse=True)
    seen = set()
    stories = [s for s in stories if not (s["id"] in seen or seen.add(s["id"]))]
    since = (today - dt.timedelta(days=10)).isoformat()
    recent = [s for s in stories if s["date"] >= since][:40]
    if len(recent) < 3:
        return
    newest = max(s["date"] for s in recent)
    if brief.get("newest") == newest and brief.get("week"):
        return  # nothing new since the last brief
    history = brief.get("history", [])[-15:]
    text = "ALREADY BRIEFED:\n" + "\n".join(f"- {h}" for h in history) + "\n\nSTORIES:\n" + "\n".join(
        f"- id={s['id']} date={s['date']} [{s['cat']}] {'FIRST TO REPORT ' if s.get('exclusive') else ''}{'(routine follow-up) ' if s.get('routine') else ''}"
        f"{s['title']}: {s.get('sum','')} Effect: {s.get('plain','')}" for s in recent)
    items = parse_json(claude(MODEL_WRITE, SYSTEM, text, max_tokens=900))[:3]
    if len(items) < 3:
        return
    leads = [i["text"].split("</b>")[0].replace("<b>", "") for i in items]
    save("brief.json", {"week": today.isoformat(), "newest": newest, "items": [i["text"] for i in items],
                        "ids": [i.get("id") for i in items], "history": (history + leads)[-30:]})


if __name__ == "__main__":
    main()
