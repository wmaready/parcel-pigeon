"""New players for the market map.

Companies first show up in the news (a deal, a partnership, a new carrier). They're added as candidates; this step
researches each one (web search through the Claude API when available), confirms it's really part of the parcel world,
fills in its profile (what it does, HQ, owner, website), and links it ONLY to companies already on the map, each link
with a source. Candidates that aren't parcel players are dropped. Newly confirmed players get a "New" badge in the app
and a phone alert (alerts.py, Deals topic).

Usage: python players.py [--max 6]
Also keeps family trees current (family_check, one company per run, about weekly each).
"""
import datetime as dt, json, os, re, sys
import requests
from common import load, save, parse_json, API_KEY, MODEL_WRITE, cached_system, track

REALMS = ["national", "regional", "gig", "retail", "3pl", "global", "software", "cold", "auto", "capital"]
KINDS = {"owns", "acquired", "invested", "partner", "merged", "sold", "spun"}

RESEARCH = """You research companies for Parcel Pigeon's market map of the small parcel industry (carriers, couriers, last-mile and
gig delivery, 3PLs and fulfillment, shipping and returns software, retailers' delivery networks, drones and robots, cold chain,
and the investors behind them). Use web search. Be strict: only facts you found in reliable sources (company site, filings,
press releases, established trade press). Never guess.

Return JSON only:
{"is_player": true|false,              // false if it isn't part of parcel shipping or delivery (law firm, generic retailer, etc.)
 "n": "official company name", "al": ["other names"],
 "realm": one of REALMS,
 "own": "public"|"private"|"pe"|"sub", "tk": "ticker or null", "parent": "parent company name or null",
 "hq": "City, ST, USA" or "City, Country", "lat": number, "lon": number,   // HQ city coordinates
 "yr": "founding year or null", "site": "domain.com or null",
 "s": "one neutral sentence: what the company does in parcel",
 "links": [{"other": "a name EXACTLY as written in the KNOWN list", "k": "owns|acquired|invested|partner|merged|sold|spun",
            "dir": "this>other" or "other>this", "y": "year or null", "t": "short label", "url": "source URL"}]}
Links only to companies in the KNOWN list, only real announced relationships, each with the URL where you found it.
Set "is_player" false for small non-U.S. carriers and couriers with no U.S. operations or U.S. customers (a local courier in
one foreign country); keep national posts, global carriers and logistics groups, and any company that serves U.S. shippers."""


def ask(user, use_search=True, system=None, max_tokens=2500):
    body = {"model": MODEL_WRITE, "max_tokens": max_tokens, "system": cached_system(system or RESEARCH), "messages": [{"role": "user", "content": user}]}
    if use_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, json=body,
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    if r.status_code >= 400 and use_search:
        print(f"  web search unavailable ({r.status_code}); researching from the story only", file=sys.stderr)
        return ask(user, use_search=False, system=system, max_tokens=max_tokens)
    r.raise_for_status()
    j = r.json(); track(j)
    return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")


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
            byname[nm.lower()] = p["id"]
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
            res = parse_json(ask(user))
        except Exception as e:
            print(f"  research failed for {p['n']}: {e}", file=sys.stderr); continue
        if not isinstance(res, dict):
            continue
        if not res.get("is_player"):
            mp["players"] = [x for x in mp["players"] if x["id"] != p["id"]]
            mp["edges"] = [e for e in mp["edges"] if p["id"] not in (e["a"], e["b"])]
            print(f"  dropped (not a parcel player): {p['n']}"); continue
        p.update({k: res[k] for k in ("n", "own", "tk", "hq", "yr", "s", "site") if res.get(k)})
        if res.get("realm") in REALMS:
            p["realm"] = res["realm"]
        p["al"] = sorted(set((p.get("al") or []) + [a for a in res.get("al") or [] if isinstance(a, str)]))[:6]
        if isinstance(res.get("lat"), (int, float)) and isinstance(res.get("lon"), (int, float)):
            p["geo"] = [round(res["lon"], 3), round(res["lat"], 3)]
        par = byname.get((res.get("parent") or "").lower())
        if par and par != p["id"]:
            p["parent"] = par
        added = 0
        for l in res.get("links") or []:
            o = byname.get((l.get("other") or "").lower())
            if not o or o == p["id"] or l.get("k") not in KINDS or not str(l.get("url") or "").startswith("http"):
                continue                      # only proven links to companies already on the map
            a, b = (p["id"], o) if l.get("dir") != "other>this" else (o, p["id"])
            if any(e["a"] == a and e["b"] == b and e["k"] == l["k"] for e in edges):
                continue
            e = {"a": a, "b": b, "k": l["k"], "y": l.get("y"), "t": (l.get("t") or "")[:120], "url": l["url"], "story": p.get("story")}
            mp["edges"].append(e); edges.append(e); added += 1
        p.update({"enriched": today, "pending": False, "added": p.get("added") or today})
        byname[p["n"].lower()] = p["id"]
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
