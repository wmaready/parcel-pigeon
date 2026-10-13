"""The vetted sweep: grow the market map's knowledge base without letting anything unproven onto it.

Three jobs, each capped by a daily call budget (PW_SWEEP_CALLS, default 40) so cost can never run away:

  discover  Walks a fixed list of market segments (regional carriers, lockers, returns, shipping software, drones, cold chain,
            investors, ...). For each it asks, with web search, which companies are missing from the map. New names go to a queue.
  vet       Takes names off the queue. Each is researched (web search, at least two different websites), then checked a second time
            by a separate search-backed pass that tries to prove the profile wrong (players.verify_profile). Only what survives
            goes on the map; fields and links it couldn't confirm are dropped. Anything that fails waits in data/sweep_review.json.
  status    Re-checks EVERY company on the map on a rolling cycle (a few per call): renamed, acquired, merged, sold, shut down.
            A change is applied only with two sources on different websites and a believable date; otherwise it waits for review.
            Renames keep the old name as an alias, so search and news matching keep working.

Usage: python sweep.py [--discover N] [--vet N] [--status N] [--calls N]
"""
import datetime as dt, json, re, sys
import players as P
from common import load, save, parse_json, API_KEY

STATUS_DAYS = 45           # every company is re-checked about every six weeks
REDISCOVER_DAYS = 60       # every segment is searched again about every two months
BATCH = 6                  # companies per status call
PRUNE_IDS = {"westbengalpost"}   # a regional office of a national post is not a separate player

SEGMENTS = [
    ("regional", "U.S. regional parcel carriers and last-mile / final-mile delivery companies that serve e-commerce shippers (ground, same-day, next-day)"),
    ("regional", "same-day courier networks, delivery-management and dispatch platforms, and white-label delivery-as-a-service companies in the U.S."),
    ("regional", "cross-border e-commerce parcel carriers, consolidators and USPS-injection / postal-access providers that move parcels into and within the U.S."),
    ("regional", "parcel lockers, pickup and drop-off access-point networks, and returns drop-off networks in the U.S."),
    ("gig", "gig and crowdsourced delivery platforms and drivers' marketplaces used for package and grocery delivery in the U.S."),
    ("software", "multi-carrier shipping software, rate-shopping tools and shipping API platforms used by U.S. e-commerce shippers"),
    ("software", "returns management, reverse-logistics and returns-label companies serving U.S. retailers"),
    ("software", "delivery tracking, post-purchase experience, address validation, delivery-routing and last-mile optimization software"),
    ("software", "parcel sortation, warehouse automation and parcel-handling hardware or robotics vendors serving carriers and fulfillment centers"),
    ("3pl", "national and regional e-commerce fulfillment companies and 3PLs in the U.S."),
    ("3pl", "freight, LTL and truckload carriers that now offer parcel, heavy-parcel, big-and-bulky or final-mile delivery in the U.S."),
    ("3pl", "customs brokers, duty-and-tax and cross-border e-commerce enablers handling U.S. imports of parcels"),
    ("global", "international postal operators and global express or cross-border carriers that serve U.S. shippers"),
    ("global", "air cargo and ocean carriers and freight forwarders that feed parcel and e-commerce networks"),
    ("retail", "marketplaces and retailers that run their own delivery, fulfillment or shipping programs and so shape parcel volume in the U.S."),
    ("cold", "cold-chain, healthcare, pharma and specialty courier and logistics companies moving temperature-controlled parcels"),
    ("auto", "drone, autonomous-vehicle and sidewalk-robot delivery companies operating or testing in the U.S."),
    ("capital", "private equity firms, investors and lenders that own or recently bought U.S. parcel, last-mile and logistics companies"),
    ("software", "mailing, mail-presort and postage-technology companies connected to USPS parcels"),
    ("regional", "Canadian and Mexican parcel carriers and couriers with cross-border service into the U.S."),
]

