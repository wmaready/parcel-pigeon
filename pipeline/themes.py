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
from common import load, save, claude, parse_json, MODEL_FAST, MODEL_WRITE, numbers_supported, cycle_of, stated_years, doc_year, \
    is_primary, programs_for

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


# ---------------------------------------------------------------- B6 / B14: "not yet announced" never outlives the announcement
# When UPS announced its 2027 increase (Oct 22-23, 2026), the Docs note "Not yet published as of Oct 9, 2026", the story
# "UPS has not yet announced 2027 rates" and the almanac entry "UPS 2027 general rate increase not yet announced" all
# stayed up, so Ask Coop contradicted the rate clock. Each run, a Pricing & GRI story for a carrier and rate year closes
# the matching placeholders, or sends them to data/review.json when it can't close them from sourced facts.
WAITING = re.compile(r"\b(still waiting|waiting (on|for)|not yet (been )?(announced|published|posted)|yet to (announce|publish|post)|"
                     r"has(n't| not) (yet )?(announced|published|posted))\b", re.I)
GRI_TEXT = re.compile(r"general rate|\bGRI\b|average (net )?(rate )?increase|rates? (increase|rise)|rate increase", re.I)


def nice(d):
    try:
        return dt.date.fromisoformat(str(d)[:10]).strftime("%b %-d, %Y")
    except Exception:
        return None


