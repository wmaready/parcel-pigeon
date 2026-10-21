"""Watch carrier rate guides, billing and alert pages. When something material changes, draft a Parcel Pigeon
story and open a GitHub issue so a person can approve it with one label.

Run: python pipeline/watch.py
Needs: ANTHROPIC_API_KEY. For issues: GITHUB_TOKEN and GITHUB_REPOSITORY (set automatically in GitHub Actions).
"""
import datetime as dt, difflib, io, json, os, re, sys, urllib.parse
import requests, trafilatura, yaml
from pypdf import PdfReader
from common import pdf_to_text, ROOT, DATA, load, save, h, get, claude, parse_json, numbers_supported, MODEL_WRITE, clock_worthy, canon, known_doc_urls
from scoop import is_covered, notify, ask, big
from common import dedupe_live, same_event
from changeaudit import audit, file_text, predecessor, snapshot, remember, story_fields
from fetch import fetch, fetch_late, render, is_blocked, is_pdf, Blocked

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


def page_text(url, full=False):
    """Return (text, pdf_links, page). full=True keeps the whole page's text (news-release lists, where the
    article extractor would pick one promo block instead of the list). Falls back to a headless browser for pages built with JavaScript.
    Raises fetch.Blocked when the carrier's site only ever returns its bot wall."""
    pg = fetch(url, timeout=40)
    if is_pdf(url, pg):
        return pdf_text(pg.content), [], pg
    html = pg.text
    text = trafilatura.extract(html, include_tables=True, include_comments=False) or ""
    hidden = 'aria-expanded="false"' in html or "<details" in html
    if (len(text) < 500 or hidden) and pg.via != "browser":
        html = render(url) or html
        text = trafilatura.extract(html, include_tables=True) or re.sub(r"<[^>]+>", " ", html)
    if full:
        text = "\n".join(l.strip() for l in re.sub(r"<[^>]+>", "\n", re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)).splitlines() if l.strip())
    if is_blocked(text):
        late = fetch_late(url)
        if late is None:
            raise Blocked("blocked by the carrier's site (block page after rendering; no proxy or archive copy)")
        pg, html = late, late.text
        text = trafilatura.extract(html, include_tables=True, include_comments=False) or ""
        if full:
            text = "\n".join(l.strip() for l in re.sub(r"<[^>]+>", "\n", re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)).splitlines() if l.strip())
        if is_blocked(text):
            raise Blocked("blocked by the carrier's site (the archive copy is a block page too)")
    links = sorted({canon(urllib.parse.urljoin(url, m)) for m in re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I)})
    return text, links, pg



def pdf_text(data):
    return pdf_to_text(data)


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


def file_into_library(lib, item, fu, res, baseline=False):
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
    if baseline:
        # a file that was already on the carrier's page when we first saw it: filed and watched, but not "new"
        lib.append({"c": item["carrier"], "t": kind, "n": f"{item['carrier']} {pretty}" if item["carrier"].lower() not in pretty.lower() else pretty,
                    "y": year, "eff": None, "u": fu, "d": f"Posted on {item['carrier']}'s {item['name']} page",
                    "cur": not (year and year < dt.date.today().year), "seen": dt.date.today().isoformat()})
        return
    lib.append({"c": item["carrier"], "t": kind, "n": f"{item['carrier']} {pretty}" if item["carrier"].lower() not in pretty.lower() else pretty,
                "y": year, "eff": None, "u": fu, "d": f"Posted on {item['carrier']}'s {item['name']} page" +
                (f" ({res.get('verdict')})" if res and res.get("verdict") else ""),
                "cur": not (year and year < dt.date.today().year), "added": dt.date.today().isoformat(),
                "why": {"how": "relisted" if res and res.get("verdict") == "relisting" else "replaced" if res and res.get("pred") else "new-file",
                        "when": dt.date.today().isoformat(), "where": f"{item['carrier']}'s {item['name']} page",
                        "prev": (res.get("pred") or "").split("?")[0].split("/")[-1] if res else None}})


