"""Strict change audit for carrier pages, guides and newly posted files.

Spotting that something changed is step one. The job here is to say exactly WHAT changed (before -> after),
WHEN it takes effect, WHO it hits and HOW MUCH, and to prove it: every change must carry a quote that is found
word for word in the old text (for the "before") and in the new text (for the "after"). Anything that can't be
proven is dropped, and if nothing survives the change isn't published as news.

Used by watch.py (carrier pages and the files they link) and docwatch.py (documents in the library).
"""
import difflib, gzip, io, json, re, sys
from common import ROOT, load, save, h, get, claude, parse_json, numbers_supported, MODEL_WRITE

SNAP = ROOT / "data" / "docwatch"            # same text snapshots docwatch keeps, so a file's "before" is always on hand
MAX_TEXT = 14000

AUDITOR = """You are Parcel Pigeon's change auditor. A carrier changed a page or document shippers rely on, or posted a new file.
You get the OLD text and the NEW text (or only NEW for a file that has no earlier version). Work out exactly what changed
and what it means for companies that ship small parcels.

Rules:
- Every change needs proof: "quote_new" copied word for word from NEW (under 200 characters) and, when there is a before,
  "quote_old" copied word for word from OLD. "before" must come only from OLD, "after" only from NEW. No numbers that aren't in the texts.
- Compare like with like: same fee, same weight break, same zone. Say the size of the move when both numbers are there
  (e.g. "$8.75 -> $9.25, +$0.50 per package").
- A file with no earlier version: list its key terms (effective date, main prices, thresholds, who it applies to) as changes with before = null.
- "relisting": the "new" file is the same document as before, an older year re-linked, or only its link moved.
- "cosmetic": formatting, navigation, page dates, reordering, typo fixes. Routine weekly fuel percentage updates are cosmetic
  unless the fuel TABLE itself changed.
- material = true only if at least one change alters a price, fee, surcharge, threshold, zone/ZIP coverage, service, rule,
  liability or contract term, or posts a new rate/service document shippers will use.

Return JSON only:
{"verdict": "price change"|"rule change"|"service change"|"new document"|"relisting"|"cosmetic",
 "material": true|false,
 "title": "neutral headline under 90 characters, naming the carrier and the change",
 "summary": "2-3 sentences: what changed, old vs new, effective date if stated",
 "effect": "1-2 sentences: who is affected and how much; plain, no advice",
 "imp": "up"|"down"|"watch"|"info", "lvl": 1|2|3,
 "category": "Pricing & GRI"|"Fees & rules"|"Peak season"|"Fuel"|"Network & operations"|"Technology & tools"|"Postal"|"International"|"Guide changes",
 "act": "YYYY-MM-DD or null",
 "changes": [{"what": "...", "before": "... or null", "after": "...", "effective": "YYYY-MM-DD or null",
              "who": "which shipments or shippers", "impact": "size of the move, or null", "quote_old": "... or null", "quote_new": "..."}],
 "unknowns": ["anything that could not be confirmed from the texts"]}"""


def squash(t):
    return re.sub(r"\s+", " ", (t or "").lower()).replace(" ,", ",").strip()


def file_text(url):
    """Plain text of a PDF or web page (None for spreadsheets)."""
    from fetch import fetch
    r = fetch(url, timeout=60)
    ctype = r.headers.get("content-type", "").lower()
    path = url.lower().split("?")[0]
    if path.endswith(".pdf") or "pdf" in ctype:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(r.content))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:60])
    if path.endswith((".xlsx", ".xls")) or "spreadsheet" in ctype:
        return None
    import trafilatura
    return trafilatura.extract(r.text, include_comments=False, include_tables=True) or ""