DISCOVER = """You help keep Parcel Pigeon's market map of the U.S. small-parcel industry complete. Use web search.
Given one market segment and the list of companies already on the map, find companies in that segment that are MISSING from
the map and matter to U.S. parcel shippers or carriers. Rules:
- Only real companies you found on the web today, each with the URL of a page about it. Never guess or invent a name.
- Skip anything already on the map (under any name, including former names), tiny local businesses, companies with no U.S.
  operations or U.S. customers, shut-down companies, and parcel-spend consultancies and invoice-audit firms.
- Prefer companies with real scale, funding, a national footprint, or a role in recent deals; at most 10, best first.
Reply JSON only: {"candidates": [{"n": "official name", "what": "one neutral sentence on what it does in parcel", "url": "page about it", "us": true|false}]}"""

STATUS_Q = """You keep Parcel Pigeon's market map of the parcel industry current. For EACH company listed (id | name | what we have on file), use
web search to find out whether anything has changed that the file doesn't show: renamed or rebranded; acquired or merged
(by whom); a unit sold or spun off; shut down, bankrupt or ceased operating. Only report what is true and sourced today.
Every change needs the company's own announcement, a filing, or established trade press, AND a second source on a different website.
Do not report rumors, partnerships, products, minority stakes, or things already on file. Reply JSON only:
{"results": [{"id": "the id given", "answered": true|false,    // false if you couldn't research this one
  "changes": [{"k": "renamed|bought|sold|spun|closed|merged", "new_name": "new name, for renamed, else null",
     "to": "acquirer or new owner, for bought/sold/merged, else null", "d": "YYYY-MM-DD effective or announced date",
     "url": "source", "url2": "second source on a different website", "t": "one neutral sentence"}]}]}"""


def today():
    return dt.date.today()


def budget(st, want):
    """Calls left today. The sweep never spends past PW_SWEEP_CALLS in a UTC day."""
    import os
    cap = int(os.environ.get("PW_SWEEP_CALLS") or 40)
    if st.get("day") != today().isoformat():
        st["day"], st["calls"] = today().isoformat(), 0
    return max(0, min(want, cap - st["calls"]))


def spend(st, n=1):
    st["calls"] = st.get("calls", 0) + n


def names(mp, seed):
    """Every published company, with the names it answers to (current, former, and any rename on record)."""
    known = [p for p in seed.get("players", []) + mp["players"] if not p.get("pending")]
    byid = {p["id"]: p for p in known}
    for m in sorted(mp.get("moves") or [], key=lambda m: m.get("d") or ""):
        p = byid.get(m.get("id"))
        if not p:
            continue
        if m["k"] == "renamed" and m.get("new"):
            if m.get("old") and m["old"] not in (p.get("al") or []):
                p["al"] = (p.get("al") or []) + [m["old"]]
            p["n"] = m["new"]
        elif m["k"] != "pending":
            p["parent"] = m.get("parent")
    byname = {}
    for p in known:
        for nm in [p["n"]] + (p.get("al") or []):
            byname[str(nm).lower()] = p["id"]; byname[P.norm(nm)] = p["id"]
    return known, byid, byname


def prune(mp):
    n = len(mp["players"])
    mp["players"] = [p for p in mp["players"] if p["id"] not in PRUNE_IDS]
    mp["edges"] = [e for e in mp["edges"] if e["a"] not in PRUNE_IDS and e["b"] not in PRUNE_IDS]
    mp["moves"] = [m for m in mp.get("moves") or [] if m.get("id") not in PRUNE_IDS]
    for i in PRUNE_IDS:
        (mp.get("checks") or {}).pop(i, None)
    return n - len(mp["players"])


