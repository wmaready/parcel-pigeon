"""Watch carrier rate guides, billing and alert pages. When something material changes, draft a Parcel Pigeon
story and open a GitHub issue so a person can approve it with one label.

Run: python pipeline/watch.py
Needs: ANTHROPIC_API_KEY. For issues: GITHUB_TOKEN and GITHUB_REPOSITORY (set automatically in GitHub Actions).
"""
import datetime as dt, difflib, io, json, os, re, sys, urllib.parse
import requests, trafilatura, yaml
from pypdf import PdfReader
from common import ROOT, DATA, load, save, h, get, claude, parse_json, numbers_supported, MODEL_WRITE, clock_worthy, canon, known_doc_urls
from scoop import is_covered, notify, ask, big
from common import dedupe_live, same_event
from changeaudit import audit, file_text, predecessor, snapshot, remember, story_fields

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
    links = sorted({canon(urllib.parse.urljoin(url, m)) for m in re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I)})
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


def file_into_library(lib, item, fu, res):
    """Every file a carrier posts goes into the Docs library (and is watched from then on)."""
    if canon(fu) in known_doc_urls(lib):
        return
    name = fu.split("?")[0].rstrip("/").split("/")[-1]
    low = name.lower()
    kind = ("Surcharges & fees" if re.search(r"surcharge|ahs|lps|accessor|fee", low) and "zip" not in low else
            "Zones & DAS" if re.search(r"zip|zone|area|das", low) else "Fuel" if "fuel" in low else
            "Service guide" if "service" in low else "Terms" if re.search(r"terms|tariff|condition", low) else
            "Rate guide" if re.search(r"rate|price", low) else "Special program")
    yr = re.search(r"(20\d\d)", name)
    year = int(yr.group(1)) if yr else None
    pretty = re.sub(r"[-_]+", " ", re.sub(r"\.(pdf|xlsx?)$", "", name, flags=re.I)).strip()
    lib.append({"c": item["carrier"], "t": kind, "n": f"{item['carrier']} {pretty}" if item["carrier"].lower() not in pretty.lower() else pretty,
                "y": year, "eff": None, "u": fu, "d": f"Posted on {item['carrier']}'s {item['name']} page" +
                (f" ({res.get('verdict')})" if res and res.get("verdict") else ""),
                "cur": not (year and year < dt.date.today().year), "added": dt.date.today().isoformat(),
                "why": {"how": "relisted" if res and res.get("verdict") == "relisting" else "replaced" if res and res.get("pred") else "new-file",
                        "when": dt.date.today().isoformat(), "where": f"{item['carrier']}'s {item['name']} page",
                        "prev": (res.get("pred") or "").split("?")[0].split("/")[-1] if res else None}})


# Stories pulled after a re-check (id: reason). Removed from the live news on the next run.
RETRACT = {"w8a582ba4f6eb": "Re-check: OnTrac's file links only gained a new cache-busting version stamp (?v=...); "
                            "the rate and surcharge files themselves did not change."}


def retract():
    live = load("news.json", [])
    keep = [x for x in live if x.get("id") not in RETRACT]
    if len(keep) != len(live):
        save("news.json", keep)
        log = load("retracted.json", [])
        log += [{"id": i, "why": w} for i, w in RETRACT.items() if i not in {x.get("id") for x in log}]
        save("retracted.json", log)
        print(f"retracted {len(live) - len(keep)} story(ies)")


