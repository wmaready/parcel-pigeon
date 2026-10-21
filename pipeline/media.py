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
    then the app icons. Wordmarks read far better than tiny round app icons. A unit with its own page on a parent's
    site (fedex.com/freight) is read from that page, so it finds the unit's own mark, not the parent's."""
    host = domain.split("/")[0]
    base = f"https://{host}/"
    page = f"https://{domain.rstrip('/')}/" if "/" in domain.strip("/") else base
    out = []
    try:
        html = get(page, timeout=20).text
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
            if sz and int(sz.group(1)) < 96:
                continue                                  # tiny tab icons look blurry in the app
            score = (int(sz.group(1)) if sz else 0) + (500 if "apple-touch" in rel else 0) + (300 if href.lower().endswith(".svg") else 0)
            out.append((min(score, 700), urllib.parse.urljoin(base, href)))
    except Exception:
        pass
    out += [(400, base + "apple-touch-icon.png")]          # no favicon.ico: too small to look sharp
    # sites that block page readers still publish their icon: the largest one the site declares, via the public
    # favicon services (anything under 48px, including their blank default, is rejected by _img)
    out += [(300, f"https://www.google.com/s2/favicons?domain={host}&sz=256"), (250, f"https://icons.duckduckgo.com/ip3/{host}.ico")]
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


def looks_like_photo(got, url):
    """Social and banner images sometimes sit where a logo should: wide photos with no 'logo' in the name."""
    kind, obj = got
    if kind != "img" or "logo" in url.lower():
        return False
    w, h = obj.size
    return min(w, h) >= 400 and 1.2 < w / h < 2.4


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
    if not idx.get("_v3"):
        # one-time cleanup: a logo file named for another company was copied from a shared site (a unit showing its
        # parent's logo); drop those, and recheck everything with the stricter finder, keeping good logos meanwhile
        for pid, rec in list(idx.items()):
            if isinstance(rec, dict):
                src = (rec.get("src") or "").lower()
                photo_like = rec.get("f", "").endswith(".png") and not re.search(r"logo|icon|brand|mark", src) and 1.2 < float(rec.get("ar") or 0) < 2.4
                if rec.get("f") and (rec["f"].rsplit("/", 1)[-1].rsplit(".", 1)[0] != pid or photo_like):
                    for k in ("f", "ar", "src"):
                        rec.pop(k, None)
                rec["checked"] = "2000-01-01"
        idx["_v3"] = True
    if not idx.get("_v4"):
        for pid, rec in idx.items():                  # one-time: retry every company still without a logo, with the new sources
            if isinstance(rec, dict) and not rec.get("f"):
                rec["checked"] = "2000-01-01"
        idx["_v4"] = True
    due = [pid for pid in sites if pid not in idx or
           (dt.date.fromisoformat(idx[pid].get("checked", "2000-01-01")) < TODAY - dt.timedelta(days=30))]
    done = 0
    for pid in due:
        if done >= limit:
            break
        host = sites[pid].split("/")[0].lower().removeprefix("www.")
        done += 1
        old = idx.get(pid) if isinstance(idx.get(pid), dict) else {}
        rec = {"checked": TODAY.isoformat(), "host": host}
        rejected = set()
        taken = {r.get("src") for k, r in idx.items() if k != pid and isinstance(r, dict) and r.get("src")}
        for u in logo_candidates(sites[pid])[:8]:
            if u in taken:
                continue                                  # another company's logo (usually the parent's): not this one's
            try:
                got = _img(u)
            except Exception:
                continue
            if got is None:
                continue
            if looks_like_photo(got, u):
                rejected.add(u); continue
            res = save_logo(pid, got)
            if res:
                rec.update({"f": f"data/logos/{pid}.{res[0]}", "ar": res[1], "src": u})
                break
        if not rec.get("f") and old.get("f") and old.get("src") not in rejected and old.get("src") not in taken:
            rec.update({k: old[k] for k in ("f", "ar", "src") if k in old})   # keep a good logo we already had
        idx[pid] = rec
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
        got = _img(url, min_side=360)          # ("img", picture) or ("svg", text) or None
    except Exception:
        return None
    im = got[1] if got and got[0] == "img" else None
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