# ---------------------------------------------------------------- discover
def discover(st, mp, seed, segs):
    known, byid, byname = names(mp, seed)
    seen = {P.norm(k) for k in byname} | {P.norm(x["n"]) for x in st.get("queue", [])} | set(st.get("rej", {}))
    seen |= {P.norm(x.get("n")) for x in load("sweep_review.json", [])}
    last = st.setdefault("seg", {})
    order = sorted(range(len(SEGMENTS)), key=lambda i: last.get(str(i), ""))
    due = [i for i in order if not last.get(str(i)) or (today() - dt.date.fromisoformat(last[str(i)])).days >= REDISCOVER_DAYS]
    klist = "; ".join(sorted({p["n"] for p in known}))
    found = 0
    for i in due[:budget(st, segs)]:
        realm, q = SEGMENTS[i]
        try:
            res = parse_json(P.ask(f"Segment: {q}\n\nALREADY ON THE MAP: {klist}", system=DISCOVER, max_tokens=1800, strict=True, searches=6)) or {}
        except Exception as e:
            print(f"  discover failed for segment {i}: {e}", file=sys.stderr); spend(st); continue
        spend(st)
        if P.ask.searches < 1:
            print(f"  segment {i}: no search ran, ignored", file=sys.stderr); continue
        last[str(i)] = today().isoformat()
        n = 0
        for c in (res.get("candidates") or [])[:10]:
            if not isinstance(c, dict) or not c.get("n") or not str(c.get("url") or "").startswith("http") or c.get("us") is False:
                continue
            k = P.norm(c["n"])
            if not k or k in seen or P.BLOCK.search(c["n"]):
                continue
            seen.add(k)
            st.setdefault("queue", []).append({"n": str(c["n"]).strip()[:80], "what": str(c.get("what") or "")[:200], "url": c["url"], "realm": realm, "seg": i, "found": today().isoformat()})
            n += 1
        found += n
        print(f"  discover: {q[:70]}...: {n} new name{'s' if n != 1 else ''}")
    return found


# ---------------------------------------------------------------- vet
def vet(st, mp, seed, count):
    known, byid, byname = names(mp, seed)
    klist = "; ".join(sorted({p["n"] for p in known}))
    edges = seed.get("edges", []) + mp["edges"]
    done = 0
    for c in list(st.get("queue", []))[:count]:
        if budget(st, 2) < 2:
            print("  vet: out of calls for today"); break
        st["queue"].remove(c)
        k = P.norm(c["n"])
        user = (f"Company: {c['n']}\nSeen at: {c.get('url')}\nWhat we know: {c.get('what')}\n\nREALMS: {', '.join(P.REALMS)}\n\n"
                f"KNOWN (companies already on the map): {klist}")
        try:
            res = parse_json(P.ask(user, strict=True, searches=6))
        except Exception as e:
            print(f"  research failed for {c['n']}: {e}", file=sys.stderr); spend(st)
            c["retry"] = c.get("retry", 0) + 1
            if c["retry"] < 3:
                st.setdefault("queue", []).append(c)       # a failed call isn't a verdict: try again on a later run
            continue
        spend(st)
        if not isinstance(res, dict) or P.ask.searches < 1:
            st.setdefault("rej", {})[k] = "no usable research"; continue
        if not res.get("is_player"):
            st.setdefault("rej", {})[k] = "not a parcel player"; print(f"  skipped (not a parcel player): {c['n']}"); continue
        try:
            ok, clean, why = P.verify_profile(res, klist)
        except Exception as e:
            print(f"  check failed for {c['n']}: {e}", file=sys.stderr); spend(st); continue
        spend(st)
        if not ok:
            st.setdefault("rej", {})[k] = why
            P.review_add("new player", c["n"], why, [x.get("url") for x in res.get("sources") or [] if isinstance(x, dict)] or [c.get("url")])
            print(f"  held back: {c['n']}: {why}"); continue
        if not clean.get("hq") or not isinstance(clean.get("lat"), (int, float)) or not isinstance(clean.get("lon"), (int, float)):
            why = "headquarters not confirmed, so it can't be placed on the map"
            st.setdefault("rej", {})[k] = why; P.review_add("new player", c["n"], why, [x.get("url") for x in clean.get("sources") or []]); print(f"  held back: {c['n']}: {why}"); continue
        if k in {P.norm(x["n"]) for x in mp["players"]} or P.norm(clean.get("n")) in byname:
            st.setdefault("rej", {})[k] = "already on the map"; continue
        pid = re.sub(r"[^a-z0-9]+", "", str(clean.get("n") or c["n"]).lower())[:14] or "co"
        while pid in byid:
            pid += "x"
        p = {"id": pid, "n": str(clean.get("n") or c["n"])[:80], "realm": c["realm"], "own": clean.get("own") or "private", "tk": None, "parent": None,
             "hq": None, "yr": None, "s": str(clean.get("s") or c["what"])[:260], "al": [], "auto": True, "seeded": True, "sweep": True}
        added = P.apply_profile(p, clean, byname, edges, mp, today().isoformat())
        if p.get("own") not in ("public", "private", "pe", "sub"):
            p["own"] = "private"
        mp["players"].append(p); known.append(p); byid[pid] = p
        byname[p["n"].lower()] = pid; byname[P.norm(p["n"])] = pid
        done += 1
        print(f"  added: {p['n']} ({p['realm']}, {p.get('hq') or 'HQ unconfirmed'}, {added} verified links)")
    return done


