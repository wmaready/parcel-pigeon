"""New players for the market map.

Companies first show up in the news (a deal, a partnership, a new carrier). They're added as candidates; this step
researches each one (web search through the Claude API when available), confirms it's really part of the parcel world,
fills in its profile (what it does, HQ, owner, website), and links it ONLY to companies already on the map, each link
with a source. Candidates that aren't parcel players are dropped. Newly confirmed players get a "New" badge in the app
and a phone alert (alerts.py, Deals topic).

Usage: python players.py [--max 6]
Also keeps family trees current (family_check, one company per run, about weekly each).
"""
import datetime as dt, json, os, re, sys, time
import requests
from common import load, save, parse_json, API_KEY, MODEL_WRITE, cached_system, track

REALMS = ["national", "regional", "gig", "retail", "3pl", "global", "software", "cold", "auto", "capital"]
KINDS = {"owns", "acquired", "invested", "partner", "merged", "sold", "spun"}

RESEARCH = """You research companies for Parcel Pigeon's market map of the small parcel industry (carriers, couriers, last-mile and
gig delivery, 3PLs and fulfillment, shipping and returns software, retailers' delivery networks, drones and robots, cold chain,
and the investors behind them). Use web search. Be strict: only facts you found in reliable sources (company site, filings,
press releases, established trade press). Never guess. If two sources disagree, leave the field null.

Return JSON only:
{"is_player": true|false,              // false if it isn't part of parcel shipping or delivery (law firm, generic retailer, etc.)
 "n": "official company name TODAY", "al": ["other names, including former names"], "former_names": ["previous names"],
 "status": "active"|"acquired"|"renamed"|"closed"|"unclear",   // what is true today
 "serves_us": true|false,              // operates in the U.S. or serves U.S. shippers or U.S. carriers
 "realm": one of REALMS,
 "own": "public"|"private"|"pe"|"sub", "tk": "ticker or null", "parent": "parent company name or null",
 "hq": "City, ST, USA" or "City, Country", "lat": number, "lon": number,   // HQ city coordinates
 "yr": "founding year or null", "site": "domain.com or null",
 "s": "one neutral sentence: what the company does in parcel",
 "sources": [{"url": "page you read", "what": "what it confirms"}],   // at least two pages on DIFFERENT websites
 "links": [{"other": "a name EXACTLY as written in the KNOWN list", "k": "owns|acquired|invested|partner|merged|sold|spun",
            "dir": "this>other" or "other>this", "y": "year or null", "t": "short label", "url": "source URL"}]}
Links only to companies in the KNOWN list, only real announced relationships, each with the URL where you found it.
Set "is_player" false for: small non-U.S. carriers and couriers with no U.S. operations or U.S. customers (keep national posts,
global carriers and logistics groups, and any company that serves U.S. shippers); a regional office, circle, branch or
subsidiary office of a postal operator or carrier (it belongs to its parent, not a separate player); parcel-spend consultancies
and invoice-audit firms; anything you can't confirm exists today."""


def ask(user, use_search=True, system=None, max_tokens=2500, strict=False, searches=5):
    """One Claude call, with web search. strict=True means the answer is only worth anything if it was really searched:
    a failed search raises instead of falling back to the model's memory, and ask.searches says how many searches ran."""
    body = {"model": MODEL_WRITE, "max_tokens": max_tokens, "system": cached_system(system or RESEARCH), "messages": [{"role": "user", "content": user}]}
    if use_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": searches}]
    ask.searches = 0
    for attempt in range(3):
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=240, json=body,
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        if r.status_code in (429, 500, 502, 503, 529) and attempt < 2:
            time.sleep(8 * (attempt + 1)); continue
        break
    if r.status_code >= 400 and use_search and not strict:
        print(f"  web search unavailable ({r.status_code}); researching from the story only", file=sys.stderr)
        return ask(user, use_search=False, system=system, max_tokens=max_tokens)
    r.raise_for_status()
    j = r.json(); track(j)
    ask.searches = sum(1 for b in j.get("content", []) if b.get("type") == "server_tool_use")
    return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")


ask.searches = 0


# ---------------------------------------------------------------- vetting: nothing is published on one model's word
CORP = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "group", "holdings", "plc", "gmbh", "sa", "ag", "lp", "the"}
BLOCK = re.compile(r"transimpact|parcel spend intelligence", re.I)      # never part of the public map


