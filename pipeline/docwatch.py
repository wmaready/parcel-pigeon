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
from common import ROOT, load, save, h, get, claude, parse_json, MODEL_WRITE, clock_worthy, canon
from fetch import fetch, is_blocked, is_pdf, Blocked
from scoop import is_covered, notify, ask, big
from changeaudit import audit, story_fields, robot_leaks

SNAP = ROOT / "data" / "docwatch"
PICS = ROOT / "data" / "snapshots"          # dated pictures of watched pages: <doc-id>/<YYYY-MM-DD>.jpg + .txt
KEEP_PICS = 6                               # newest pictures kept per document
MAX_PICS = 8                                # pictures taken per run at most (changed pages first), so a run stays short
ROTATE_MIN = 10                             # rotation slots every run, on top of the priority documents
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


PDF_LINK = re.compile(r"""(?:href|value|data-href|data-url|data-src)\s*=\s*["']([^"']+?\.pdf(?:\?[^"']*)?)["']""", re.I)
BLOCKED = ("access denied", "request blocked", "are you a robot", "enable javascript", "page not found", "404 error",
           "temporarily unavailable", "captcha")


def pdf_links(html, base):
    """Every PDF the page offers, including ones hidden in drop-down menus (<option value=...pdf>) and buttons."""
    from urllib.parse import urljoin
    out = []
    for m in PDF_LINK.findall(html or ""):
        u = urljoin(base, m.replace("&amp;", "&"))
        if u not in out:
            out.append(u)
    return out


def best_pdf(links, name):
    """Pick the PDF that best matches the document's name (e.g. 'Service Guide', 'Rate Guide', the current year)."""
    words = {w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(w) > 2}
    year = str(dt.date.today().year)
    def score(u):
        s = u.lower()
        return sum(w in s for w in words) * 2 + (year in s or str(int(year) + 1) in s) + ("en" in s.split("/"))
    return max(links, key=score) if links else None


