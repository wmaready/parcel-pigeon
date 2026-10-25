"""One-off: download the carriers' own quarterly reports (2024 on) as plain text into filings/, so package volumes can
be copied from the source by hand. Runs in GitHub Actions only (the build sandbox can't reach these sites)."""
import html, io, json, os, re, sys, time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests as cr

OUT = Path("filings")
OUT.mkdir(exist_ok=True)
LOG = []
SINCE = "2024-01-01"


class Text(HTMLParser):
    """HTML to text that keeps table rows on one line, cells split by ' | '."""
    def __init__(self):
        super().__init__(); self.out, self.row, self.cell, self.skip = [], None, [], 0
    def handle_starttag(self, t, a):
        if t in ("script", "style"): self.skip += 1
        elif t == "tr": self.row = []
        elif t in ("td", "th"): self.cell = []
        elif t in ("br", "p", "div") and self.row is None: self.out.append("\n")
    def handle_endtag(self, t):
        if t in ("script", "style"): self.skip -= 1
        elif t in ("td", "th") and self.row is not None:
            c = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            if c: self.row.append(c)
        elif t == "tr" and self.row is not None:
            if self.row: self.out.append("\n" + " | ".join(self.row) + "\n")
            self.row = None
        elif t in ("p", "div") and self.row is None: self.out.append("\n")
    def handle_data(self, d):
        if self.skip: return
        (self.cell if self.row is not None else self.out).append(d)


def to_text(raw):
    p = Text(); p.feed(raw); t = "".join(p.out)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", html.unescape(t)))


def pdf_text(b):
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(b)).pages)


def get(url, **k):
    for i in range(3):
        try:
            r = cr.get(url, timeout=60, impersonate="chrome", **k)
            if r.status_code == 200:
                return r
            LOG.append(f"{r.status_code} {url}")
        except Exception as e:
            LOG.append(f"ERR {url} {e}")
        time.sleep(2 + i * 3)
    return None


def save(name, text, src):
    (OUT / name).write_text(f"SOURCE: {src}\n\n{text}")
    LOG.append(f"saved {name} ({len(text)} chars) {src}")


def sec(cik, slug, forms, want_ex99):
    ua = os.environ.get("SEC_CONTACT", "").strip()
    if "@" not in ua:
        LOG.append("SEC skipped: SEC_CONTACT secret not set"); return
    H = {"User-Agent": f"ParcelPigeon filings reader {ua}", "Accept-Encoding": "gzip, deflate"}
    r = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=H)
    if not r: return
    f = r.json()["filings"]["recent"]
    for form, date, acc, doc, items in zip(f["form"], f["filingDate"], f["accessionNumber"], f["primaryDocument"], f.get("items", [""] * len(f["form"]))):
        if date < SINCE or form not in forms: continue
        if form == "8-K" and "2.02" not in (items or ""): continue
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/"
        time.sleep(0.3)
        if form == "8-K" and want_ex99:
            ix = get(base + "index.json", headers=H)
            if not ix: continue
            for it in ix.json()["directory"]["item"]:
                n = it["name"]
                if re.search(r"ex-?99", n, re.I) and n.lower().endswith((".htm", ".html")):
                    time.sleep(0.3); d = get(base + n, headers=H)
                    if d: save(f"{slug}-8K-{date}-{n}.txt", to_text(d.text), base + n)
        elif form != "8-K":
            d = get(base + doc, headers=H)
            if d: save(f"{slug}-{form.replace('/', '')}-{date}.txt", to_text(d.text), base + doc)


def usps():
    pages = ["https://about.usps.com/what/financials/financial-conditions-results-reports/",
             "https://about.usps.com/what/financials/10k-reports/", "https://about.usps.com/what/financials/10q-reports/"]
    links = set()
    for p in pages:
        r = get(p)
        if not r: continue
        for h in re.findall(r'href="([^"]+\.pdf)"', r.text, re.I):
            u = urljoin(p, h)
            if re.search(r"(10-?[kq]|fy-?20(2[4-6]))", u, re.I): links.add(u)
    LOG.append("USPS links: " + json.dumps(sorted(links)))
    for u in sorted(links):
        if not re.search(r"202[4-6]", u): continue
        r = get(u)
        if r:
            try: save("USPS-" + re.sub(r"[^\w.-]", "_", u.split("/")[-1]) + ".txt", pdf_text(r.content), u)
            except Exception as e: LOG.append(f"PDF fail {u} {e}")


if __name__ == "__main__":
    sec(1090727, "UPS", {"10-Q", "10-K", "8-K"}, True)
    sec(1048911, "FDX", {"10-Q", "10-K", "8-K"}, True)
    usps()
    (OUT / "_log.txt").write_text("\n".join(LOG))
    print("\n".join(LOG))