def main():
    retract()
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
        prev_pdfs = {canon(x) for x in prev.get("pdfs", [])}
        new_pdfs = sorted(set(pdfs) - prev_pdfs) if prev else []

        def accept():
            # the snapshot moves forward only once this change is handled, so a failed analysis is retried next run
            snap.write_text("\n".join(new))
            state[item["url"]] = {"checked": today, "pdfs": pdfs, "lines": len(new), "told": (state.get(item["url"]) or {}).get("told", [])}
        if first:
            accept(); print(f"baseline saved: {item['carrier']} {item['name']}"); continue
        removed, added = diff_lines(old, new)
        gone_pdfs = sorted(prev_pdfs - set(pdfs)) if prev else []
        if not removed and not added and not new_pdfs:
            state.setdefault(item["url"], {}).pop("pend", None)
            accept(); continue
        # a change has to show up on two runs in a row before it counts: some carrier pages load differently from one
        # read to the next, and a page that flickers between two versions must not look like a new posting each hour
        sig = h("\n".join(new) + "|" + ",".join(new_pdfs))
        if (prev or {}).get("pend") != sig:
            state.setdefault(item["url"], dict(prev or {}))["pend"] = sig
            print(f"  change seen once, confirming next run: {item['name']}"); continue
        # Spotting a change is step one; the audit says exactly what changed, before and after, and proves it.
        results, failed = [], False
        lib = load("docs.json", [])
        lib_urls = [d["u"] for d in lib if d.get("c") == item["carrier"] and d.get("u")]
        for fu in new_pdfs[:6]:
            try:
                ftxt = file_text(fu)
            except Exception as e:
                print(f"  couldn't open {fu}: {e}", file=sys.stderr); continue
            if not ftxt:
                continue
            pred = predecessor(fu, gone_pdfs + lib_urls)
            otxt = None
            if pred:
                otxt = snapshot(pred)
                if otxt is None:
                    try:
                        otxt = file_text(pred)
                    except Exception:
                        otxt = None
            res = audit(item["carrier"], fu.split("/")[-1], fu, otxt, ftxt,
                        note=f"Posted on {item['carrier']} {item['name']} ({item['url']})" + (f"; it appears to replace {pred}" if pred else ""))
            if res is None:
                failed = True; continue
            res["file"], res["pred"] = fu, pred
            results.append(res)
            remember(fu, ftxt, fu.split("/")[-1])
            file_into_library(lib, item, fu, res)
        if removed or added:
            res = audit(item["carrier"], item["name"], item["url"], "\n".join(old), "\n".join(new))
            if res is None:
                failed = True
            else:
                results.append(res)
        if failed and not results:
            print(f"  audit failed, will retry next run: {item['name']}", file=sys.stderr); continue
        accept()
        save("docs.json", lib)
        material = [r for r in results if r.get("material") and r.get("changes")]
        verdicts = ", ".join(f"{r.get('verdict')}" + (f" ({r['file'].split('/')[-1]})" if r.get("file") else "") for r in results)
        if not material:
            drafts.insert(0, {"status": "not material", "date": today, "page": item["url"], "verdicts": verdicts})
            print(f"  checked, nothing material: {item['name']} [{verdicts}]"); continue
        # drop changes this page has already been reported for (fingerprint: what + after), so a re-read never repeats a story
        told = set(state.get(item["url"], {}).get("told", []))
        fp = lambda c: h((c.get("what") or "").lower().strip() + "|" + re.sub(r"\s+", " ", (c.get("after") or "").lower()).strip())
        for r in material:
            r["changes"] = [c for c in r["changes"] if fp(c) not in told]
        material = [r for r in material if r["changes"]]
        if not material:
            drafts.insert(0, {"status": "already reported", "date": today, "page": item["url"], "verdicts": verdicts})
            print(f"  already reported, skipped: {item['name']}"); continue
        st = state.setdefault(item["url"], {})
        st["told"] = (st.get("told", []) + [fp(c) for r in material for c in r["changes"]])[-300:]
        material.sort(key=lambda r: (-int(r.get("lvl") or 1), -len(r["changes"])))
        lead = material[0]
        f = story_fields(lead, item["carrier"])
        for r in material[1:]:
            f["changes"] += [{k: c.get(k) for k in ("what", "before", "after", "effective", "who", "impact")} for c in r["changes"]]
            f["sum"] += f" Also: {r.get('title')}."
        f["changes"] = f["changes"][:12]
        srcs = [{"src": f"{item['carrier']} {item['name']}", "url": item["url"]}] + \
               [{"src": f"{item['carrier']}: {r['file'].split('/')[-1]}", "url": r["file"]} for r in material if r.get("file")]
        story = {"id": "w" + h(item["url"] + today + f["title"]), "date": today, "c": [item["carrier"]], **f, "kind": "Alert",
                 "src": f"{item['carrier']} {item['name']} (spotted by Parcel Pigeon)", "url": lead.get("file") or item["url"],
                 "srcs": srcs, "auto": True,
                 "audit": {"verdicts": verdicts, "dropped": sum(r.get("dropped", 0) for r in results),
                           "compared": [{"new": r.get("file"), "old": r.get("pred")} for r in material if r.get("file")]}}
        story["dates"] = [d for d in story["dates"] if clock_worthy(story, d)]
        changes = story["changes"]
        reasons = []
        unsupported = sorted({x for r in material for x in r.get("unsupported") or []})
        if unsupported:
            reasons.append("These numbers aren't in the old or new text: " + ", ".join(unsupported))
        if not is_covered(story["title"]):
            story["exclusive"] = True
            if big(story):
                reasons.append("It's big and nobody else has reported it yet.")
        if reasons:
            lines = "\n".join(f"- **{c.get('what','')}**: {c.get('before') or '(new)'} → {c.get('after')}" for c in changes)
            try:
                url = ask(story, reasons, story["srcs"], extra=f"Spotted on **{item['carrier']} — {item['name']}** ({verdicts}):\n{lines}")
            except Exception as e:
                url = None; print(f"  issue failed: {e}", file=sys.stderr)
            drafts.insert(0, {"status": "asked", "issue": url, "story": story})
            continue
        live = load("news.json", [])
        twin = next((x for x in live if same_event(x, story)), None)
        if twin:
            drafts.insert(0, {"status": "same as published", "story": story, "twin": twin.get("id")})
            print(f"  same event already published ({twin.get('id')}), skipped: {story['title']}"); continue
        if not any(x.get("id") == story["id"] for x in live):
            live.insert(0, story); save("news.json", live)
        drafts.insert(0, {"status": "published", "story": story})
        print(f"  PUBLISHED: {story['title']} [{verdicts}]")
    save("watch_state.json", state); save("drafts.json", drafts[:200])
    live = load("news.json", [])
    clean = dedupe_live(live)
    if len(clean) != len(live):
        save("news.json", clean)


if __name__ == "__main__":
    main()
