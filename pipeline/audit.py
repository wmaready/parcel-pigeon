"""Parcel Pigeon auditor. Checks that every piece of the app lines up, fixes what is safe to fix, and reports the rest.

Reads:  data/seed.json (the app's built-in data, from export_seed.js) + data/news.json, deals.json, fuel.json (pipeline)
Writes: data/audit.json   fixes the app applies on load (clock entries to add, story-to-clock links, stale flags)
                           and the open issue list
        a single GitHub issue "Parcel Pigeon audit" kept up to date, plus a phone push for new high-priority problems

Checks
  price-no-date      price increase with no effective date, so it is missing from the rate clock (tries to find the date)
  date-not-on-clock  story has a future effective date but no rate clock entry links to it (auto-links or adds an entry)
  clock-bad-ref      rate clock entry points at a story that does not exist (auto-removes the reference)
  clock-no-story     future rate clock entry with no story behind it
  clock-past-up      "Next cost change" style entries whose date passed but are still described as upcoming
  duplicate          two stories that look like the same event
  superseded         a "has not announced / pending" story when a newer story on the same carrier and topic exists
  deal-stale         M&A deal still Announced or Pending past its expected close or 90 days
  deal-duplicate     two deal cards for one transaction (same buyer and target, loosely matched)
  deal-storyline     a storyline's newest story is about a deal, but the deal card tells a different story (the storyline
                     says it was terminated, the card still says Pending), or the card has no line on where it stands
  doc-pending        document marked "Not yet published" while a newer story says it has been published
  fuel-stale         fuel data more than 8 days old
  brief-stale        60-second brief mentions something no current story supports (Claude check)
  numbers            story and its rate clock entry disagree on a fee or date (Claude check)
  link-broken        a source link no longer opens
  doc-link-broken    a document library link no longer opens
  no-primary         price, peak or fee story with no carrier source behind it (the carrier's site is the source of truth)
  primary-not-first  a carrier source exists but is not listed first (the app reorders automatically)

Run: python pipeline/audit.py [--offline]   (--offline skips link checks and Claude checks)
"""
import datetime as dt, difflib, hashlib, json, os, re, sys
from common import deals_merged, deal_same, deal_status, DEAL_ENDED, load, save, claude, parse_json, MODEL_FAST, MODEL_WRITE, get, is_primary, primary_first, clock_worthy
from scoop import notify

TODAY = dt.date.today()
ISO = TODAY.isoformat()
OFFLINE = "--offline" in sys.argv
PRICE_CATS = {"Pricing & GRI", "Peak season", "Fees & rules"}
PENDING_RE = re.compile(r"\b(has not (yet )?(announced|published)|not yet (announced|published)|still waiting|pending)\b", re.I)


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def words(s):
    return set(re.findall(r"[a-z0-9.$%]+", s.lower()))


def overlap(a, b):
    A, B = words(a), words(b)
    return len(A & B) / max(1, min(len(A), len(B)))


def deal_storyline_issues(deals, threads, stories):
    """Storylines and deal cards must tell the same story. For each storyline whose newest story is about a deal (the deal's
    own story or a later one in its timeline, or an M&A story in a storyline that holds the deal's first story), the deal
    card's status must agree with what the storyline says happened, and an ended deal needs its "latest" line.
    Returns [(ids, message)]."""
    out = []
    for k, t in (threads or {}).items():
        if t.get("theme"):
            continue                                  # a year theme spans many deals; each deal's own storyline is checked
        S = sorted((stories[i] for i in (t.get("ids") or []) if i in stories), key=lambda s: s.get("date") or "")
        if not S:
            continue
        top, ids = S[-1], set(t.get("ids") or [])
        for d in deals:
            own = {d.get("story")} | {u.get("story") for u in d.get("updates") or []}
            own.discard(None)
            if not (top["id"] in own or (top.get("cat") == "M&A" and own & ids)):
                continue
            said = deal_status({"status": "Pending"}, t.get("s"), top.get("title"), top.get("sum"))
            name = d.get("title") or f"{d.get('buyer')} / {d.get('target')}"
            if said in DEAL_ENDED and d.get("status") != said:
                out.append(([k, top["id"]], f"Storyline \"{t.get('n') or k}\" says the deal was {said.lower()} (\"{top.get('title')}\"), "
                                            f"but the deal card \"{name}\" says {d.get('status')}"))
            elif d.get("status") in DEAL_ENDED and not d.get("latest"):
                out.append(([k, top["id"]], f"Deal card \"{name}\" is {d.get('status')} but has no line on where it stands"))
    return out