def catalog(item, pdfs, skip=(), cap=10):
    """Files already on a carrier page: read once, keep the text as the 'before' copy, file in the Docs library as existing
    (no "new" tag, no story, no alert). From then on a change to any of them is news; their being there is not."""
    todo = [u for u in pdfs if u not in skip and not u.lower().split("?")[0].endswith((".xlsx", ".xls")) and snapshot(u) is None][:cap]
    if not todo:
        return 0
    lib, n = load("docs.json", []), 0
    for fu in todo:
        try:
            txt = file_text(fu, max_pages=None)
        except Exception as e:
            print(f"  catalog: couldn't read {fu}: {e}", file=sys.stderr); continue
        if not txt:
            continue
        remember(fu, txt, fu.split("?")[0].split("/")[-1])
        if canon(fu) not in known_doc_urls(lib):
            file_into_library(lib, item, fu, None, baseline=True)
        n += 1
    if n:
        save("docs.json", lib)
        print(f"  catalogued {n} existing file(s) from {item['carrier']} {item['name']} (no news)")
    return n


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
    health = load("watch_health.json", {})
    for item in cfg.get("watch", []):
        key = h(item["url"])
        hh = health.setdefault(item["url"], {"carrier": item["carrier"], "name": item["name"], "fails": 0, "thin": 0})
        try:
            text, pdfs, pg = page_text(item["url"], full=item.get("mode") == "full")
        except Exception as e:
            # a bot wall is a failed read, never a reading: nothing is saved or compared, and the audit flags it
            hh["fails"] = hh.get("fails", 0) + 1; hh["err"] = str(e)[:160]; hh["last_try"] = today
            hh["blocked"] = isinstance(e, Blocked)
            print(f"skip {item['name']}: {e}", file=sys.stderr); continue
        new = norm(text)
        # coverage record: the audit flags any source we haven't read successfully in the last day or so, or that reads back nearly empty
        hh.update({"fails": 0, "err": None, "blocked": False, "last_try": today, "chars": len(text or ""),
                   "via": pg.via, "copy_of": pg.when, "last_ok": today if len(text or "") >= 300 else hh.get("last_ok")})
        hh["thin"] = hh.get("thin", 0) + 1 if len(text or "") < 300 else 0
        if len(text or "") < 300 and not hh.get("probe_day") == today:
            # a page that reads back empty: record exactly what the carrier's server sent, so the audit says why
            try:
                pr = requests.get(item["url"], headers=get.__globals__["UA"], timeout=25, allow_redirects=True)
                hh["probe"] = f"HTTP {pr.status_code}, {pr.headers.get('content-type','?')[:40]}, {len(pr.content)} bytes, starts: {pr.text[:140]!r}"
            except Exception as e:
                hh["probe"] = f"probe failed: {str(e)[:100]}"
            hh["probe_day"] = today
        elif len(text or "") >= 300:
            hh.pop("probe", None)
        snap = SNAP / f"{key}.txt"
        prev = state.get(item["url"], {})
        first = not snap.exists()
        _new_links = sorted(set(pdfs) - {canon(x) for x in prev.get("pdfs", [])}) if prev else []
        catalog(item, pdfs, skip=set(_new_links))
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
                ftxt = file_text(fu, max_pages=None)     # whole file, as docwatch reads it, or pages past 60 look "added" later
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
                        otxt = file_text(pred, max_pages=None)
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
            # found on the carrier's own page before anyone reported it: the carrier is the source of truth, so no second
            # source is needed. It publishes as first-to-report. (Only numbers that don't match the documents are held.)
            story["exclusive"] = True
            story["primary"] = True
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
    save("watch_state.json", state); save("drafts.json", drafts[:200]); save("watch_health.json", health)
    live = load("news.json", [])
    clean = dedupe_live(live)
    if len(clean) != len(live):
        save("news.json", clean)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from scoop import crash_alert
        crash_alert("watch.py")
        raise
