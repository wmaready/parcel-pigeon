"""Priority watch: language and trigger changes in carrier rate guides, service guides, tariffs and surcharge documents.

Every run checks a rotating batch of documents from the library (data/docs.json + the app's built-in list in data/seed.json),
starting with the ones that matter most (rate guides, service guides, tariffs/terms, surcharge and peak notices).
For each document it keeps a text snapshot. When the text changes, Claude compares old and new and decides whether the change
is material: a new or removed surcharge, a changed trigger or threshold (weight, size, density/cube, zone, ZIP, dates),
changed amounts, or new contract language (e.g. "EZ", density or cube terms). Material changes become an Alert story in
data/news.json (category "Guide changes"). If no outlet has reported it yet, it is flagged first-to-report and you are notified
(GitHub issue + phone push if NTFY_TOPIC is set) so you can post first.

Usage: python docwatch.py [--batch 15]
"""
import datetime as dt, difflib, gzip, io, json, os, re, sys
from common import ROOT, load, save, h, get, claude, parse_json, MODEL_WRITE, clock_worthy
from scoop import is_covered, notify, ask, big
from changeaudit import audit, story_fields

SNAP = ROOT / "data" / "docwatch"
PRIORITY = {"Rate guide": 0, "Service guide": 0, "Terms": 1, "Surcharges & fees": 1, "Peak": 1, "GRI notice": 2,
            "Special program": 2, "Zones & DAS": 3, "Fuel": 4, "Regulatory filing": 4}
SKIP_TYPES = {"Market report"}

SYSTEM = """You compare two versions of the same carrier pricing or service document for Parcel Pigeon, a neutral parcel news app.
Report only MATERIAL changes a parcel shipper would care about: new, removed or renamed surcharges or fees; changed triggers or
thresholds (weight, length, girth, cubic size, density, dimensional divisor, zones, ZIP codes, residential/commercial rules,
dates and effective periods); changed amounts or percentages; new or changed contract or liability language (including terms
like "EZ", density, cube, minimums, eligibility); and services added or removed. Ignore formatting, page numbers, reordering,
typo fixes, copyright years and navigation text.
Return JSON: {"material": true|false, "title": "neutral headline under 14 words", "summary": "2-3 sentences: what changed,
old vs new wording or numbers, effective date if stated", "effect": "1 sentence on who it affects; no advice",
"imp": "up"|"down"|"watch"|"info", "lvl": 1|2|3, "changes": ["short bullet of each change, quoting the new wording"]}"""


def text_of(url):
    r = get(url, timeout=60)
    ctype = r.headers.get("content-type", "").lower()
    if url.lower().split("?")[0].endswith(".pdf") or "pdf" in ctype:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(r.content))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if "spreadsheet" in ctype or url.lower().split("?")[0].endswith((".xlsx", ".xls")):
        return None  # spreadsheets are ZIP lists and rate tables; the PDF twin is watched instead
    import trafilatura
    return trafilatura.extract(r.text, include_comments=False, include_tables=True) or ""


def norm(t):
    t = re.sub(r"[ \t]+", " ", t or "")
    t = re.sub(r"(?im)^\s*(page \d+( of \d+)?|\d+)\s*$", "", t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def snap_path(url):
    return SNAP / f"{h(url)}.txt.gz"


def main():
    batch = 15
    if "--batch" in sys.argv:
        batch = int(sys.argv[sys.argv.index("--batch") + 1])
    SNAP.mkdir(parents=True, exist_ok=True)
    seed = load("seed.json", {})
    docs = {d["u"]: d for d in seed.get("docs", []) + load("docs.json", []) if (d.get("u") or "").startswith("http")}
    docs = [d for d in docs.values() if d.get("t") not in SKIP_TYPES and d.get("cur", True) is not False]
    docs.sort(key=lambda d: (PRIORITY.get(d.get("t"), 5), d.get("c", ""), d.get("n", "")))
    idx = load("docwatch.json", {"cursor": 0, "docs": {}})
    cur = idx.get("cursor", 0) % max(1, len(docs))
    # priority documents (rate guides, service guides, terms) are checked every run; the rest rotate
    top = [d for d in docs if PRIORITY.get(d.get("t"), 5) == 0]
    rest = [d for d in docs if d not in top]
    picks = top + (rest[cur:] + rest[:cur])[:max(0, batch - len(top))]
    idx["cursor"] = cur + max(0, batch - len(top))
    news, today = load("news.json", []), dt.date.today().isoformat()
    alerts = 0
    for d in picks:
        u = d["u"]
        try:
            new = text_of(u)
        except Exception as e:
            print(f"  skip {d['n']}: {e}", file=sys.stderr)
            continue
        if new is None:
            continue
        new = norm(new)
        rec = idx["docs"].get(u, {})
        newhash = h(new)
        p = snap_path(u)
        if not rec or not p.exists():
            p.write_bytes(gzip.compress(new.encode()))
            idx["docs"][u] = {"hash": newhash, "first": today, "checked": today, "n": d["n"]}
            continue
        rec["checked"] = today
        if rec.get("hash") == newhash:
            continue
        old = gzip.decompress(p.read_bytes()).decode()
        diff = "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=1))

        def accept():
            # the snapshot moves forward only once the change has been judged, so a failed Claude call is retried next run
            p.write_bytes(gzip.compress(new.encode()))
            rec.update({"hash": newhash, "changed": today})
        if len(diff) < 40:
            accept(); continue
        # strict audit: exact before/after for each change, proven by quotes from both versions
        res = audit(d["c"], d["n"], u, old, new)
        if res is None:
            print(f"  {d['n']}: audit failed, will retry next run", file=sys.stderr)
            continue
        accept()
        if not res.get("material") or not res.get("changes"):
            print(f"  {d['n']}: checked, nothing material ({res.get('verdict')}, {res.get('dropped', 0)} unproven claims dropped)")
            continue
        f = story_fields(res, d["c"])
        covered = is_covered(f["title"], days=7)
        story = {"id": "w" + h(u + today), "date": today, "c": [d["c"]] if d["c"] in ("UPS", "FedEx", "USPS", "Amazon", "OnTrac", "DHL") else ["Regional"],
                 **f, "cat": "Guide changes", "kind": "Alert", "exclusive": not covered,
                 "src": d["c"], "url": u, "srcs": [{"src": f"{d['c']}: {d['n']}", "url": u}], "auto": True,
                 "audit": {"verdicts": res.get("verdict"), "dropped": res.get("dropped", 0), "compared": [{"new": u, "old": u + " (previous version)"}]}}
        story["dates"] = [x for x in story["dates"] if clock_worthy(story, x)]
        if res.get("unsupported"):
            ask(story, ["These numbers aren't in the old or new text: " + ", ".join(res["unsupported"])], story["srcs"])
            continue
        if not covered and big(story):
            ask(story, ["It's big and nobody else has reported it yet."], story["srcs"],
                extra="Changes:\n" + "\n".join(f"- {c.get('what')}: {c.get('before') or '(new)'} → {c.get('after')}" for c in story["changes"]))
            continue
        news.insert(0, story)          # routine guide changes publish on their own; alerts.py handles the phone push
        alerts += 1
    save("docwatch.json", idx)
    if alerts:
        save("news.json", news)
    print(f"docwatch: checked {len(picks)} documents, {alerts} material changes")


if __name__ == "__main__":
    main()
