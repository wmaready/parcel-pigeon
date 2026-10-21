"""One-off, deterministic clean-up of data/threads.json (October 2026): storylines the pipeline had split in two are
folded into one. No model calls; running it again changes nothing.

  python3 tools/merge_storylines.py          # writes data/threads.json
  python3 tools/merge_storylines.py --dry    # prints what it would do

Each merge keeps every story id that is still on the site, Coop's step lines for those stories, and the newest
"where it stands". Old keys are kept in "was", so the pipeline files later items sent to an old key into the merged
storyline. Story records in data/news.json are not touched: the app finds a story's storyline from threads.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from common import load, save          # noqa: E402
from news import merge_threads         # noqa: E402

PLAN = [
    # UniUni: its funding rounds, the MAK go-public deal (breach notice, then termination) and the Tacoma delivery
    # complaints were two one-story storylines plus four built-in stories with no storyline. One company, one saga.
    {"into": "uniuni", "from": ["uniuni-mak-acquisition", "uniuni-delivery-complaints"], "add": ["h521", "61", "60", "nr4f8ee6"],
     "co": "UniUni", "n": "UniUni: funding, SPAC deal and complaints",
     "s": "MAK terminated the UniUni purchase agreement on Oct. 20, 2026, so the planned go-public deal will not proceed; "
          "Tacoma residents' delivery complaints have also gone to the Washington Attorney General's office."},
    # Royal Mail and the CWU: the DM26 rollout pause and the staffing-crisis summit call are the same union dispute
    {"into": "royal-mail-cwu-dispute", "from": ["royal-mail-dm26"], "co": "Royal Mail"},
    # the next chapter of the low-value import rules after de minimis ended (the app already showed them together)
    {"into": "de-minimis", "from": ["cbp-low-value-import-filing"], "n": "End of de minimis and low-value import rules"},
    # an analysis of UPS's parcel pivot, which the app already folded into the UPS-Amazon cutback storyline
    {"into": "ups-amazon-glide-down", "from": ["ups-parcel-pivot"], "co": "UPS"},
]


def run(threads, dates, plan=PLAN):
    log = []
    for m in plan:
        dst = m["into"]
        add = [i for i in m.get("add", []) if i in dates]
        srcs = [s for s in m["from"] if s in threads and s != dst]
        if not srcs and not (dst in threads and set(add) - set(threads[dst].get("ids", []))) and dst in threads:
            continue        # already done
        if dst not in threads and srcs:
            # the merged storyline starts from the first source, under its new key
            threads[dst] = threads.pop(srcs[0])
            threads[dst]["was"] = sorted(set(threads[dst].get("was") or []) | {srcs[0]})
            srcs = srcs[1:]
        for s in srcs:
            merge_threads(threads, s, dst, dates)
        merge_threads(threads, dst, dst, dates, name=m.get("n"), status=m.get("s"), co=m.get("co"), add=add)
        log.append(f"{dst}: {len(threads[dst]['ids'])} stories (from {', '.join(m['from'])}{' + ' + ', '.join(add) if add else ''})")
    return log


if __name__ == "__main__":
    threads = load("threads.json", {})
    pool = load("seed.json", {}).get("news", []) + load("news.json", [])
    dates = {s["id"]: s.get("date") for s in pool if s.get("id")}
    log = run(threads, dates)
    print("\n".join(log) or "nothing to merge")
    if log and "--dry" not in sys.argv:
        save("threads.json", threads)
