"""Memory across years: the pricing almanac and the patterns it shows.

data/almanac.json is a sourced list of carrier pricing events (UPS, FedEx and USPS rate increases, peak surcharges, fuel
table and surcharge changes) and industry milestones since 2018. It was seeded by research and grows on its own: every
run, new price stories for UPS, FedEx and USPS are read and any yearly event they report is added (one entry per carrier,
year, kind and effective date; the story is its source).

data/patterns.json holds a handful of short notes on how this year compares with earlier years (timing, size, structure
of rate increases and surcharges; what keeps recurring; what is new). They are rewritten about once a week, or as soon as
the almanac gains an event, and only state facts and figures found in the almanac and the stories given.

Usage: python themes.py [--force]
"""
import datetime as dt, json, re, sys
from common import load, save, claude, parse_json, MODEL_FAST, MODEL_WRITE, numbers_supported, cycle_of

BIG = ("UPS", "FedEx", "USPS")
PRICE_CATS = ("Pricing & GRI", "Peak season", "Fees & rules", "Guide changes", "Fuel", "Postal")
KINDS = {"gri", "peak", "fuel_table", "das", "dim", "surcharge", "program", "price_change", "fee", "other"}
PATTERN_DAYS = 7

EXTRACT = """You maintain a parcel pricing almanac. From the STORY below (about UPS, FedEx or USPS), list the yearly pricing events it
reports, using ONLY facts stated in the story. An event is one of: a general rate increase or USPS price change (kind "gri" or
"price_change"), a peak or demand surcharge program ("peak"), a fuel surcharge table change ("fuel_table"), a delivery-area
ZIP list change ("das"), a dimensional weight change ("dim"), a new or changed surcharge or fee ("surcharge" or "fee"), or a
pricing program change ("program"). Skip opinion, forecasts and anything not announced by the carrier.
Reply JSON only: a list (possibly empty) of
{"carrier": "UPS|FedEx|USPS", "year": rate year as a number, "kind": "...", "announced": "YYYY-MM-DD or null",
 "effective": "YYYY-MM-DD or null", "pct": average % as a number or null, "headline": "one neutral line under 100 chars",
 "details": ["short factual bullets with figures from the story"]}"""

PATTERNS = """You are the year-over-year desk of Parcel Pigeon, a U.S. small-parcel news app read by shippers and industry
executives. You get the ALMANAC (carrier pricing events and industry milestones since 2018, each with an id) and this year's
STORYLINES and RECENT PRICE STORIES. Write 3 to 6 short notes on how this year compares with earlier years: timing (when
increases were announced and took effect), size (average increases year by year), structure (surcharges and fees that keep
growing, new kinds of charges), off-cycle changes (marked OFF-CYCLE: price changes taking effect outside the annual increase
window and the peak season, which have become more frequent), and what is genuinely new this year. Keep the date a change was
announced and the date it takes effect apart, and say which one you mean. Rules: use ONLY facts and figures in the inputs; every
number must appear in them; name the years you compare; neutral wire style; no advice, no predictions, no adjectives that
judge. Reply JSON only: {"items": [{"t": "headline under 70 characters", "body": "2-3 sentences", "carriers": ["UPS"|"FedEx"|
"USPS"|"Industry"], "refs": ["almanac ids or story ids you used"]}]}"""


def key(e):
    return (e.get("carrier"), int(e.get("year") or 0), e.get("kind"), e.get("effective") or e.get("announced") or "")


def eid(e):
    return re.sub(r"[^a-z0-9]+", "-", f"{e.get('carrier')}-{e.get('year')}-{e.get('kind')}-{e.get('effective') or e.get('announced') or ''}".lower()).strip("-")