# ---------------------------------------------------------------- status: renamed, bought, sold, folded
def valid_date(d):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d or "")):
        return False
    try:
        t = dt.date.fromisoformat(d)
    except ValueError:
        return False
    return dt.date(2023, 1, 1) <= t <= today()


def apply_change(mp, byid, byname, st, p, c):
    """Apply one sourced change to company p as a dated 'move' (the app applies moves in date order). Returns a short
    description when applied, or None when it was held for review."""
    k = {"merged": "closed"}.get(c.get("k"), c.get("k"))
    u1, u2 = str(c.get("url") or ""), str(c.get("url2") or "")
    why = None
    if k not in ("renamed", "bought", "sold", "spun", "closed"):
        return None
    if not (u1.startswith("http") and u2.startswith("http") and P.domain(u1) != P.domain(u2)):
        why = "needs two sources on different websites"
    elif not valid_date(c.get("d")):
        why = "no believable date"
    moves = mp.setdefault("moves", [])
    to = byname.get(str(c.get("to") or "").lower()) or byname.get(P.norm(c.get("to"))) if c.get("to") else None
    if not why and k == "renamed":
        new = str(c.get("new_name") or "").strip()[:80]
        if not new or P.norm(new) == P.norm(p["n"]):
            return None
        if P.norm(new) in byname and byname[P.norm(new)] != p["id"]:
            why = f"new name '{new}' already belongs to another company"
    if not why and k in ("bought", "sold") and c.get("to") and not to:
        st.setdefault("queue", []).append({"n": str(c["to"])[:80], "what": f"new owner of {p['n']}", "url": u1, "realm": p.get("realm") or "3pl", "seg": -1, "found": today().isoformat()})
        why = f"new owner '{c['to']}' isn't on the map yet (queued for research)"
    if not why and k == "bought" and not to:
        why = "no acquirer named"
    if why:
        P.review_add("change", p["n"], f"{k}: {why}. {str(c.get('t') or '')[:120]}", [u1, u2])
        return None
    d = c["d"]
    if any(m["id"] == p["id"] and m["k"] == k and m.get("d") == d for m in moves):
        return None
    if k == "renamed":
        moves.append({"id": p["id"], "k": "renamed", "new": new, "old": p["n"], "d": d, "url": u1, "url2": u2, "t": str(c.get("t") or "")[:160]})
        if p["n"] not in (p.get("al") or []):
            p["al"] = (p.get("al") or []) + [p["n"]]
        p["n"] = new
        byname[new.lower()] = p["id"]; byname[P.norm(new)] = p["id"]
        return f"renamed to {new}"
    old = p.get("parent")
    par = to if k in ("bought", "sold") else None
    into = to if k == "closed" else None
    moves.append({"id": p["id"], "k": k, "parent": par, "from": old if old and old != par else None, "pend": None, "into": into,
                  "d": d, "url": u1, "url2": u2, "t": str(c.get("t") or "")[:160], "role": None})
    if k != "pending":
        p["parent"] = par
    return f"{k}" + (f" → {byid[to]['n']}" if to and to in byid else "")