def read_pdf(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


LAST = {}       # how the last text_of() read was made: {"pdf": url} when the text came from a PDF file


def text_of(url, name=""):
    """Plain text of a carrier file or page. Raises fetch.Blocked for a bot wall, so it is never saved as the document."""
    LAST.clear()
    r = fetch(url, timeout=60)
    ctype = r.headers.get("content-type", "").lower()
    if is_pdf(url, r):
        LAST["pdf"] = url
        return read_pdf(r.content)
    if "spreadsheet" in ctype or url.lower().split("?")[0].endswith((".xlsx", ".xls")):
        return None  # spreadsheets are ZIP lists and rate tables; the PDF twin is watched instead
    # HTML page: prefer the real PDF behind the page (carrier sites hide them behind drop-downs)
    pdf = best_pdf(pdf_links(r.text, r.url), name)
    if pdf:
        try:
            t = read_pdf(fetch(pdf, timeout=60).content)
            if len(t.strip()) > 500:
                print(f"  {name}: using PDF {pdf}")
                LAST["pdf"] = pdf
                return t
        except Exception as e:
            print(f"  {name}: PDF {pdf} failed ({e}), using page text", file=sys.stderr)
    import trafilatura
    t = trafilatura.extract(r.text, include_comments=False, include_tables=True) or ""
    low = t.lower()[:3000]
    if is_blocked(t):
        raise Blocked("block page")
    if len(t.strip()) < 300 or any(b in low for b in BLOCKED):
        # blank, blocked or error page: never save it as the document, or a later real page looks like a huge "change"
        raise RuntimeError("page is blank or blocked; snapshot kept as-is")
    return t


def norm(t):
    t = re.sub(r"[ \t]+", " ", t or "")
    t = re.sub(r"(?im)^\s*(page \d+( of \d+)?|\d+)\s*$", "", t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def snap_path(url):
    return SNAP / f"{h(url)}.txt.gz"


def pick(docs, idx, batch):
    """This run's documents. Priority documents (rate and service guides) are checked every run, and the rest rotate
    through slots of their own (at least ROTATE_MIN, whatever the batch), never-checked documents first. Before Oct 2026
    the rotation only got `batch - len(top)` slots: with 37 priority documents and --batch 15 that was zero, the cursor
    never moved, and 63 of 122 documents had never been checked once (including the UPS Small Business Rates page)."""
    top = [d for d in docs if PRIORITY.get(d.get("t"), 5) == 0]
    rest = [d for d in docs if PRIORITY.get(d.get("t"), 5) != 0]
    rotate = max(ROTATE_MIN, batch)
    cur = idx.get("cursor", 0) % max(1, len(rest))
    order = rest[cur:] + rest[:cur]
    order.sort(key=lambda d: d["u"] in idx.get("docs", {}))     # stable: never-checked first, then the rotation order
    idx["cursor"] = (cur + rotate) % max(1, len(rest))
    return top + order[:rotate]


def doc_id(url):
    """Folder name for a document's pictures: the same short hash its text snapshot uses."""
    return h(url)


PIC_BLOCKED = ("access denied", "request blocked", "captcha", "are you a robot", "pardon our interruption",
               "checking your browser", "unusual traffic", "you don't have permission")


def ok_picture(status, text):
    """(True, "") when the page is fit to keep as proof, else (False, reason). Blocked or broken pages are never proof."""
    if status != 200:
        return False, f"status {status}"
    if len((text or "").strip()) < 500:
        return False, "page text under 500 characters"
    low = (text or "").lower()
    hit = next((b for b in PIC_BLOCKED if b in low), None)
    if hit:
        return False, f'page says "{hit}"'
    return True, ""


def capture(url, out, timeout=30):
    """A picture of the page as a reader sees it: Playwright Chromium, headless, 1280 px wide, networkidle (30 s limit)
    then 2 s to settle, common cookie banners dismissed, full page capped at 8,000 px, JPEG quality 70. The picture is
    only written when the page passes ok_picture. Returns (http_status, visible_text); raises on a browser failure."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        try:
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            r = pg.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            pg.wait_for_timeout(2000)
            for label in ("Accept All", "Accept all", "Accept", "I Accept", "Agree"):
                try:
                    btn = pg.get_by_role("button", name=label, exact=True)
                    if btn.count():
                        btn.first.click(timeout=1500)
                        pg.wait_for_timeout(500)
                        break
                except Exception:
                    pass                        # no banner, or it wouldn't close: carry on
            text = pg.evaluate("() => document.body ? document.body.innerText : ''") or ""
            status = r.status if r is not None else 0
            if ok_picture(status, text)[0]:
                height = min(8000, int(pg.evaluate("() => document.documentElement.scrollHeight") or 900))
                pg.screenshot(path=str(out), type="jpeg", quality=70, full_page=True,
                              clip={"x": 0, "y": 0, "width": 1280, "height": max(1, height)})
            return status, text
        finally:
            b.close()


def keep_six(folder):
    """Newest KEEP_PICS dates (picture and text) per document; older ones are deleted so the repository stays small."""
    days = sorted({f.stem for f in folder.glob("*.jpg")} | {f.stem for f in folder.glob("*.txt")}, reverse=True)
    for d in days[KEEP_PICS:]:
        for ext in (".jpg", ".txt"):
            (folder / f"{d}{ext}").unlink(missing_ok=True)


def to_review(doc, url, reason, today):
    """One data/review.json entry per page and day when a picture couldn't be kept as proof."""
    rv = load("review.json", [])
    if any(isinstance(x, dict) and x.get("type") == "page-picture" and x.get("url") == url and x.get("date") == today for x in rv):
        return
    rv.insert(0, {"type": "page-picture", "title": f"{doc.get('c', '')}: {doc.get('n', '')}", "url": url, "date": today,
                  "note": f"Doc watch didn't save a picture of this page ({reason}). The previous picture is kept. Check the page by hand."})
    save("review.json", rv[:200])


def picture(doc, rec, text, today, changed, how=None):
    """B35: a dated picture of the page, only when its cleaned text changed or it has no picture yet. It backs up the text
    comparison and never replaces it: any failure here is logged and leaves the previous picture and rec["snap"] as they
    were. PDF documents are never photographed; the file's address and today's date are stored instead. True if saved."""
    u, how = doc["u"], (LAST if how is None else how)
    if not changed and rec.get("snap"):
        return False
    folder = PICS / doc_id(u)
    prev = rec.get("snap") or {}
    if prev.get("d") == today:
        return False        # one picture a document a day: hourly re-captures of a busy page would bloat the repository
    prev_img = prev.get("img")
    tmp = folder / f".{today}.part.jpg"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if how.get("pdf") or is_pdf(u):
            (folder / f"{today}.txt").write_text(text)
            snap = {"d": today, "pdf": how.get("pdf") or u, "txt": (folder / f"{today}.txt").relative_to(ROOT).as_posix()}
            if prev.get("d") and prev["d"] != today:
                snap["prev_d"] = prev["d"]
            rec["snap"] = snap
            keep_six(folder)
            return True
        tmp.unlink(missing_ok=True)
        status, seen = capture(u, tmp)
        good, why = ok_picture(status, seen)
        if not good or not tmp.exists():
            tmp.unlink(missing_ok=True)
            print(f"  {doc.get('n')}: no picture saved ({why or 'nothing captured'})", file=sys.stderr)
            to_review(doc, u, why or "nothing captured", today)
            return False
        img = folder / f"{today}.jpg"
        tmp.replace(img)
        (folder / f"{today}.txt").write_text(text)
        keep_six(folder)
        snap = {"d": today, "img": img.relative_to(ROOT).as_posix()}
        if prev_img and (ROOT / prev_img).exists():
            snap["prev"] = prev_img
        rec["snap"] = snap
        return True
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        print(f"  {doc.get('n')}: picture failed ({type(e).__name__}: {str(e)[:120]}); the text check is unaffected", file=sys.stderr)
        return False


def main():
    batch = 15
    if "--batch" in sys.argv:
        batch = int(sys.argv[sys.argv.index("--batch") + 1])
    SNAP.mkdir(parents=True, exist_ok=True)
    seed = load("seed.json", {})
    # one entry per file: the same file under a new cache stamp (?v=...) is not a new document
    docs = {canon(d["u"]): {**d, "u": canon(d["u"])} for d in seed.get("docs", []) + load("docs.json", []) if (d.get("u") or "").startswith("http")}
    docs = [d for d in docs.values() if d.get("t") not in SKIP_TYPES and d.get("cur", True) is not False]
    docs.sort(key=lambda d: (PRIORITY.get(d.get("t"), 5), d.get("c", ""), d.get("n", "")))
    idx = load("docwatch.json", {"cursor": 0, "docs": {}})
    # priority documents (rate guides, service guides) are checked every run; the rest rotate in slots of their own
    picks = pick(docs, idx, batch)
    news, today = load("news.json", []), dt.date.today().isoformat()
    alerts, pics = 0, []
    for d in picks:
        u = d["u"]
        try:
            new = text_of(u, d.get("n", ""))
        except Exception as e:
            # a bot wall or dead link is a failed read: recorded so the audit can flag it, never saved as the document
            r0 = idx["docs"].setdefault(u, {"n": d["n"]})
            r0.update({"fails": r0.get("fails", 0) + 1, "err": str(e)[:160], "blocked": isinstance(e, Blocked), "last_try": today})
            print(f"  skip {d['n']}: {e}", file=sys.stderr)
            continue
        if new is None:
            # a spreadsheet (its PDF twin is watched instead): noted as looked at, so it never holds a never-checked slot
            idx["docs"].setdefault(u, {"n": d["n"]}).update({"checked": today, "skip": "spreadsheet"})
            continue
        new = norm(new)
        rec = idx["docs"].get(u, {})
        for k in ("fails", "err", "blocked", "skip"):
            rec.pop(k, None)
        newhash = h(new)
        p = snap_path(u)
        if not rec or not p.exists():
            p.write_bytes(gzip.compress(new.encode()))
            idx["docs"][u] = {"hash": newhash, "first": today, "checked": today, "n": d["n"],
                              **{k: rec[k] for k in ("snap", "pic_try") if rec.get(k)}}
            pics.append((d, idx["docs"][u], new, False, dict(LAST)))
            continue
        rec["checked"] = today
        if rec.get("hash") == newhash:
            pics.append((d, rec, new, False, dict(LAST)))
            continue
        pics.append((d, rec, new, True, dict(LAST)))
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
        leaks = robot_leaks(story)
        if leaks:
            # B9 final pass: text that still reads like the auditor's own notes is held for a person, never published
            story.pop("robot_notes", None)
            ask(story, ["The text still has robot notes in it: " + " | ".join(x[:100] for x in leaks[:3])], story["srcs"])
            continue
        # found on the carrier's own site before anyone reported it: publish as first-to-report (the audit above already proved every number)
        news.insert(0, story)          # routine guide changes publish on their own; alerts.py handles the phone push
        alerts += 1
    if alerts:
        save("news.json", news)
    # dated pictures (B35), after the text results: changed pages first, then pages with no picture yet. A page whose
    # picture couldn't be kept today waits for tomorrow unless its text changes. At most MAX_PICS a run.
    todo = [x for x in pics if x[3]] + [x for x in pics if not x[3] and not x[1].get("snap") and x[1].get("pic_try") != today]
    taken = 0
    for d, rec, text, changed, how in todo[:MAX_PICS]:
        if picture(d, rec, text, today, changed, how):
            taken += 1
            rec.pop("pic_try", None)
        else:
            rec["pic_try"] = today
    save("docwatch.json", idx)
    print(f"docwatch: checked {len(picks)} documents, {alerts} material changes, {taken} page pictures saved")


if __name__ == "__main__":
    main()
