"""One-off, deterministic clean-up of data/deals.json and data/players.json (October 2026): one deal card per transaction.
No model calls; running it again changes nothing.

  python3 tools/repair_deals.py          # writes data/deals.json and data/players.json
  python3 tools/repair_deals.py --dry    # prints what it would do

Until now the pipeline matched a story's deal to a tracked one only by exact buyer and target strings, and only within
data/deals.json, so a later step in a built-in deal (MAK terminating the UniUni purchase agreement) opened a second card,
marked Announced. Every deals.json entry that describes a deal already tracked is folded into one update entry keyed by
the tracked deal's own buyer and target (the app lays it over the built-in card), with the story added to the deal's
timeline. The UniUni termination then gets its full record from the sources, and the market map loses the duplicate
"UniUni (Uni Express Inc.)" company and the ownership line the terminated deal drew from MAK."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from common import load, save, deal_same, deal_overlay, deal_advance    # noqa: E402

# deals.json entries whose buyer and target were written differently from the tracked deal than loose matching can see
ALIAS = {("WWEX Group", "Auctane"): ("Thoma Bravo", "WWEX Group (combined with Auctane)")}

# The UniUni go-public deal, from its sources: the May 15 announcement (story 60, GlobeNewswire / Fasken), MAK's Sept. 24
# breach notice (story nr4f8ee6, BetaKit; the 15-business-day cure period ran to Oct. 19) and MAK's Oct. 20 termination
# notice (story afb6fa67940a7, MAK's release via GlobeNewswire / The Manila Times).
UNIUNI = {
    "status": "Terminated", "ended": "2026-10-20", "d": "2026-10-20", "checked": "2026-10-20",
    "latest": "MAK terminated the purchase agreement on Oct. 20, 2026; the go-public deal will not proceed.",
    "sum": "UniUni agreed on May 15, 2026 to go public through a reverse takeover by MAK Acquisition Corp. at about US$1.0 billion. "
           "MAK sent a notice of material breach on Sept. 24, 2026 and terminated the purchase agreement on Oct. 20, 2026, so the deal will not proceed.",
    "note": "MAK said UniUni breached an interim covenant capping its cumulative pre-tax loss and did not cure it before the "
            "cure period expired Oct. 19. MAK is withdrawing its preliminary prospectus and will keep looking for a qualifying acquisition.",
    "updates": [
        {"d": "2026-05-15", "t": "UniUni agrees to go public through MAK Acquisition at about $1 billion", "story": "60"},
        {"d": "2026-09-24", "t": "MAK sends UniUni a notice of material breach, starting a 15-business-day cure period", "story": "nr4f8ee6"},
        {"d": "2026-10-20", "t": "MAK terminates the purchase agreement; the go-public deal will not proceed", "story": "afb6fa67940a7"}],
    "srcs": [
        {"src": "MAK Acquisition (GlobeNewswire, via The Manila Times)", "url": "https://www.manilatimes.net/2026/10/20/tmt-newswire/globenewswire/mak-acquisition-terminates-purchase-agreement-with-uniuni/2449899"},
        {"src": "BetaKit (breach notice)", "url": "https://betakit.com/?p=410314"}],
}


def story_view(x, stories):
    """A deals.json entry seen as the story that reported it (title and date from the story when it is on the site)."""
    n = stories.get(x.get("story")) or {}
    return {"id": x.get("story"), "date": n.get("date") or x.get("checked") or x.get("d"), "title": n.get("title") or x.get("title"),
            "srcs": x.get("srcs") or n.get("srcs") or [], "url": x.get("url")}


def fold(seed, dl, stories):
    """deals.json with every duplicate of a tracked deal folded into one entry keyed by that deal. Returns (deals, log)."""
    out, log = [], []
    for x in reversed(dl):                                      # oldest first, so later steps land on top of earlier ones
        key = ALIAS.get((x.get("buyer"), x.get("target")))
        base = next((s for s in seed if (s.get("buyer"), s.get("target")) == key or deal_same(s, x)), None)
        if base is None:
            prior = next((o for o in out if deal_same(o, x)), None)
            if prior is None:
                out.append(x)
                continue
            ov = deal_advance(prior, x, story_view(x, stories))
            for k in ("buyer", "target", "title", "ann", "story"):
                ov.pop(k, None)
            prior.update(ov)
            log.append(f"folded \"{x.get('title')}\" into deals.json deal \"{prior.get('title')}\"")
            continue
        i = next((i for i, o in enumerate(out) if (o.get("buyer"), o.get("target")) == (base["buyer"], base["target"])), None)
        if (x.get("buyer"), x.get("target")) == (base["buyer"], base["target"]):
            if i is None:
                out.append(x)
            else:
                out[i] = deal_overlay(out[i], x)
            continue
        cur = deal_overlay(base, out[i]) if i is not None else base
        ov = deal_advance(cur, x, story_view(x, stories))
        log.append(f"folded \"{x.get('title')}\" ({x.get('buyer')} / {x.get('target')}, {x.get('status')}) into built-in deal "
                   f"\"{base.get('title')}\" -> {ov.get('status')}")
        if i is None:
            out.append(ov)
        else:
            out[i] = ov
    return list(reversed(out)), log


def repair_map(mp):
    """The termination story added "UniUni (Uni Express Inc.)" as a second UniUni and drew MAK -> UniUni as an acquisition.
    Its links move to the built-in UniUni (uniuni); the acquisition line goes, since the deal was terminated."""
    log, dup, real = [], "uniuniuniexpre", "uniuni"
    if any(p.get("id") == dup for p in mp.get("players", [])):
        mp["players"] = [p for p in mp["players"] if p.get("id") != dup]
        log.append("removed duplicate company uniuniuniexpre (UniUni (Uni Express Inc.)); its links now point at uniuni")
    seed_edges = load("seed.json", {}).get("edges", [])
    kept = []
    for e in mp.get("edges", []):
        e = dict(e, a=real if e.get("a") == dup else e.get("a"), b=real if e.get("b") == dup else e.get("b"))
        if {e["a"], e["b"]} == {"mak", real} and e.get("k") in ("acquired", "merged", "owns"):
            log.append(f"removed ownership line {e['a']} -> {e['b']} ({e.get('t')}): the deal was terminated")
            continue
        if any(x["a"] == e["a"] and x["b"] == e["b"] and x["k"] == e["k"] and str(x.get("y")) == str(e.get("y")) for x in seed_edges + kept):
            continue
        kept.append(e)
    mp["edges"] = kept
    mp["moves"] = [m for m in mp.get("moves", []) if not (m.get("id") in (real, dup) and "mak" in (m.get("pend"), m.get("parent")))]
    for k in ("checks", "facts"):
        if isinstance(mp.get(k), dict) and dup in mp[k]:
            mp[k].setdefault(real, mp[k][dup]); del mp[k][dup]
    return mp, log


def main(dry=False):
    seed = load("seed.json", {})
    stories = {s["id"]: s for s in seed.get("news", []) + load("news.json", []) if s.get("id")}
    dl, log = fold(seed.get("deals", []), load("deals.json", []), stories)
    for x in dl:
        if (x.get("buyer"), x.get("target")) == ("MAK Acquisition Corp. (SPAC)", "UniUni"):
            x.update({k: v for k, v in UNIUNI.items() if k != "srcs"})
            by_url = {s["url"]: s for s in x.get("srcs") or []}
            by_url.update({s["url"]: s for s in UNIUNI["srcs"]})        # same link, clearer label
            x["srcs"] = list(by_url.values())
    mp, mlog = repair_map(load("players.json", {"players": [], "edges": []}))
    for line in log + mlog:
        print(line)
    if not dry:
        save("deals.json", dl)
        save("players.json", mp)
    return dl


if __name__ == "__main__":
    main("--dry" in sys.argv)