def rate_year(s):
    """The rate year a price story is about. Increases that take effect from mid-December are the next year's rates
    (UPS's 2026 rates took effect Dec 22, 2025); otherwise the effective year, or the one year the headline states."""
    act = str(s.get("act") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", act):
        y, m, d = int(act[:4]), int(act[5:7]), int(act[8:10])
        return y + 1 if (m == 12 and d >= 15) else y
    ys = stated_years(s.get("title"))
    return ys[0] if len(ys) == 1 else None


def gri_landed(news):
    """(carrier, rate year, story) for each published general-rate-increase story: cat 'Pricing & GRI', prices going up,
    not opinion, not unconfirmed, not itself a 'still waiting' story, and not one program's own price change (SBR)."""
    out = []
    for s in news:
        if not isinstance(s, dict) or s.get("cat") != "Pricing & GRI" or s.get("imp") != "up" or s.get("unconf") \
                or s.get("kind") in ("Opinion", "Analysis"):
            continue
        text = f"{s.get('title') or ''} {s.get('sum') or ''}"
        if WAITING.search(text) or not GRI_TEXT.search(text) or programs_for(None, s.get("title") or ""):
            continue
        y = rate_year(s)
        if y:
            out += [(c, y, s) for c in s.get("c") or []]
    return out


def placeholder(e):
    """An almanac GRI entry that only says the increase isn't announced yet (no announcement, no figure, no date)."""
    words = " ".join([str(e.get("headline") or ""), str(e.get("note") or "")])
    return e.get("kind") == "gri" and not e.get("announced") and not e.get("story") and \
        bool(WAITING.search(words) or (e.get("pct") is None and not e.get("effective")))


def gri_pct(s):
    """The average increase the story states: the news writer's rate clock figure, else a proven audit change."""
    for d in s.get("dates") or []:
        fx = (d or {}).get("fx") if isinstance(d, dict) else None
        if isinstance(fx, dict) and fx.get("t") == "gri" and isinstance(fx.get("pct"), (int, float)):
            return fx["pct"]
    for c in s.get("changes") or []:
        if GRI_TEXT.search(f"{c.get('what') or ''} {c.get('after') or ''}"):
            m = re.search(r"(\d+(?:\.\d+)?)\s?%", c.get("after") or "")
            if m:
                return float(m.group(1))
    return None


def to_review(rv, kind, title, note, story, today):
    if any(x.get("type") == kind and x.get("title") == title for x in rv if isinstance(x, dict)):
        return
    rv.insert(0, {"type": kind, "title": title, "story_id": story.get("id"), "url": story.get("url"), "date": today, "note": note})


def close_placeholders(alm, today=None):
    """Close (or send to review) every placeholder a landed GRI story answers: Docs entries with no link that say "not yet
    published", "still waiting" stories, and almanac GRI entries with no announcement. Returns what it did, for the log."""
    today = today or dt.date.today().isoformat()
    news, seed = load("news.json", []), load("seed.json", {})
    landed = gri_landed(news)
    if not landed:
        return []
    done, rv = [], load("review.json", [])
    n_review = len(rv)
    docs, drop = load("docs.json", []), load("drop.json", [])
    used = {d.get("u") for d in docs + (seed.get("docs") or []) if d.get("u")}
    dropped = {d if isinstance(d, str) else d.get("id") for d in drop}
    docs_changed = drop_changed = False
    for c, y, s in landed:
        src = next((x for x in s.get("srcs") or [] if is_primary(x.get("url"))), None)
        when = f"first reported {nice(s.get('ann') or s.get('date'))}" if not s.get("ann") else f"announced {nice(s['ann'])}"
        eff = f"takes effect {nice(s['act'])}" if nice(s.get("act")) else "effective date not stated yet"
        # 1. Docs: the "not yet published" note for this carrier and year
        for d in docs:
            if d.get("c") != c or d.get("u") or doc_year(d) != y or not re.search(r"not yet", str(d.get("d") or ""), re.I) or \
                    not (d.get("t") == "GRI notice" or re.search(r"rate increase|\bGRI\b", d.get("n") or "", re.I)):
                continue
            if not src:
                to_review(rv, "placeholder", d.get("n"), f"{c} {y}: a rate increase story landed ({s.get('title')}) but has no "
                          f"{c} source to link. Point this Docs entry to {c}'s own announcement.", s, today)
                continue
            d.update({"d": f"{c} {y} rate increase {when}; {eff}.", "eff": s.get("act"),
                      "cur": True, "checked": today, "upd": today, "closed_by": s.get("id")})
            # the app matches Docs entries by address first: a link another entry already uses (the rate hub page) would
            # overwrite that entry, so it goes in "see" and this entry keeps matching by name
            if src["url"] in used:
                d["see"] = src["url"]
            else:
                d["u"] = src["url"]
            docs_changed = True
            done.append(f"docs: closed '{d.get('n')}' with story {s.get('id')}")
        # 2. "Still waiting" stories for this carrier and year, built-in ones included (the app honors drop.json)
        for w in news + (seed.get("news") or []):
            if not isinstance(w, dict) or w.get("id") in dropped or w.get("id") == s.get("id") or c not in (w.get("c") or []):
                continue
            text = " ".join(str(w.get(k) or "") for k in ("title", "sum", "plain"))
            title = str(w.get("title") or "")
            if WAITING.search(text) and str(y) in text and re.search(r"\b" + re.escape(c) + r"\b", title, re.I) \
                    and not any(re.search(r"\b" + re.escape(o) + r"\b", title) for o in ("UPS", "FedEx", "USPS", "Amazon", "DHL") if o != c) \
                    and (w.get("date") or "") <= (s.get("date") or ""):
                drop.append({"id": w["id"], "why": f"Superseded by {s.get('id')}: {s.get('title')}"})
                dropped.add(w["id"]); drop_changed = True
                done.append(f"story {w['id']} superseded by {s.get('id')}")
        # 3. The almanac's placeholder for this carrier, year and kind
        for e in list(alm):
            if e.get("carrier") != c or int(e.get("year") or 0) != y or not placeholder(e):
                continue
            real = [x for x in alm if x is not e and x.get("carrier") == c and int(x.get("year") or 0) == y
                    and x.get("kind") == "gri" and not placeholder(x)]
            old = f"{e.get('headline')} | {e.get('note') or ''} | {'; '.join(map(str, e.get('details') or []))}"
            if real:
                alm.remove(e)
                done.append(f"almanac: removed placeholder {e.get('id')}; {real[0].get('id')} has the announcement")
            else:
                pct = gri_pct(s)
                e.update({"headline": f"{c} {y} rate increase announced" + (f": {pct:g}% average" if pct is not None else ""),
                          "announced": s.get("ann"), "effective": s.get("act"), "pct": pct,
                          "details": [str(s.get("title") or "")], "sources": [x["url"] for x in (s.get("srcs") or [])[:3] if x.get("url")],
                          "story": s.get("id"), "conf": "review",
                          "note": f"Updated automatically on {today} from story {s.get('id')}; a person should check the figures."})
                done.append(f"almanac: closed placeholder {e.get('id')} with story {s.get('id')} (sent to review)")
            to_review(rv, "almanac-placeholder", f"{c} {y} gri", f"Was: {old}. Now answered by story {s.get('id')}: "
                      f"{s.get('title')}. Check the almanac entry's figures.", s, today)
    if docs_changed:
        save("docs.json", docs)
    if drop_changed:
        save("drop.json", drop)
        live = [x for x in news if x.get("id") not in dropped]
        if len(live) != len(news):
            save("news.json", live)
    if len(rv) != n_review:
        save("review.json", rv[:200])
    for line in done:
        print("  placeholders:", line)
    return done


def main():
    alm, st = load("almanac.json", []), load("almanac_state.json", {})
    if not alm:
        print("themes: no almanac yet")
        close_placeholders(alm)
        return
    added = grow(alm, st)
    closed = close_placeholders(alm)
    if added or any(x.startswith("almanac") for x in closed):
        save("almanac.json", sorted(alm, key=lambda e: (-(e.get("year") or 0), e.get("carrier") or "", e.get("kind") or "")))
    save("almanac_state.json", st)
    patterns(alm, force=added > 0 or "--force" in sys.argv)


if __name__ == "__main__":
    main()