def status(st, mp, seed, batches):
    known, byid, byname = names(mp, seed)
    chk = mp.setdefault("checks", {})
    cutoff = (today() - dt.timedelta(days=STATUS_DAYS)).isoformat()
    due = sorted([p for p in known if (chk.get(p["id"]) or "") < cutoff], key=lambda p: chk.get(p["id"]) or "")
    applied = held = answered = 0
    for b in range(min(batches, budget(st, batches))):
        grp = due[b * BATCH:(b + 1) * BATCH]
        if not grp:
            break
        lines = "\n".join(f"{p['id']} | {p['n']}{' (also ' + ', '.join(p['al'][:3]) + ')' if p.get('al') else ''} | "
                          f"{(byid.get(p.get('parent')) or {}).get('n') and 'part of ' + byid[p['parent']]['n'] + '; ' or ''}{p.get('hq') or ''}; {str(p.get('s') or '')[:120]}"
                          for p in grp)
        try:
            res = parse_json(P.ask(f"Today is {today().isoformat()}. Companies to check:\n{lines}", system=STATUS_Q, max_tokens=2500, strict=True, searches=6)) or {}
        except Exception as e:
            print(f"  status check failed: {e}", file=sys.stderr); spend(st); continue
        spend(st)
        if P.ask.searches < 1:
            continue
        for r in res.get("results") or []:
            p = byid.get(r.get("id")) if isinstance(r, dict) else None
            if not p or r.get("answered") is False:
                continue
            answered += 1
            chk[p["id"]] = today().isoformat()
            for c in r.get("changes") or []:
                if isinstance(c, dict):
                    out = apply_change(mp, byid, byname, st, p, c)
                    if out:
                        applied += 1; print(f"  change: {p['n']}: {out}")
                    else:
                        held += 1
    print(f"  status: {answered} companies re-checked, {applied} change{'s' if applied != 1 else ''} applied, {held} held for review")
    return applied


def main():
    if not API_KEY:
        print("sweep: no API key"); return
    arg = lambda k, d: int(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
    if "--calls" in sys.argv:
        import os
        os.environ["PW_SWEEP_CALLS"] = str(arg("--calls", 40))
    seed, mp = load("seed.json", {}), load("players.json", {"players": [], "edges": [], "moves": []})
    mp.setdefault("moves", []); mp.setdefault("checks", {})
    st = load("sweep_state.json", {})
    if prune(mp):
        print("  removed entries that aren't separate players")
    try:
        status(st, mp, seed, arg("--status", 1))       # existing companies first: they're what the map already claims
    except Exception as e:
        print("status check failed:", e, file=sys.stderr)
    try:
        vet(st, mp, seed, arg("--vet", 4))
    except Exception as e:
        print("vetting failed:", e, file=sys.stderr)
    try:
        if len(st.get("queue", [])) < arg("--vet", 4):    # keep the queue stocked, not hoarded
            discover(st, mp, seed, arg("--discover", 1))
    except Exception as e:
        print("discovery failed:", e, file=sys.stderr)
    save("players.json", mp)
    save("sweep_state.json", st)
    left = len(st.get("queue", []))
    never = sum(1 for p in seed.get("players", []) + mp["players"] if not mp["checks"].get(p["id"]))
    print(f"sweep: {st.get('calls', 0)} calls today, {left} names waiting to be vetted, {never} companies never re-checked, "
          f"{len(load('sweep_review.json', []))} items in review")


if __name__ == "__main__":
    main()