def norm(t):
    """Same normalising docwatch uses, so snapshots and hashes line up."""
    t = re.sub(r"[ \t]+", " ", t or "")
    t = re.sub(r"(?im)^\s*(page \d+( of \d+)?|\d+)\s*$", "", t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def snapshot(url):
    p = SNAP / f"{h(url)}.txt.gz"
    return gzip.decompress(p.read_bytes()).decode() if p.exists() else None


def remember(url, text, name):
    """Keep this version as the 'before' for next time (and let docwatch keep watching it)."""
    SNAP.mkdir(parents=True, exist_ok=True)
    text = norm(text)
    (SNAP / f"{h(url)}.txt.gz").write_bytes(gzip.compress(text.encode()))
    idx = load("docwatch.json", {"cursor": 0, "docs": {}})
    import datetime as dt
    today = dt.date.today().isoformat()
    rec = idx["docs"].setdefault(url, {"first": today, "n": name})
    rec.update({"hash": h(text), "checked": today})
    save("docwatch.json", idx)


def stem(url):
    """File name with years, versions and dates removed, for pairing a new file with the one it replaced."""
    name = url.lower().split("?")[0].rstrip("/").split("/")[-1]
    name = re.sub(r"\.(pdf|xlsx?|html?)$", "", name)
    name = re.sub(r"(19|20)\d\d|v\d+|\d{1,2}[-_]\d{1,2}|rev\w*|final|updated?|new", " ", name)
    return " ".join(re.findall(r"[a-z]{2,}", name))


def predecessor(url, candidates):
    """The most similar earlier file (same stem) from links that disappeared or the document library."""
    s = stem(url)
    best, score = None, 0.0
    for c in candidates:
        if c == url:
            continue
        r = difflib.SequenceMatcher(None, s, stem(c)).ratio()
        if r > score:
            best, score = c, r
    return best if score >= 0.72 else None


def focus(old, new):
    """The changed parts with context, so long documents fit: unified diff hunks, or the start of a brand-new text."""
    if not old:
        return "", new[:MAX_TEXT]
    o, n = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, o, n, autojunk=False)
    old_parts, new_parts = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old_parts.append("\n".join(o[max(0, i1 - 3):i2 + 3]))
        new_parts.append("\n".join(n[max(0, j1 - 3):j2 + 3]))
    return "\n...\n".join(old_parts)[:MAX_TEXT // 2], "\n...\n".join(new_parts)[:MAX_TEXT // 2]


def verify(res, old, new):
    """Keep only changes whose quotes and numbers are really in the texts."""
    so, sn = squash(old), squash(new)
    kept, dropped = [], []
    for c in res.get("changes") or []:
        if not isinstance(c, dict):
            continue
        qn, qo = squash(c.get("quote_new")), squash(c.get("quote_old"))
        ok = bool(qn) and qn in sn
        if c.get("before"):
            ok = ok and bool(qo) and qo in so and not numbers_supported(str(c["before"]), old or "")
        ok = ok and not numbers_supported(str(c.get("after") or ""), new)
        (kept if ok else dropped).append(c)
    res["changes"], res["dropped"] = kept, len(dropped)
    if not kept:
        res["material"] = False
    # the headline and summary may only use numbers the texts contain
    text = " ".join(str(res.get(k) or "") for k in ("title", "summary", "effect")) + " " + \
        " ".join(str(c.get("impact") or "") for c in kept)
    missing = numbers_supported(text, (old or "") + "\n" + new)
    # differences and percentage moves worked out from proven before/after pairs are allowed
    derived = set()
    for c in kept:
        b, a = nums(c.get("before")), nums(c.get("after"))
        for x in b:
            for y in a:
                derived |= {round(abs(y - x), 2), round(abs(y - x) / x * 100, 1) if x else None, round(abs(y - x) / x * 100) if x else None}
    res["unsupported"] = [m for m in missing if nums(m) and nums(m)[0] not in derived]
    return res


def nums(t):
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", str(t or "")) if x.replace(",", "").replace(".", "").isdigit()]


def audit(carrier, name, url, old, new, note=""):
    """Compare two versions (old may be None) and return a verified verdict dict."""
    o, n = focus(old or "", new or "")
    payload = (f"Carrier: {carrier}\nDocument: {name}\nURL: {url}\n{note}\n\n"
               + (f"OLD TEXT (changed parts with context):\n{o}\n\n" if old else "OLD TEXT: none, this file has no earlier version on record.\n\n")
               + f"NEW TEXT{' (changed parts with context)' if old else ''}:\n{n}")
    try:
        res = parse_json(claude(MODEL_WRITE, AUDITOR, payload, max_tokens=2500))
    except Exception as e:
        print(f"  audit failed for {name}: {e}", file=sys.stderr)
        return None
    if not isinstance(res, dict):
        return None
    return verify(res, old or "", new or "")


def story_fields(res, carrier):
    """Turn a verified audit into story fields (changes become a before/after table in the app)."""
    ch = [{k: c.get(k) for k in ("what", "before", "after", "effective", "who", "impact")} for c in res["changes"][:10]]
    # A carrier doc we just saw change, with no effective date printed in it, is almost always live already (ZIP/zone lists,
    # rate guides and fee pages are updated when they take effect). Date it from first sighting and say so plainly.
    import datetime as _dt
    seen = _dt.date.today().isoformat()
    inferred = not res.get("act") and not any(c.get("effective") for c in ch)
    act = res.get("act") or (seen if inferred else None)
    note = (" The carrier's page doesn't state an effective date. This change was first seen on the carrier's own site on "
            + seen + ", so it is treated as in effect from then.") if inferred else ""
    return {"title": res.get("title") or f"{carrier} change", "sum": (res.get("summary") or "") + note, "plain": res.get("effect") or "",
            "imp": res.get("imp") if res.get("imp") in ("up", "down", "watch", "info") else "watch",
            "lvl": int(res.get("lvl") or 2), "cat": res.get("category") or "Guide changes", "act": act, "inferred": inferred or None, "detected": seen,
            "changes": ch, "verdict": res.get("verdict"), "unknowns": (res.get("unknowns") or [])[:4],
            "dates": [{"d": c["effective"], "w": f"{carrier}: {c.get('what', '')}"[:70], "imp": res.get("imp") if res.get("imp") in ("up", "down") else "info"}
                      for c in ch if c.get("effective")][:3]}
