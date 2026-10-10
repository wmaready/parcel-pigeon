"""Watch carrier rate guides, billing and alert pages. When something material changes, draft a Parcel Pigeon
story and open a GitHub issue so a person can approve it with one label.

Run: python pipeline/watch.py
Needs: ANTHROPIC_API_KEY. For issues: GITHUB_TOKEN and GITHUB_REPOSITORY (set automatically in GitHub Actions).
"""
import datetime as dt, difflib, io, json, os, re, sys, urllib.parse
import requests, trafilatura, yaml
from pypdf import PdfReader
from common import ROOT, DATA, load, save, h, get, claude, parse_json, numbers_supported, MODEL_WRITE
from scoop import is_covered, notify

SNAP = DATA / "snapshots"
MAX_DIFF_CHARS = 12000

ANALYST = """You are the Parcel Pigeon change analyst. A carrier changed a page or document that shippers rely on
(rate guide, surcharge page, fuel table, service alert, developer/API page, postal price filing). You get the lines
that were removed and added. Decide if the change matters to companies that ship small parcels: new or changed
prices, fees, surcharges, effective dates, fuel tables, service changes or suspensions, rule or threshold changes,
API changes or retirements, newly posted rate guides. Ignore cosmetic edits, navigation, cookie text, reordered
content, and routine weekly fuel percentage updates (those are tracked elsewhere) unless the fuel TABLE itself changed.

Return JSON only:
{"material": true|false,
 "changes": [{"what": "...", "old": "...", "new": "...", "effective": "YYYY-MM-DD or null"}],
 "story": {"title": "...", "sum": "...", "imp": "up|down|watch|info", "lvl": 1|2|3, "plain": "...",
           "act": "YYYY-MM-DD or null",
           "dates": [{"d": "YYYY-MM-DD", "w": "...", "imp": "up|down|info"}],
           "category": "Pricing & GRI|Fees & rules|Peak season|Fuel|Technology & tools|Postal|Network & operations|International|Documents"}}
Story rules: neutral trade-press wire style, no advice; say this was posted on the carrier's own page; use only
facts in the added/removed lines; every number must appear there; title under 90 characters. If material is false,
story may be null."""


def page_text(url):
    """Return (text, pdf_links). Falls back to a headless browser for pages built with JavaScript."""
    r = get(url, timeout=40)
    if "pdf" in r.headers.get("content-type", "") or url.lower().endswith(".pdf"):
        return pdf_text(r.content), []
    html = r.text
    text = trafilatura.extract(html, include_tables=True, include_comments=False) or ""
    if len(text) < 500:
        html = render(url) or html
        text = trafilatura.extract(html, include_tables=True) or re.sub(r"<[^>]+>", " ", html)
    links = sorted({urllib.parse.urljoin(url, m) for m in re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I)})
    return text, links


def pdf_text(data):
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(f"[page {i+1}]\n" + (p.extract_text() or "") for i, p in enumerate(reader.pages))


def render(url):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(url, wait_until="networkidle", timeout=45000)
            html = pg.content()
            b.close()
            return html
    except Exception as e:
        print(f"  render failed {url}: {e}", file=sys.stderr)
        return None


def norm(text):
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    return [l for l in lines if l and not re.search(r"cookie|javascript|©|all rights reserved", l, re.I)]


def diff_lines(old, new):
    removed, added = [], []
    for d in difflib.unified_diff(old, new, lineterm="", n=0):
        if d.startswith("---") or d.startswith("+++") or d.startswith("@@"):
            continue
        (added if d.startswith("+") else removed).append(d[1:])
    return removed, added


