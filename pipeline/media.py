"""Logos and story photos, stored with the site so pages stay fast and nothing breaks when a source changes.

Logos: each company's own logo from its own website (apple-touch-icon or the largest site icon), trimmed and centered
on a 128x128 transparent square at data/logos/<id>.png. Used unaltered, only to identify the company. Re-checked monthly.

Photos: only images a company, government body or union published with its own announcement (og:image on its page),
never trade-press photos. Saved as a wide 960x540 crop (data/img/<id>-w.webp) and a 240px square thumbnail (data/img/<id>-s.webp),
credited "Image: <source>".

Usage: python media.py [--logos 25] [--photos 6]   (alerts.py runs it every run with small batches)
"""
import datetime as dt, io, re, sys, urllib.parse
from common import ROOT, load, save, get, is_primary

LOGO_DIR, IMG_DIR = ROOT / "data" / "logos", ROOT / "data" / "img"   # under data/ so the workflows keep them
TODAY = dt.date.today()


def _img(url, min_side=48):
    from PIL import Image
    r = get(url, timeout=25)
    ctype = r.headers.get("content-type", "").lower()
    if "svg" in ctype or url.lower().split("?")[0].endswith(".svg"):
        return ("svg", r.text)
    im = Image.open(io.BytesIO(r.content))
    if getattr(im, "n_frames", 1) > 1 or im.format == "ICO":
        try:
            im.size = max(im.info.get("sizes", [im.size]))   # largest icon in an .ico
        except Exception:
            pass
    im.load()
    if min(im.size) < min_side:
        return None
    return ("img", im)


def logo_candidates(domain):
    """Best first: the logo the site itself declares (JSON-LD), the header logo image (often a crisp SVG wordmark),
    then the app icons. Wordmarks read far better than tiny round app icons."""
    host = domain.split("/")[0]
    base = f"https://{host}/"
    out = []
    try:
        html = get(base, timeout=20).text
        for m in re.finditer(r'"logo"\s*:\s*(?:\{[^}]*?"url"\s*:\s*)?"([^"]+)"', html):
            out.append((900, urllib.parse.urljoin(base, m.group(1))))
        head = html[:200000]
        for tag in re.findall(r"<img[^>]+>", head, re.I):
            attrs = tag.lower()
            if "logo" not in attrs:
                continue
            src = (re.search(r'(?:data-src|src)=["\']([^"\']+)', tag, re.I) or [None, ""])[1]
            if not src or src.startswith("data:") and "svg" not in src[:30]:
                continue
            score = 800 + (60 if src.lower().split("?")[0].endswith(".svg") else 0) + (30 if re.search(r"header|nav|brand", attrs) else 0)
            out.append((score, urllib.parse.urljoin(base, src)))
        for tag in re.findall(r"<link[^>]+>", html, re.I):
            rel = (re.search(r'rel=["\']([^"\']+)', tag, re.I) or [None, ""])[1].lower()
            href = (re.search(r'href=["\']([^"\']+)', tag, re.I) or [None, ""])[1]
            if not href or "icon" not in rel:
                continue
            sz = re.search(r'sizes=["\'](\d+)x(\d+)', tag, re.I)
            score = (int(sz.group(1)) if sz else 0) + (500 if "apple-touch" in rel else 0) + (300 if href.lower().endswith(".svg") else 0)
            out.append((min(score, 700), urllib.parse.urljoin(base, href)))
    except Exception:
        pass
    out += [(400, base + "apple-touch-icon.png"), (1, base + "favicon.ico")]
    seen, ordered = set(), []
    for _, u in sorted(out, reverse=True):
        if u not in seen:
            seen.add(u); ordered.append(u)
    return ordered


def clean_svg(text):
    """Keep only drawing: no scripts, event handlers or outside references. Returns (svg, aspect) or None."""
    t = re.sub(r"<\?xml[^>]*>|<!DOCTYPE[^>]*>|<!--.*?-->", "", text or "", flags=re.S)
    t = re.sub(r"<(script|foreignObject|iframe|object|embed)\b.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", t, flags=re.I)
    t = re.sub(r"(xlink:)?href\s*=\s*[\"'](?!#|data:image/(?:png|jpe?g|gif|webp))[^\"']*[\"']", "", t, flags=re.I)
    m = re.search(r"<svg\b[^>]*>", t, re.I)
    if not m or len(t) > 300000:
        return None
    vb = re.search(r'viewBox=["\']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', m.group(0), re.I)
    if vb:
        w, h = float(vb.group(1)), float(vb.group(2))
    else:
        w = re.search(r'width=["\']([\d.]+)', m.group(0)); h = re.search(r'height=["\']([\d.]+)', m.group(0))
        if not (w and h):
            return None
        w, h = float(w.group(1)), float(h.group(1))
        t = t.replace(m.group(0), m.group(0)[:-1] + f' viewBox="0 0 {w:g} {h:g}">', 1)
    if not h:
        return None
    return t[t.lower().index("<svg"):], w / h


