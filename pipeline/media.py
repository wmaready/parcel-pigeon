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
        return None                                   # raster only (no SVG renderer in the runner)
    im = Image.open(io.BytesIO(r.content))
    if getattr(im, "n_frames", 1) > 1 or im.format == "ICO":
        try:
            im.size = max(im.info.get("sizes", [im.size]))   # largest icon in an .ico
        except Exception:
            pass
    im.load()
    if min(im.size) < min_side:
        return None
    return im


def logo_candidates(domain):
    host = domain.split("/")[0]
    base = f"https://{host}/"
    out = []
    try:
        html = get(base, timeout=20).text
        for tag in re.findall(r"<link[^>]+>", html, re.I):
            rel = (re.search(r'rel=["\']([^"\']+)', tag, re.I) or [None, ""])[1].lower()
            href = (re.search(r'href=["\']([^"\']+)', tag, re.I) or [None, ""])[1]
            if not href or "icon" not in rel:
                continue
            sz = re.search(r'sizes=["\'](\d+)x(\d+)', tag, re.I)
            score = (int(sz.group(1)) if sz else 0) + (500 if "apple-touch" in rel else 0)
            out.append((score, urllib.parse.urljoin(base, href)))
    except Exception:
        pass
    out += [(400, base + "apple-touch-icon.png"), (1, base + "favicon.ico")]
    seen, ordered = set(), []
    for _, u in sorted(out, reverse=True):
        if u not in seen:
            seen.add(u); ordered.append(u)
    return ordered


def save_logo(pid, im):
    from PIL import Image
    im = im.convert("RGBA")
    bbox = im.getbbox()                               # trim empty transparent border
    if bbox:
        im = im.crop(bbox)
    im.thumbnail((112, 112), Image.LANCZOS)
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    canvas.paste(im, ((128 - im.width) // 2, (128 - im.height) // 2), im)
    LOGO_DIR.mkdir(exist_ok=True)
    canvas.save(LOGO_DIR / f"{pid}.png", optimize=True)


def logos(limit=25):
    seed, mp = load("seed.json", {}), load("players.json", {"players": []})
    sites = dict(seed.get("psite") or {})
    for p in mp.get("players", []):
        if p.get("site") and not p.get("pending"):
            sites.setdefault(p["id"], p["site"])
    idx = load("logos.json", {})
    by_host = {}
    for pid, rec in idx.items():
        if rec.get("f") and rec.get("host"):
            by_host[rec["host"]] = rec
    due = [pid for pid in sites if pid not in idx or
           (dt.date.fromisoformat(idx[pid].get("checked", "2000-01-01")) < TODAY - dt.timedelta(days=30))]
    done = 0
    for pid in due:
        if done >= limit:
            break
        host = sites[pid].split("/")[0].lower().removeprefix("www.")
        if host in by_host and by_host[host].get("checked") == TODAY.isoformat():   # same company site as one done today
            src = LOGO_DIR / by_host[host]["f"].split("/")[-1]
            (LOGO_DIR / f"{pid}.png").write_bytes(src.read_bytes())
            idx[pid] = {**by_host[host], "f": f"data/logos/{pid}.png"}
            continue
        done += 1
        rec = {"checked": TODAY.isoformat(), "host": host}
        for u in logo_candidates(sites[pid])[:6]:
            try:
                im = _img(u)
            except Exception:
                continue
            if im is not None:
                save_logo(pid, im)
                rec.update({"f": f"data/logos/{pid}.png", "src": u})
                break
        idx[pid] = rec
        if rec.get("f"):
            by_host[host] = rec
        print(f"  logo {pid}: {'ok' if rec.get('f') else 'none found'}")
    save("logos.json", idx)
    print(f"logos: {sum(1 for r in idx.values() if r.get('f'))} on file, checked {done} this run")


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