def open_issue(story, item, changes):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    lines = "\n".join(f"- **{c.get('what','')}**: {c.get('old','—')} → {c.get('new','—')}" + (f" (effective {c['effective']})" if c.get('effective') else "") for c in changes)
    body = f"""Spotted a change on **{item['carrier']} — {item['name']}**: {item['url']}

### What changed
{lines}

### Draft story (edit any line below, then add the `publish` label)
TITLE: {story['title']}
SUMMARY: {story['sum']}
EFFECT: {story['plain']}

Close the issue to discard it.

<!-- parcelwatch-data
{json.dumps(story)}
-->"""
    covered = is_covered(story["title"])
    if not covered:
        story["exclusive"] = True
        body = "**Nobody in the trade press has reported this yet.**\n\n" + body
        return notify(f"[First to report] {story['title']}", body, labels=("draft", "first-to-report", item["carrier"]), link=item["url"])
    body = f"Already covered by: {', '.join(covered)}\n\n" + body
    return notify(f"[Draft] {story['title']}", body, labels=("draft", item["carrier"]), link=item["url"]) if (token and repo) else None


def main():
    cfg = yaml.safe_load((ROOT / "pipeline" / "sources.yaml").read_text())
    SNAP.mkdir(parents=True, exist_ok=True)
    state, drafts = load("watch_state.json", {}), load("drafts.json", [])
    today = dt.date.today().isoformat()
    for item in cfg.get("watch", []):
        key = h(item["url"])
        try:
            text, pdfs = page_text(item["url"])
        except Exception as e:
            print(f"skip {item['name']}: {e}", file=sys.stderr); continue
        new = norm(text)
        snap = SNAP / f"{key}.txt"
        prev = state.get(item["url"], {})
        first = not snap.exists()
        old = snap.read_text().splitlines() if not first else []
        new_pdfs = sorted(set(pdfs) - set(prev.get("pdfs", []))) if prev else []

        def accept():
            # the snapshot moves forward only once this change is handled, so a failed analysis is retried next run
            snap.write_text("\n".join(new))
            state[item["url"]] = {"checked": today, "pdfs": pdfs, "lines": len(new)}
        if first:
            accept(); print(f"baseline saved: {item['carrier']} {item['name']}"); continue
        removed, added = diff_lines(old, new)
        if new_pdfs:
            added += [f"NEW FILE POSTED: {u}" for u in new_pdfs]
        if not removed and not added:
            accept(); continue
        payload = f"Carrier: {item['carrier']}\nPage: {item['name']} ({item['url']})\nDate noticed: {today}\n\nREMOVED LINES:\n" + \
                  "\n".join(removed)[:MAX_DIFF_CHARS // 2] + "\n\nADDED LINES:\n" + "\n".join(added)[:MAX_DIFF_CHARS // 2]
        try:
            res = parse_json(claude(MODEL_WRITE, ANALYST, payload, max_tokens=1500))
        except Exception as e:
            print(f"  analysis failed, will retry next run: {e}", file=sys.stderr); continue
        accept()
        if not res.get("material") or not res.get("story"):
            print(f"  change not material: {item['name']}"); continue
        s = res["story"]
        story = {"id": "w" + h(item["url"] + today + s["title"]), "date": today, "c": [item["carrier"]],
                 "cat": s.get("category", "Documents"), "title": s["title"], "sum": s["sum"], "imp": s.get("imp", "watch"),
                 "lvl": int(s.get("lvl", 2)), "plain": s["plain"], "act": s.get("act"),
                 "dates": s.get("dates", []),
                 "src": f"{item['carrier']} {item['name']} (spotted by Parcel Pigeon)", "url": item["url"]}
        missing = numbers_supported(" ".join([story["title"], story["sum"], story["plain"]]), "\n".join(added + removed))
        if missing:
            story["unsupported_numbers"] = missing
        try:
            url = open_issue(story, item, res.get("changes", []))
        except Exception as e:
            url = None; print(f"  issue failed: {e}", file=sys.stderr)
        drafts.insert(0, {"status": "draft", "issue": url, "story": story, "changes": res.get("changes", [])})
        print(f"  DRAFT ready: {story['title']}")
    save("watch_state.json", state); save("drafts.json", drafts[:200])


if __name__ == "__main__":
    main()