def norm(name):
    w = [x for x in re.sub(r"[^a-z0-9& ]+", " ", str(name or "").lower().replace("&", " and ")).split() if x not in CORP]
    return "".join(w)


def domain(url):
    h = re.sub(r"^https?://", "", str(url or "").strip().lower()).split("/")[0].split(":")[0]
    h = re.sub(r"^(www|m|amp)\.", "", h)
    p = h.split(".")
    return ".".join(p[-3:]) if len(p) >= 3 and p[-2] in ("co", "com", "org", "gov", "ac") else ".".join(p[-2:])


def review_add(kind, name, why, urls=None):
    """Things that didn't pass the checks wait here (data/sweep_review.json) instead of going on the map."""
    rv = load("sweep_review.json", [])
    d = dt.date.today().isoformat()
    if any(x.get("n") == name and x.get("kind") == kind and x.get("why") == why for x in rv):
        return
    rv.append({"d": d, "kind": kind, "n": name, "why": why, "urls": [u for u in (urls or []) if str(u).startswith("http")][:4]})
    save("sweep_review.json", rv[-400:])


VERIFY = """A colleague wrote the company profile below for Parcel Pigeon's market map. Your job is to find out whether it is WRONG.
Search the web yourself, independently; do not trust the profile or its sources. Check, in this order:
1. Does the company exist, and is that its official name TODAY? (Look for renames, rebrands, mergers, shutdowns, bankruptcies, acquisitions.)
2. Is it part of parcel shipping or delivery, and does it operate in the U.S. or serve U.S. shippers or carriers?
3. Each field: headquarters, founding year, ownership type, ticker, parent company, website.
4. Each link (the list is numbered from 0): did that relationship really happen, between those companies, in that direction?
Mark a field "confirmed" only if you found it in a reliable source yourself; "disputed" if you found something different;
"unverified" if you couldn't tell. Reply JSON only:
{"exists": true|false, "name_ok": true|false, "name_now": "official name today", "status": "active"|"acquired"|"renamed"|"closed"|"unclear",
 "parcel_relevant": true|false, "us_relevant": true|false,
 "fields": {"hq": "confirmed|disputed|unverified", "yr": "...", "own": "...", "tk": "...", "parent": "...", "site": "..."},
 "links": [{"i": 0, "ok": true|false}], "evidence": ["urls you used"], "notes": "one line: anything wrong or doubtful"}"""


def verify_profile(res, known_list=""):
    """Second, adversarial look at a researched profile. Returns (ok, cleaned_profile, reason). A profile goes live only if
    (1) the research cited pages on at least two different websites, (2) a separate search-backed check agrees the company
    exists under that name, is active, is parcel-relevant and U.S.-relevant, and (3) only the fields and links that check
    could confirm are kept; the rest are dropped rather than guessed."""
    srcs = [x for x in (res.get("sources") or []) if isinstance(x, dict) and str(x.get("url") or "").startswith("http")]
    if len({domain(x["url"]) for x in srcs}) < 2:
        return False, res, "fewer than two independent sources"
    if res.get("serves_us") is False or res.get("status") not in ("active", None, "acquired"):
        return False, res, f"status {res.get('status')} / serves_us {res.get('serves_us')}"
    brief = {k: res.get(k) for k in ("n", "al", "former_names", "status", "realm", "own", "tk", "parent", "hq", "yr", "site", "s")}
    brief["links"] = [{"i": i, "other": l.get("other"), "k": l.get("k"), "dir": l.get("dir"), "y": l.get("y"), "url": l.get("url")}
                      for i, l in enumerate(res.get("links") or [])]
    v = parse_json(ask("Profile to check:\n" + json.dumps(brief, ensure_ascii=False), system=VERIFY, max_tokens=1500, strict=True, searches=6)) or {}
    if not isinstance(v, dict) or ask.searches < 1:
        return False, res, "the check did not search"
    if not (v.get("exists") and v.get("name_ok") and v.get("parcel_relevant") and v.get("us_relevant")):
        return False, res, "check failed: " + str(v.get("notes") or "not confirmed")[:160]
    if v.get("status") not in ("active", "acquired"):
        return False, res, f"check says status {v.get('status')}"
    f = v.get("fields") or {}
    out = dict(res)
    for k in ("hq", "yr", "own", "tk", "parent", "site"):
        if f.get(k) != "confirmed":
            out[k] = None
    if out.get("hq") is None:
        out["lat"] = out["lon"] = None
    good = {int(x["i"]) for x in (v.get("links") or []) if isinstance(x, dict) and x.get("ok") is True and str(x.get("i", "")).isdigit()}
    out["links"] = [l for i, l in enumerate(res.get("links") or []) if i in good]
    out["sources"] = srcs
    out["evidence"] = [u for u in (v.get("evidence") or []) if str(u).startswith("http")][:4]
    return True, out, str(v.get("notes") or "")[:160]