WRONG_TITLE = re.compile(r"access denied|request access|page not found|404|error|sign in|log in", re.I)


def _depth(path):
    return len([p for p in (path or "").split("/") if p])


def classify_link(url, name, status, final_url, ctype="", title="", blocked=False):
    """B21: what a document link check means. Returns {state, content_verified, why}:
    blocked    the site turned the checker away (401/403/429/503 or a bot wall): not known, never shown as broken
    broken     404/410 or another error: content_verified False
    wrong-page a redirect to a home or section page, an error.page, or an "Access denied"/"Request Access" title:
               content_verified False (the reader would not get the document)
    opens      the right address answers. content_verified is True only when the page title names the document;
               a 200 alone (a PDF, or a title we can't match) stays None, never "confirmed"."""
    from urllib.parse import urlsplit
    if blocked or status in (401, 403, 429, 503) or status is None:
        return {"state": "blocked", "content_verified": None, "why": f"blocked ({status or 'no answer'})"}
    if status >= 400:
        return {"state": "broken", "content_verified": False, "why": f"HTTP {status}"}
    a, b = urlsplit(url), urlsplit(final_url or url)
    if re.search(r"error\.page|/error(/|$|\.)", b.path, re.I):
        return {"state": "wrong-page", "content_verified": False, "why": "redirected to an error page"}
    if title and WRONG_TITLE.search(title) and "pdf" not in (ctype or ""):
        return {"state": "wrong-page", "content_verified": False, "why": f'page title "{title[:60]}"'}
    moved = (b.netloc.lower().removeprefix("www."), b.path.rstrip("/").lower()) != (a.netloc.lower().removeprefix("www."), a.path.rstrip("/").lower())
    home = re.fullmatch(r"/?([a-z]{2}([-_/][a-z]{2})?/)?(home|index|default)?(\.html?|\.page|\.aspx)?/?", b.path or "/", re.I)
    if moved and (home or _depth(b.path) < _depth(a.path)) and "pdf" not in (ctype or ""):
        return {"state": "wrong-page", "content_verified": False, "why": "redirected to a home or section page"}
    words = {w for w in re.findall(r"[a-z0-9]{3,}", (name or "").lower()) if w not in ("the", "and", "pdf", "page", "for", "with")}
    tw = set(re.findall(r"[a-z0-9]{3,}", (title or "").lower()))
    ok = True if words and title and len(words & tw) * 2 >= len(words) else None
    return {"state": "opens", "content_verified": ok, "why": "title names the document" if ok else "opens; content not confirmed"}