def save_logo(pid, got):
    """Save a logo trimmed to its edges, keeping its shape, and return its width/height ratio."""
    from PIL import Image
    LOGO_DIR.mkdir(exist_ok=True)
    kind, obj = got
    if kind == "svg":
        c = clean_svg(obj)
        if not c:
            return None
        (LOGO_DIR / f"{pid}.svg").write_text(c[0])
        return "svg", round(c[1], 3)
    im = obj.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 0))
    bbox = im.getbbox()                               # trim transparent border
    if bbox:
        im = im.crop(bbox)
    # also trim a plain white border
    from PIL import ImageChops
    diff = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, (255, 255, 255)))
    bb2 = diff.getbbox()
    if bb2 and (bb2[2] - bb2[0]) > 8 and (bb2[3] - bb2[1]) > 8:
        im = im.crop(bb2)
    im.thumbnail((480, 160) if im.width > im.height * 1.6 else (160, 160), Image.LANCZOS)
    im.save(LOGO_DIR / f"{pid}.png", optimize=True)
    return "png", round(im.width / max(1, im.height), 3)


def logos(limit=25):
    seed, mp = load("seed.json", {}), load("players.json", {"players": []})
    sites = dict(seed.get("psite") or {})
    for p in mp.get("players", []):
        if p.get("site") and not p.get("pending"):
            sites.setdefault(p["id"], p["site"])
    for pid, site in load("sites.json", {}).items():         # looked up by players.backfill_sites
        if site:
            sites.setdefault(pid, site)
    idx = load("logos.json", {})
    if not idx.get("_v2"):
        idx = {"_v2": True}                           # redo every logo once with the better finder
    by_host = {}
    for pid, rec in idx.items():
        if isinstance(rec, dict) and rec.get("f") and rec.get("host"):
            by_host[rec["host"]] = rec
    due = [pid for pid in sites if pid not in idx or
           (dt.date.fromisoformat(idx[pid].get("checked", "2000-01-01")) < TODAY - dt.timedelta(days=30))]
    done = 0
    for pid in due:
        if done >= limit:
            break
        host = sites[pid].split("/")[0].lower().removeprefix("www.")
        if host in by_host and by_host[host].get("checked") == TODAY.isoformat():   # same company site as one done today
            idx[pid] = dict(by_host[host]); continue
        done += 1
        rec = {"checked": TODAY.isoformat(), "host": host}
        for u in logo_candidates(sites[pid])[:8]:
            try:
                got = _img(u)
            except Exception:
                continue
            if got is None:
                continue
            res = save_logo(pid, got)
            if res:
                rec.update({"f": f"data/logos/{pid}.{res[0]}", "ar": res[1], "src": u})
                break
        idx[pid] = rec
        if rec.get("f"):
            by_host[host] = rec
        print(f"  logo {pid}: {'ok ' + rec['f'].rsplit('.',1)[1] if rec.get('f') else 'none found'}")
    save("logos.json", idx)
    have = [k for k, r in idx.items() if isinstance(r, dict) and r.get("f")]
    miss = sorted(k for k, r in idx.items() if isinstance(r, dict) and not r.get("f"))
    allp = seed.get("players", []) + mp.get("players", [])
    nosite = sorted({p["n"] for p in allp if p.get("id") not in sites and not p.get("pending")})
    save("logos_missing.json", {"no_logo_found": miss, "no_website_on_file": nosite})
    print(f"logos: {len(have)} on file, {len(miss)} not found, {len(nosite)} without a website; checked {done} this run")


def story_photo(url, sid):
    """Download a company's own announcement image and save the wide and square versions. Returns (wide, square) or None."""
    from PIL import Image, ImageOps
    try:
        im = _img(url, min_side=360)
    except Exception:
        return None
    if im is None or im.width < 600:
        return None
    im = im.convert("RGB")
    IMG_DIR.mkdir(exist_ok=True)
    ImageOps.fit(im, (960, 540), Image.LANCZOS, centering=(0.5, 0.42)).save(IMG_DIR / f"{sid}-w.webp", quality=78, method=6)
    ImageOps.fit(im, (240, 240), Image.LANCZOS, centering=(0.5, 0.45)).save(IMG_DIR / f"{sid}-s.webp", quality=76, method=6)
    return f"data/img/{sid}-w.webp", f"data/img/{sid}-s.webp"


def photos(limit=6):
    """Recent live stories from company sources that don't have a photo yet."""
    from news import lead_image
    live = load("news.json", [])
    since = (TODAY - dt.timedelta(days=14)).isoformat()
    tried = set(load("photos_tried.json", []))
    n = 0
    for s in live:
        if n >= limit:
            break
        if s.get("img") or s["id"] in tried or (s.get("date") or "") < since:
            continue
        tried.add(s["id"])
        for sx in s.get("srcs") or []:
            if not is_primary(sx.get("url")):
                continue
            u = lead_image(sx["url"])
            got = story_photo(u, s["id"]) if u else None
            if got:
                s["img"], s["thumb"], s["imgc"] = got[0], got[1], f"Image: {sx.get('src') or 'company'}"
                print(f"  photo: {s['title'][:70]}")
                break
        n += 1
    save("news.json", live)
    save("photos_tried.json", sorted(tried)[-4000:])


if __name__ == "__main__":
    a = sys.argv
    logos(int(a[a.index("--logos") + 1]) if "--logos" in a else 25)
    photos(int(a[a.index("--photos") + 1]) if "--photos" in a else 6)