SITE_Q = """Find the official website of this company, so its logo can be shown next to its name. Use web search.
Only the company's own site: never a news site, directory, LinkedIn, Crunchbase or Wikipedia. If it was acquired and its old
site now redirects, give the domain it redirects to. If you can't confirm one, say null.
Reply JSON only: {"site": "domain.com" or null}"""


def backfill_sites(limit=8):
    """Companies already on the map without a website on file get one looked up (a few per run), so media.py can fetch
    their logo. Results go to data/sites.json; an empty value means 'looked, none found' so it isn't retried."""
    if not API_KEY:
        return
    seed, mp = load("seed.json", {}), load("players.json", {"players": []})
    sites, have = load("sites.json", {}), dict(seed.get("psite") or {})
    allp = [p for p in seed.get("players", []) + mp.get("players", []) if not p.get("pending")]
    todo = [p for p in allp if p["id"] not in have and not p.get("site") and p["id"] not in sites][:limit]
    for p in todo:
        try:
            res = parse_json(ask(f"Company: {p['n']}\nAlso known as: {', '.join(p.get('al') or [])}\nWhat it does: {p.get('s') or ''}\nHQ: {p.get('hq') or ''}",
                                 system=SITE_Q, max_tokens=400)) or {}
        except Exception as e:
            print(f"  site lookup failed for {p['n']}: {e}", file=sys.stderr); continue
        site = re.sub(r"^https?://(www\.)?", "", str(res.get("site") or "")).strip("/ ").split("/")[0].lower()
        sites[p["id"]] = site if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", site) else ""
        print(f"  site for {p['n']}: {sites[p['id']] or 'none found'}")
    if todo:
        save("sites.json", sites)


def apply_profile(p, res, byname, edges, mp, today):
    """Write a verified profile onto a player and add its verified links. Returns the number of links added."""
    p.update({k: res[k] for k in ("n", "own", "tk", "hq", "yr", "s", "site") if res.get(k)})
    if res.get("realm") in REALMS:
        p["realm"] = res["realm"]
    p["al"] = sorted(set((p.get("al") or []) + [a for a in (res.get("al") or []) + (res.get("former_names") or []) if isinstance(a, str)]))[:8]
    if isinstance(res.get("lat"), (int, float)) and isinstance(res.get("lon"), (int, float)) and -90 <= res["lat"] <= 90 and -180 <= res["lon"] <= 180:
        p["geo"] = [round(res["lon"], 3), round(res["lat"], 3)]
    par = byname.get((res.get("parent") or "").lower()) or byname.get(norm(res.get("parent")))
    if par and par != p["id"]:
        p["parent"] = par
    added = 0
    for l in res.get("links") or []:
        o = byname.get((l.get("other") or "").lower()) or byname.get(norm(l.get("other")))
        if not o or o == p["id"] or l.get("k") not in KINDS or not str(l.get("url") or "").startswith("http"):
            continue                      # only proven links to companies already on the map
        a, b = (p["id"], o) if l.get("dir") != "other>this" else (o, p["id"])
        if any(e["a"] == a and e["b"] == b and e["k"] == l["k"] for e in edges):
            continue
        e = {"a": a, "b": b, "k": l["k"], "y": l.get("y"), "t": (l.get("t") or "")[:120], "url": l["url"], "story": p.get("story")}
        mp["edges"].append(e); edges.append(e); added += 1
    srcs = [x["url"] for x in res.get("sources") or [] if isinstance(x, dict) and str(x.get("url") or "").startswith("http")]
    if srcs:
        p["src"] = srcs[0]; p["srcs"] = srcs[:3]
    p.update({"enriched": today, "pending": False, "added": p.get("added") or today})
    mp.setdefault("checks", {})[p["id"]] = today
    byname[p["n"].lower()] = p["id"]; byname[norm(p["n"])] = p["id"]
    return added