def grow(alm, st):
    """Add yearly events reported by new UPS, FedEx and USPS price stories."""
    done = set(st.get("read", []))
    have = {key(e) for e in alm}
    news = [s for s in load("news.json", []) if s.get("id") not in done and s.get("cat") in PRICE_CATS
            and set(s.get("c") or []) & set(BIG) and int(s.get("lvl") or 1) >= 2 and s.get("kind") not in ("Opinion", "Analysis")]
    added = 0
    for s in news[:12]:
        text = f"{s['date']}: {s['title']}. {s.get('sum', '')} {s.get('plain', '')} " + \
               " ".join(f"{d.get('d')}: {d.get('w')}" for d in s.get("dates") or [] if isinstance(d, dict))
        try:
            got = parse_json(claude(MODEL_FAST, EXTRACT, "STORY:\n" + text, max_tokens=800))
        except Exception as e:
            print(f"  almanac: couldn't read {s['id']}: {e}", file=sys.stderr); continue
        done.add(s["id"])
        for e in got if isinstance(got, list) else []:
            if not isinstance(e, dict) or e.get("carrier") not in BIG or e.get("kind") not in KINDS or not str(e.get("year") or "").isdigit():
                continue
            if numbers_supported(" ".join([str(e.get("pct") or "")] + [str(x) for x in e.get("details") or []]), text):
                continue          # a figure the story doesn't contain: leave the event out rather than guess
            e["year"] = int(e["year"])
            if key(e) in have:
                continue
            e.update({"id": eid(e), "sources": [x["url"] for x in (s.get("srcs") or [])[:3] if x.get("url")], "story": s["id"],
                      "conf": "confirmed", "auto": True})
            alm.append(e); have.add(key(e)); added += 1
            print(f"  almanac: + {e['carrier']} {e['year']} {e['kind']}: {e.get('headline')}")
    st["read"] = list(done)[-2000:]
    return added


def compact(alm):
    lines = []
    for e in sorted(alm, key=lambda e: (e.get("year") or 0, e.get("carrier") or "", e.get("effective") or e.get("date") or "")):
        when = e.get("effective") or e.get("date") or ""
        ann = f" (announced {e['announced']})" if e.get("announced") else ""
        if cycle_of(e.get("carrier"), e.get("kind"), e.get("effective"), e.get("announced")) == "off":
            ann += " OFF-CYCLE"
        pct = f" avg {e['pct']}%" if e.get("pct") is not None else ""
        det = "; ".join(str(x) for x in (e.get("details") or [])[:3])
        lines.append(f"{e.get('id')} | {e.get('year')} {e.get('carrier')} {e.get('kind')} {when}{ann}{pct}: {e.get('headline')}. {det}")
    return "\n".join(lines)


def patterns(alm, force=False):
    old = load("patterns.json", {})
    if not force and old.get("updated") and (dt.date.today() - dt.date.fromisoformat(old["updated"])).days < PATTERN_DAYS:
        return False
    year = dt.date.today().year
    threads = load("threads.json", {})
    lines = [f"- {t.get('n')}: {t.get('s') or ''} (last {t.get('last')})" for t in threads.values()
             if (t.get("last") or "") >= f"{year - 1}-07-01"][:30]
    recent = [s for s in load("news.json", []) if s.get("cat") in PRICE_CATS and s.get("date", "") >= f"{year - 1}-07-01"][:40]
    rs = "\n".join(f"{s['id']} | {s['date']} | {s['title']}. {s.get('sum', '')}" for s in recent)
    src = compact(alm)
    user = f"Today is {dt.date.today().isoformat()}.\n\nALMANAC:\n{src}\n\nSTORYLINES:\n" + "\n".join(lines) + f"\n\nRECENT PRICE STORIES:\n{rs}"
    try:
        res = parse_json(claude(MODEL_WRITE, PATTERNS, user, max_tokens=2000))
    except Exception as e:
        print(f"  patterns failed: {e}", file=sys.stderr); return False
    allin = src + "\n" + rs + "\n" + "\n".join(lines)
    items = []
    for it in (res or {}).get("items") or []:
        if not isinstance(it, dict) or not it.get("t") or not it.get("body"):
            continue
        bad = numbers_supported(it["t"] + " " + it["body"], allin)
        if bad:
            print(f"  pattern dropped (figures not in the inputs: {', '.join(bad)}): {it['t']}"); continue
        items.append({k: it.get(k) for k in ("t", "body", "carriers", "refs")})
    if not items:
        return False
    save("patterns.json", {"updated": dt.date.today().isoformat(), "items": items[:6]})
    print(f"  patterns: {len(items)} notes")
    return True


def main():
    alm, st = load("almanac.json", []), load("almanac_state.json", {})
    if not alm:
        print("themes: no almanac yet"); return
    added = grow(alm, st)
    if added:
        save("almanac.json", sorted(alm, key=lambda e: (-(e.get("year") or 0), e.get("carrier") or "", e.get("kind") or "")))
    save("almanac_state.json", st)
    patterns(alm, force=added > 0 or "--force" in sys.argv)


if __name__ == "__main__":
    main()
