"""Saved copies of carrier documents, so readers can download them in one tap, even after a carrier moves or removes a file.

Only PDFs and spreadsheets the carriers publish openly (the ones already listed in data/docs.json), saved as they are,
unaltered, under data/files/. Each document keeps its link to the carrier's own copy; the saved copy is the backup.
Kept small on purpose: files up to MAX_MB each, ARCHIVE_MB in total, a few per run, re-checked every RECHECK_DAYS.
A changed file replaces the old copy (git history keeps earlier versions). Set PP_ARCHIVE=0 to turn it off.

Usage: python archive.py [--max 6]      (alerts.py runs it every run)
"""
import datetime as dt, hashlib, os, re, sys
from common import ROOT, load, save
from fetch import fetch

FILES = ROOT / "data" / "files"
MAX_MB = float(os.environ.get("PP_ARCHIVE_MAX_MB") or 8)
ARCHIVE_MB = float(os.environ.get("PP_ARCHIVE_MB") or 150)
RECHECK_DAYS = 14
TODAY = dt.date.today()
KIND = {".pdf": ("application/pdf", b"%PDF"), ".xlsx": ("spreadsheet", b"PK")}


def ext_of(u):
    p = (u or "").split("?")[0].split("#")[0].lower()
    return next((e for e in KIND if p.endswith(e)), None)


def slug(d):
    s = re.sub(r"[^a-z0-9]+", "-", f"{d.get('c','')} {d.get('n','')}".lower()).strip("-")[:70]
    return f"{s}-{hashlib.sha1(d['u'].encode()).hexdigest()[:6]}"


def used_mb():
    return sum(f.stat().st_size for f in FILES.glob("*") if f.is_file()) / 1e6 if FILES.exists() else 0


def main(limit=6):
    if os.environ.get("PP_ARCHIVE", "1") == "0":
        print("archive: off (PP_ARCHIVE=0)"); return
    docs = load("docs.json", [])
    if not docs:
        return
    due = []
    for d in docs:
        e = ext_of(d.get("u"))
        if not e or d.get("cur") is False and d.get("f"):
            continue                                  # old versions keep the copy they already have
        last = d.get("fchk") or "2000-01-01"
        if not d.get("f") or dt.date.fromisoformat(last) < TODAY - dt.timedelta(days=RECHECK_DAYS):
            due.append((0 if not d.get("f") else 1, d.get("y") or 0, d))
    due.sort(key=lambda x: (x[0], -int(x[1] or 0)))       # never-saved first, newest years first
    FILES.mkdir(parents=True, exist_ok=True)
    done = saved = 0
    for _, _, d in due:
        if done >= limit:
            break
        done += 1
        e = ext_of(d["u"])
        d["fchk"] = TODAY.isoformat()
        try:
            r = fetch(d["u"], timeout=40)
            body = r.content
        except Exception as ex:
            print(f"  archive: couldn't fetch {d['n'][:60]}: {ex}", file=sys.stderr); continue
        if not body.startswith(KIND[e][1]):
            print(f"  archive: not a real {e} file, skipped: {d['n'][:60]}"); continue
        if len(body) > MAX_MB * 1e6:
            print(f"  archive: {len(body)/1e6:.1f} MB is over the {MAX_MB:g} MB limit: {d['n'][:60]}"); continue
        h = hashlib.sha1(body).hexdigest()
        if d.get("fh") == h and d.get("f"):
            continue                                  # unchanged since the saved copy
        path = FILES / (slug(d) + e)
        old = path.stat().st_size if path.exists() else 0
        if used_mb() - old / 1e6 + len(body) / 1e6 > ARCHIVE_MB:
            print(f"  archive: total would pass {ARCHIVE_MB:g} MB, stopping"); break
        path.write_bytes(body)
        d.update({"f": f"data/files/{path.name}", "fh": h, "fat": TODAY.isoformat(), "fsz": len(body)})
        saved += 1
        print(f"  archive: saved {d['c']}: {d['n'][:60]} ({len(body)/1e6:.1f} MB)")
    save("docs.json", docs)
    print(f"archive: {sum(1 for d in docs if d.get('f'))} saved copies, {used_mb():.0f} MB; {saved} new or updated this run")


if __name__ == "__main__":
    a = sys.argv
    main(int(a[a.index("--max") + 1]) if "--max" in a else 6)