def main():
    if not API_KEY:
        print("players: no API key"); return
    limit = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 6
    seed, mp = load("seed.json", {}), load("players.json", {"players": [], "edges": []})
    news = {s["id"]: s for s in load("news.json", [])}
    known = [p for p in seed.get("players", []) + mp["players"] if not p.get("pending")]
    byname = {}
    for p in known:
        for nm in [p["n"]] + (p.get("al") or []):
            byname[nm.lower()] = p["id"]; byname[norm(nm)] = p["id"]
    todo = [p for p in mp["players"] if p.get("auto") and not p.get("enriched")][:limit]
    if not todo:
        print("players: nothing new to research"); return
    known_list = "; ".join(sorted({p["n"] for p in known}))
    today = dt.date.today().isoformat()
    edges = seed.get("edges", []) + mp["edges"]
    for p in todo:
        st = news.get(p.get("story")) or {}
        user = (f"Company: {p['n']}\nSeen in: {st.get('title') or p.get('s') or ''}\n{st.get('sum') or ''}\nSource: {p.get('src') or st.get('url') or ''}\n\n"
                f"REALMS: {', '.join(REALMS)}\n\nKNOWN (companies already on the map): {known_list}")
        try:
            res = parse_json(ask(user, strict=True, searches=6))
        except Exception as e:
            print(f"  research failed for {p['n']}: {e}", file=sys.stderr); continue
        if not isinstance(res, dict):
            continue
        if not res.get("is_player"):
            mp["players"] = [x for x in mp["players"] if x["id"] != p["id"]]
            mp["edges"] = [e for e in mp["edges"] if p["id"] not in (e["a"], e["b"])]
            print(f"  dropped (not a parcel player): {p['n']}"); continue
        ok, res, why = verify_profile(res, known_list)
        if not ok:                                  # not proven: it stays off the map and waits in the review list
            mp["players"] = [x for x in mp["players"] if x["id"] != p["id"]]
            mp["edges"] = [e for e in mp["edges"] if p["id"] not in (e["a"], e["b"])]
            review_add("new player", p["n"], why, [x.get("url") for x in res.get("sources") or [] if isinstance(x, dict)] or [p.get("src")])
            print(f"  held back (not verified): {p['n']}: {why}"); continue
        added = apply_profile(p, res, byname, edges, mp, today)
        print(f"  researched {p['n']}: {p.get('realm')}, {p.get('hq')}, {added} links")
    save("players.json", mp)


# ---------------------------------------------------------------- family trees: keep ownership current
FAMILY_ROOTS = ["ups", "fedex", "amazon", "usps", "dhl", "walmart", "uber", "doordash", "instacart", "pitneybowes", "ontrac",
                "canadapost", "purolator", "ids", "laposte", "japanpost", "maersk", "cmacgm", "dsv", "xpo", "gxo", "rxo",
                "stord", "fdxfreight", "target", "shopify", "ryder", "jbhunt", "forwardair"]
FAMILY_DAYS = 7                       # each family is re-checked about once a week, one family per run

FAMILY_Q = """You keep the corporate family tree of a parcel and logistics company current for Parcel Pigeon's market map.
Use web search. Report ONLY ownership changes that happened (or were officially announced) AFTER the date given:
acquisitions that closed, sales that closed, spin-offs completed, units shut down or folded into another, deals agreed but not
closed, and brand-new MAJOR arms (an operating company, airline, freight or logistics division, retail network, tech or
capital unit). Ignore facilities, offices, drop-off points, products and service names, partnerships, rumors and minority stakes.
Every change needs the company's own announcement or a filing or established trade press, with its URL. Never guess.
Return JSON only:
{"changes": [{"unit": "company or arm name", "k": "bought|sold|spun|closed|pending|new_arm",
  "to": "new owner's name (for bought or sold) or null", "into": "company it was folded into, for closed, or null",
  "d": "YYYY-MM-DD", "role": "under 60 characters: what the unit does", "url": "source URL", "t": "one neutral sentence"}]}
Return {"changes": []} if nothing changed."""