def check_doc_link(url, name, timeout=20):
    """One document link check, recorded with http_status, final_url, content_verified and checked_at."""
    import requests
    from fetch import is_blocked, BROWSER
    status, final, ctype, title, blocked = None, url, "", "", False
    try:
        r = requests.get(url, headers=BROWSER, timeout=timeout, allow_redirects=True, stream=True)
        status, final, ctype = r.status_code, r.url, (r.headers.get("content-type") or "").lower()
        if "pdf" not in ctype and status < 400:
            head = b""
            for chunk in r.iter_content(65536):
                head += chunk
                if len(head) > 200000:
                    break
            text = head.decode("utf-8", "replace")
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            blocked = is_blocked(text)
        r.close()
    except Exception as e:
        print(f"  doc link check failed for {url}: {type(e).__name__}", file=sys.stderr)
    rec = classify_link(url, name, status, final, ctype, title, blocked)
    return {"http_status": status, "final_url": final, "content_verified": rec["content_verified"], "state": rec["state"],
            "why": rec["why"], "checked_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}


def main():
    seed = load("seed.json", {})
    stories = {s["id"]: s for s in seed.get("news", [])}
    for s in load("news.json", []):
        stories.setdefault(s["id"], s)
    clock = list(seed.get("clock", []))
    deals = deals_merged(seed.get("deals", []), load("deals.json", []))     # what readers see: one card per transaction
    docs = list(seed.get("docs", []))
    for d in load("docs.json", []):
        if not any((d.get("u") and x.get("u") == d.get("u")) or (x.get("c") == d.get("c") and x.get("n") == d.get("n")) for x in docs):
            docs.append(d)
    brief = seed.get("brief", [])
    prev = load("audit.json", {})
    issues, fix = [], {"clock_add": [], "clock_link": [], "clock_unlink": []}

    def issue(sev, kind, msg, ids=(), fixed=False):
        issues.append({"sev": sev, "type": kind, "msg": msg, "ids": list(ids), "fixed": fixed})

    # pipeline stories turn their dates into clock entries in the app; mirror that here
    for s in stories.values():
        for i, d in enumerate(s.get("dates") or []):
            if d.get("d") and clock_worthy(s, d) and not any(c["d"] == d["d"] and s["id"] in c.get("news", []) for c in clock):
                clock.append({"id": f"x{s['id']}{i}", "d": d["d"], "w": d.get("w", ""), "c": " · ".join(s.get("c", [])), "imp": d.get("imp", "up"), "news": [s["id"]]})

    linked = {sid for c in clock for sid in c.get("news", [])}

    # 1. price story with no date
    for s in stories.values():
        if s.get("cat") in PRICE_CATS and s.get("imp") == "up" and not s.get("act") and not s.get("dates") and not s.get("inferred") and s["id"] not in linked:
            issue("high", "price-no-date", f"Price increase has no effective date, so it is not on the rate clock: \"{s['title']}\"", [s["id"]])

    # 2. future effective date with no clock entry
    for s in stories.values():
        a = s.get("act")
        if not a or a < ISO or not clock_worthy(s, {"w": s.get("title", ""), "imp": s.get("imp")}):
            continue
        if any(s["id"] in c.get("news", []) and abs(days(c["d"], a)) <= 3 for c in clock):
            continue
        near = [c for c in clock if abs(days(c["d"], a)) <= 3 and (set(s.get("c", [])) & set(re.split(r" · ", c.get("c", ""))))]
        if near:
            fix["clock_link"].append({"clock": near[0]["id"], "story": s["id"]})
            issue("med", "date-not-on-clock", f"Linked \"{s['title']}\" to rate clock entry {near[0]['d']} \"{near[0]['w']}\"", [s["id"]], fixed=True)
        else:
            entry = {"id": "a" + s["id"], "d": a, "w": s["title"][:80], "c": " · ".join(c for c in s.get("c", []) if c != "Industry") or "Industry",
                     "imp": s.get("imp", "up") if s.get("imp") in ("up", "down") else "info", "news": [s["id"]], "auto": True}
            fix["clock_add"].append(entry)
            issue("med", "date-not-on-clock", f"Added rate clock entry {a} for \"{s['title']}\"", [s["id"]], fixed=True)

    # 3/4. clock references
    for c in clock:
        bad = [sid for sid in c.get("news", []) if sid not in stories]
        if bad:
            fix["clock_unlink"].append({"clock": c["id"], "stories": bad})
            issue("low", "clock-bad-ref", f"Removed missing story link(s) {bad} from rate clock entry {c['d']} \"{c['w']}\"", [c["id"]], fixed=True)
        if c["d"] >= ISO and not [sid for sid in c.get("news", []) if sid in stories] and not c.get("note"):
            issue("low", "clock-no-story", f"Rate clock entry {c['d']} \"{c['w']}\" has no story or note explaining it", [c["id"]])

    # 4b. source of truth: the carrier's own site
    live = load("news.json", [])
    live_ids = {x["id"]: x for x in live}
    relinked = []
    for s in stories.values():
        srcs = s.get("srcs") or [{"src": s.get("src"), "url": s.get("url")}]
        prim = [x for x in srcs if is_primary(x.get("url"))]
        recent = days(s["date"], ISO) <= 180   # older history may rest on press reports; recent price news must have the carrier's own source
        if not prim and recent and s.get("cat") in PRICE_CATS and not PENDING_RE.search(s.get("title", "")) \
                and s.get("kind") != "Analysis" and (s.get("imp") in ("up", "down") or s.get("act") or s.get("dates")):
            # (analysis and forecast pieces with no carrier price or date in them don't need a carrier source)
            # a carrier-site detection for the same carrier near this date is the primary source: attach it
            mine = set(s.get("c", [])) - {"Industry"}
            cand = [t for t in stories.values() if t is not s and t.get("cat") == "Guide changes" and is_primary(t.get("url"))
                    and mine & set(t.get("c", [])) and abs(days(t["date"], s["date"])) <= 21]
            if cand and s["id"] in live_ids:
                t = cand[0]
                live_ids[s["id"]].setdefault("srcs", []).insert(0, {"src": t.get("src") or "Carrier", "url": t["url"]})
                live_ids[s["id"]]["srcs"] = primary_first(live_ids[s["id"]]["srcs"])
                relinked.append(s["id"])
                issue("med", "primary-attached", f"Attached carrier-site source {t['url']} to \"{s['title']}\"", [s["id"]], fixed=True)
                continue
            issue("high", "no-primary", f"No carrier source for a price story; figures rest on press reports: \"{s['title']}\"", [s["id"]])
        elif prim and not is_primary(srcs[0].get("url")):
            issue("low", "primary-not-first", f"Carrier source {prim[0]['src']} moved ahead of press coverage on \"{s['title']}\"", [s["id"]], fixed=True)

    # 4c. carrier-page coverage: every watched page should have been read successfully within the last day
    for u, hh in load("watch_health.json", {}).items():
        last = hh.get("last_ok")
        if hh.get("blocked") and hh.get("fails", 0) >= 3:
            issue("high", "watch-blocked", f"Carrier site is turning our reader away (bot protection), so changes on this page are not being seen: {hh.get('carrier')} {hh.get('name')} {u}. "
                  "Fix: add an unblocking proxy as the PP_FETCH_PROXY secret (see pipeline/fetch.py).", [])
        elif hh.get("fails", 0) >= 6 or (last and days(last, ISO) > 1) or (not last and hh.get("last_try") and hh.get("fails", 0) >= 2):
            issue("med", "watch-stale", f"Carrier page not read in over a day: {hh.get('carrier')} {hh.get('name')} ({hh.get('err') or 'no readable text'}) {u}", [])
        elif hh.get("thin", 0) >= 3:
            issue("med", "watch-thin", f"Carrier page reads back almost empty (probably hidden behind scripts or drop-downs): {hh.get('carrier')} {hh.get('name')} {u}. Server said: {hh.get('probe') or 'not probed yet'}", [])

    # 4d. older break: a recent story that is really a later report of something we already had weeks, months or years ago
    _stop = set("with from that this will their they have been after about into over more than says plans adds amid new its are for and the".split())
    tk = lambda t: {w.strip(".") for w in re.findall(r"[a-z0-9$%.]+", (t or "").lower()) if (len(w) >= 4 or any(c.isdigit() for c in w)) and w not in _stop}
    recent = [x for x in stories.values() if days(x["date"], ISO) <= 30 and x.get("kind") != "Alert"]
    older = [x for x in stories.values() if days(x["date"], ISO) > 30]
    for x in recent:
        A = tk(x.get("title"))
        for o in older:
            B = tk(o.get("title"))
            n = len(A & B)
            if n >= 4 and n / max(1, min(len(A), len(B))) >= 0.6 and set(x.get("c") or []) & set(o.get("c") or []) and not x.get("thread") == o.get("thread"):
                issue("med", "older-break", f"\"{x['title']}\" ({x['date']}) looks like a later report of \"{o['title']}\" ({o['date']}). Check whether it is new.", [x["id"], o["id"]])
                break

    # 4c2. news feeds that keep failing or come back empty (a moved RSS address, a search that matches nothing)
    dead = [n for n, f in load("feed_health.json", {}).items() if f.get("fails", 0) >= 6 or (f.get("direct") and f.get("entries") == 0)]
    if dead:
        issue("med", "feed-dead", f"{len(dead)} news feeds failing or empty: " + "; ".join(dead[:10]), [])

    # 4d. watched documents the carrier's site keeps turning away
    blocked_docs = [v.get("n") for v in load("docwatch.json", {}).get("docs", {}).values() if v.get("blocked") and v.get("fails", 0) >= 3]
    if blocked_docs:
        issue("high", "docs-blocked", f"{len(blocked_docs)} watched carrier documents can't be read (bot protection): " + "; ".join(blocked_docs[:8]), [])

    # 5. duplicates
    lst = sorted(stories.values(), key=lambda s: s["date"])
    for i, a in enumerate(lst):
        for b in lst[i + 1:]:
            if days(a["date"], b["date"]) > 7:
                break
            if set(a.get("c", [])) & set(b.get("c", [])) and (sim(a["title"], b["title"]) > 0.62 or overlap(a["title"], b["title"]) > 0.7):
                issue("med", "duplicate", f"Possible duplicate stories: \"{a['title']}\" and \"{b['title']}\"", [a["id"], b["id"]])

    # 6. superseded "not yet announced" stories
    for s in stories.values():
        if PENDING_RE.search(s.get("title", "") + " " + s.get("plain", "")):
            newer = [t for t in stories.values() if t["date"] > s["date"] and t.get("cat") == s.get("cat")
                     and set(t.get("c", [])) & set(s.get("c", [])) and t["id"] != s["id"] and not PENDING_RE.search(t["title"])]
            if newer:
                issue("high", "superseded", f"\"{s['title']}\" may be out of date: newer story \"{newer[0]['title']}\"", [s["id"], newer[0]["id"]])
            elif days(s["date"], ISO) > 14:
                issue("low", "superseded", f"\"{s['title']}\" is {days(s['date'], ISO)} days old; check whether it has been announced", [s["id"]])

    # 7. deals
    for d in deals:
        if d.get("status") in ("Announced", "Pending") and days(d["d"], ISO) > 90 and not (d.get("checked") and days(d["checked"], ISO) <= 30):
            issue("med", "deal-stale", f"Deal {d['buyer']} / {d['target']} still marked {d['status']} after {days(d['d'], ISO)} days; confirm whether it closed", [])
    for i, d in enumerate(deals):
        for e in deals[i + 1:]:
            if deal_same(d, e):
                issue("high", "deal-duplicate", f"Two deal cards for one transaction: \"{d.get('title')}\" and \"{e.get('title')}\"", [x for x in (d.get("story"), e.get("story")) if x])
    for k, why in deal_storyline_issues(deals, load("threads.json", {}), stories):
        issue("high", "deal-storyline", why, k)

    # 8. docs
    for doc in docs:
        if not doc.get("u"):
            hit = [t for t in stories.values() if doc["c"] in t.get("c", []) and t.get("cat") == "Pricing & GRI" and not PENDING_RE.search(t["title"])
                   and t["date"] >= (TODAY - dt.timedelta(days=60)).isoformat() and doc["t"] == "GRI"]
            if hit:
                issue("high", "doc-pending", f"Library still shows \"{doc['n']}\" as not published, but \"{hit[0]['title']}\" exists", [hit[0]["id"]])

    # 9. fuel
    fuel = seed.get("fuel", {})
    live_fuel = load("fuel.json", {})
    latest = max([x for x in [fuel.get("eff"), *((live_fuel.get("eff") or {}).values())] if x] or ["1970-01-01"])
    if days(latest, ISO) > 8:
        issue("high", "fuel-stale", f"Latest fuel rates are from {latest}, {days(latest, ISO)} days ago", [])

    if not OFFLINE:
        # 10. links (a rotating slice each run)
        urls = sorted({x["url"] for s in stories.values() for x in s.get("srcs", [{"url": s.get("url")}]) if x.get("url", "").startswith("http")})
        start = prev.get("link_cursor", 0) % max(1, len(urls))
        batch = (urls[start:] + urls[:start])[:40]
        for u in batch:
            try:
                r = get(u, timeout=15)
                if r.status_code >= 400:
                    raise Exception(r.status_code)
            except Exception as e:
                if "403" in str(e) or "429" in str(e):
                    continue  # sites that block bots are not broken for readers
                issue("low", "link-broken", f"Source link failed ({e}): {u}", [s["id"] for s in stories.values() if any(x.get("url") == u for x in s.get("srcs", []))])
        fix["link_cursor"] = start + len(batch)

        # 10b. document library links (a rotating slice each run). The library is the source of truth for agents,
        # so a dead carrier document is flagged medium.
        # B21: each check is recorded (data/doc_links.json, and on the docs.json entry): http_status, final_url,
        # content_verified, checked_at. A blocked check is never "broken"; a 200 is never "confirmed" by itself.
        durls = sorted({d["u"] for d in docs if (d.get("u") or "").startswith("http")})
        dstart = prev.get("doc_cursor", 0) % max(1, len(durls))
        links = load("doc_links.json", {})
        for u in (durls[dstart:] + durls[:dstart])[:30]:
            name = next((d["n"] for d in docs if d.get("u") == u), u)
            rec = check_doc_link(u, name)
            links[u] = rec
            if rec["state"] == "broken":
                issue("med", "doc-link-broken", f"Library document no longer opens ({rec['why']}): {name} {u}", [])
            elif rec["state"] == "wrong-page":
                issue("med", "doc-link-wrong-page", f"Library link lands on the wrong page ({rec['why']}): {name} {u} -> {rec['final_url']}", [])
        save("doc_links.json", links)
        lib = load("docs.json", [])
        touched = False
        for d in lib:
            rec = links.get(d.get("u") or "")
            if rec and d.get("checked_at") != rec["checked_at"]:
                d.update({k: rec[k] for k in ("http_status", "final_url", "content_verified", "checked_at")}); touched = True
        if touched:
            save("docs.json", lib)
        fix["doc_cursor"] = dstart + 30

        # 11. numbers: story vs its clock entry (only pairs that changed since last run)
        seen = set(prev.get("checked_pairs", []))
        pairs = []
        for c in clock:
            for sid in c.get("news", []):
                s = stories.get(sid)
                if not s or c["d"] < ISO:
                    continue
                key = hashlib.sha1(json.dumps([c, s.get("sum"), s.get("plain"), s.get("act")], sort_keys=True).encode()).hexdigest()[:12]
                if key not in seen:
                    pairs.append((key, c, s))
        if pairs:
            txt = "\n\n".join(f"PAIR {i}\nCLOCK {c['d']} {c['w']} fees={c.get('fees')} note={c.get('note')}\nSTORY {s['title']} | {s['sum']} | effect: {s['plain']} | effective={s.get('act')}"
                              for i, (_, c, s) in enumerate(pairs[:25]))
            try:
                res = parse_json(claude(MODEL_WRITE, "You audit a parcel news app. For each PAIR, check whether the rate clock entry and the story disagree on any date, fee amount, carrier or percentage. Return JSON list of {\"pair\": n, \"problem\": \"one sentence\"} only for real contradictions; [] if none.", txt, max_tokens=1500))
                for r in res:
                    _, c, s = pairs[r["pair"]]
                    issue("high", "numbers", f"{r['problem']} (clock {c['d']} vs \"{s['title']}\")", [s["id"], c["id"]])
            except Exception as e:
                print(f"numbers check failed: {e}", file=sys.stderr)
            fix["checked_pairs"] = list(seen | {k for k, _, _ in pairs[:25]})

        # 12. brief
        if brief:
            facts = "\n".join(f"- {s['title']}: {s.get('plain','')}" for s in sorted(stories.values(), key=lambda s: s["date"], reverse=True)[:30])
            try:
                res = parse_json(claude(MODEL_FAST, "Check each BRIEF line against the STORIES. Return JSON list of {\"line\": n, \"problem\": \"...\"} for lines that state something the stories do not support or that is out of date; [] if all are fine.", "BRIEF:\n" + "\n".join(f"{i}. {re.sub('<[^>]+>','',b)}" for i, b in enumerate(brief)) + "\n\nSTORIES:\n" + facts, max_tokens=800))
                for r in res:
                    issue("med", "brief-stale", f"Brief line {r['line'] + 1}: {r['problem']}", [])
            except Exception as e:
                print(f"brief check failed: {e}", file=sys.stderr)

    if relinked:
        save("news.json", live)
    for k in ("link_cursor", "doc_cursor", "checked_pairs"):   # the hourly offline run must not reset the daily run's progress
        if k not in fix and k in prev:
            fix[k] = prev[k]
    out = {"run": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **fix,
           "issues": issues, "open": [i for i in issues if not i["fixed"]]}
    save("audit.json", out)
    open_ = out["open"]
    print(f"audit: {len(issues)} findings, {len(issues) - len(open_)} fixed automatically, {len(open_)} need a person")
    for i in issues:
        print(f"  [{i['sev']}] {'FIXED ' if i['fixed'] else ''}{i['type']}: {i['msg']}")

    # notify: one GitHub issue kept current; phone push only for NEW high-priority problems
    prev_high = {i["msg"] for i in prev.get("open", []) if i["sev"] == "high"}
    new_high = [i for i in open_ if i["sev"] == "high" and i["msg"] not in prev_high]
    if open_ and (new_high or not prev.get("open")):
        body = "Parcel Pigeon audit found problems that need a person. Fix the data, then this list clears on the next run.\n\n" + \
               "\n".join(f"- [ ] **{i['sev']}** {i['type']}: {i['msg']}" for i in sorted(open_, key=lambda i: ["high", "med", "low"].index(i["sev"])))
        fixed = [i for i in issues if i["fixed"]]
        if fixed:
            body += "\n\nFixed automatically:\n" + "\n".join(f"- {i['msg']}" for i in fixed)
        notify(f"Parcel Pigeon audit: {len(new_high)} new high-priority, {len(open_)} open", body, labels=("audit",))


if __name__ == "__main__":
    main()