def family_check(limit=1):
    """One family per run, each about weekly: ask what changed since it was last checked, and record each change as a
    'move' in data/players.json. The app applies moves on top of the researched trees, so a sale shows up in the seller's
    tree ("No longer part of"), the buyer's tree, the map lines and the company card at the same time."""
    if not API_KEY:
        return
    seed, mp = load("seed.json", {}), load("players.json", {"players": [], "edges": []})
    known = [p for p in seed.get("players", []) + mp["players"] if not p.get("pending")]
    byid = {p["id"]: p for p in known}
    for m in sorted(mp.get("moves") or [], key=lambda m: m.get("d") or ""):   # earlier changes already applied in the app
        if m["id"] in byid and m["k"] != "pending":
            byid[m["id"]]["parent"] = m.get("parent")
    byname = {}
    for p in known:
        for nm in [p["n"]] + (p.get("al") or []):
            byname[str(nm).lower()] = p["id"]
    st = load("family_watch.json", {})
    today = dt.date.today()
    due = [r for r in FAMILY_ROOTS if r in byid and (today - dt.date.fromisoformat(st.get(r, "2026-10-01"))).days >= FAMILY_DAYS]
    due.sort(key=lambda r: st.get(r, "2026-10-01"))
    moves = mp.setdefault("moves", [])
    for root in due[:limit]:
        kids = [p for p in known if p.get("parent") == root]
        tree = "\n".join(f"- {p['n']}" + "".join(f"\n  - {q['n']}" for q in known if q.get("parent") == p["id"]) for p in kids)
        since = st.get(root, "2026-10-01")
        try:
            res = parse_json(ask(f"Company: {byid[root]['n']}\nChanges since: {since}\nIts arms on file today:\n{tree or '(none)'}", system=FAMILY_Q, max_tokens=1800)) or {}
        except Exception as e:
            print(f"  family check failed for {root}: {e}", file=sys.stderr); continue
        st[root] = today.isoformat()
        n = 0
        for c in res.get("changes") or []:
            if not isinstance(c, dict) or c.get("k") not in ("bought", "sold", "spun", "closed", "pending", "new_arm"):
                continue
            if not str(c.get("url") or "").startswith("http") or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(c.get("d") or "")) or c["d"] < since:
                continue
            uid = byname.get(str(c.get("unit") or "").lower())
            to = byname.get(str(c.get("to") or "").lower()) if c.get("to") else None
            into = byname.get(str(c.get("into") or "").lower()) if c.get("into") else None
            k = c["k"]
            if not uid:
                if k not in ("bought", "new_arm", "pending"):
                    continue                              # a unit we never had can't leave the family
                name = str(c.get("unit") or "").strip()[:60]
                if not name:
                    continue
                uid = re.sub(r"[^a-z0-9]+", "", name.lower())[:14] or "co"
                while uid in byid:
                    uid += "x"
                p = {"id": uid, "n": name, "realm": byid[root].get("realm") if k == "new_arm" else "3pl", "own": "sub", "tk": None,
                     "parent": root if k != "pending" else None, "hq": None, "yr": None, "s": (c.get("role") or "")[:120], "role": (c.get("role") or "")[:60],
                     "al": [], "src": c["url"], "auto": True, "added": today.isoformat()}
                mp["players"].append(p); known.append(p); byid[uid] = p; byname[name.lower()] = uid
            if any(m["id"] == uid and m["k"] == k and m.get("d") == c["d"] for m in moves):
                continue
            frm = byid[uid].get("parent") if k in ("sold", "spun", "closed") else None
            par = root if k in ("bought", "new_arm") else to if k == "sold" else None
            moves.append({"id": uid, "k": k, "parent": par, "from": frm or (root if k in ("sold", "spun", "closed") else None),
                          "pend": root if k == "pending" else None, "into": into, "d": c["d"], "url": c["url"],
                          "t": str(c.get("t") or "")[:160], "role": (c.get("role") or "")[:60] or None})
            if k != "pending" and uid in byid:
                byid[uid]["parent"] = par
            n += 1
        print(f"  family check: {byid[root]['n']} ({n} change{'s' if n != 1 else ''} since {since})")
    save("family_watch.json", st)
    save("players.json", mp)


if __name__ == "__main__":
    main()
