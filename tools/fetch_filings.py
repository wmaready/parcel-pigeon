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


def save_any(name, r, u):
    try:
        if r.content[:4] == b"%PDF": save(name + ".txt", pdf_text(r.content), u)
        else: save(name + ".txt", to_text(r.text), u)
    except Exception as e: LOG.append(f"parse fail {u} {e}")


def slug(u):
    return re.sub(r"[^\w.-]", "_", u.split("://")[-1])[-120:]


def releases():
    """The release and filing links already in data/earnings.json (carrier sites, not sec.gov)."""
    for e in json.load(open("data/earnings.json")):
        for k in ("release", "filing"):
            u = e.get(k)
            if u and "sec.gov" not in u:
                r = get(u)
                if r: save_any(f"{e['company'].replace(' ', '')}-{e['q'].replace(' ', '')}-{k}", r, u)


def fedex_statbooks():
    for fy in (25, 26):
        for q in (1, 2, 3, 4):
            for name in (f"FedEx-Q{q}-FY{fy}-Stat-Book.pdf", f"FedEx-Q{q}-FY{fy}-Stat-Book-Final.pdf", f"Q{q}-FY{fy}-Stat-Book.pdf"):
                u = f"https://s21.q4cdn.com/665674268/files/doc_financials/20{fy}/q{q}/{name}"
                r = get(u)
                if r: save_any(f"FedEx-FY{fy}Q{q}-statbook", r, u); break


def usps():
    links = {"https://about.usps.com/newsroom/national-releases/2026/0205-usps-reports-first-quarter-fiscal-year-2026-results.pdf",
             "https://about.usps.com/newsroom/national-releases/2026/0508-usps-reports-second-quarter-fiscal-year-2026-results.pdf",
             "https://about.usps.com/newsroom/national-releases/2026/0807-usps-reports-third-quarter-fiscal-year-2026-results.pdf"}
    for y in (2024, 2025, 2026):
        for p in (f"https://about.usps.com/newsroom/national-releases/{y}/", f"https://about.usps.com/newsroom/national-releases/{y}/default.htm"):
            r = get(p)
            if not r: continue
            for h in re.findall(r'href="([^"]+)"', r.text, re.I):
                if re.search(r"reports?-(first|second|third|fourth|fiscal|quarter|.*results)", h, re.I) and re.search(r"results|fiscal", h, re.I):
                    links.add(urljoin(p, h))
    LOG.append("USPS links: " + json.dumps(sorted(links)))
    for u in sorted(links):
        r = get(u)
        if r: save_any("USPS-" + slug(u), r, u)


def pitney():
    """Pitney Bowes Parcel Shipping Index: the page and every PDF or report page it links to."""
    seen = set()
    for p in ("https://www.pitneybowes.com/us/shipping-index.html", "https://www.pitneybowes.com/us/shipping-index/parcel-shipping-index.html",
              "https://www.pitneybowes.com/us/newsroom.html"):
        r = get(p)
        if not r:
            continue
        save_any("PB-" + slug(p), r, p)
        for h in re.findall(r'href="([^"]+)"', r.text, re.I):
            u = urljoin(p, h)
            if u in seen or not re.search(r"(shipping-index|parcel-shipping|psi)", u, re.I) or "#" in u:
                continue
            seen.add(u)
            if len(seen) > 25:
                break
            rr = get(u)
            if rr:
                save_any("PB-" + slug(u), rr, u)


def diesel():
    for u in ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=GASDESW", "https://fred.stlouisfed.org/data/GASDESW.txt",
              "https://www.eia.gov/dnav/pet/pet_pri_gnd_dcus_nus_w.htm", "https://www.eia.gov/petroleum/gasdiesel/"):
        try:
            import requests as rq
            r = rq.get(u, timeout=40, headers={"User-Agent": "Mozilla/5.0 (compatible; ParcelPigeon/1.0)"})
            LOG.append(f"plain requests {r.status_code} {len(r.text)} {u}")
            (OUT / ("DIESEL-" + slug(u) + ".txt")).write_text(f"SOURCE: {u}\nSTATUS: {r.status_code}\n\n" + r.text[-6000:] + "\n\n=== HEAD ===\n" + r.text[:3000])
        except Exception as e:
            LOG.append(f"plain requests ERR {u} {e}")


def site(base, depth=1, limit=60, tag="TI"):
    """A site's page and the same-site pages it links to (carrier-updates entries, archives, PDFs)."""
    from urllib.parse import urlparse
    host = urlparse(base).netloc.replace("www.", "")
    seen, todo = set(), [base]
    for _ in range(depth + 1):
        nxt = []
        for u in todo:
            if u in seen or len(seen) >= limit:
                continue
            seen.add(u)
            r = get(u)
            if not r:
                continue
            save_any(f"{tag}-" + slug(u), r, u)
            if r.content[:4] == b"%PDF":
                continue
            for h in re.findall(r'href="([^"#]+)"', r.text, re.I):
                v = urljoin(u, h)
                if urlparse(v).netloc.replace("www.", "") == host and re.search(r"(carrier|update|rate|surcharge|fuel|gri|peak|ups|fedex|usps|dhl|amazon|ontrac|\.pdf)", v, re.I) \
                        and not re.search(r"\.(png|jpe?g|gif|svg|css|js|webp|ico)(\?|$)", v, re.I):
                    nxt.append(v)
        todo = nxt


def fuelpages():
    for u in ("https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges.page",
              "https://www.fedex.com/en-us/shipping/fuel-surcharge.html",
              "https://www.fedex.com/en-us/shipping/historical-fuel-surcharge.html",
              "https://www.dhl.com/us-en/home/express/products-and-solutions/products-and-services-overview/surcharges.html"):
        r = get(u)
        if r:
            save_any("FUEL-" + slug(u), r, u)


def upsraw():
    """UPS's fuel page as served (to find where its weekly table comes from), the flyers it links, and a few likely feeds."""
    u = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges.page"
    r = get(u)
    if not r:
        return
    (OUT / "UPSRAW-fuel-page.html").write_text(r.text[:600000])
    LOG.append(f"UPS raw page {len(r.text)} chars")
    hrefs = sorted(set(re.findall(r'(?:href|src|data-[\w-]+)="([^"]+)"', r.text)))
    keep = [h for h in hrefs if re.search(r"(fuel|surcharge|\.pdf|\.json|assets\.ups|/api/|webcontent)", h, re.I)]
    (OUT / "UPSRAW-links.txt").write_text("\n".join(keep))
    for h in keep:
        v = urljoin(u, h)
        if re.search(r"\.pdf|flyer|fuel", v, re.I) and not re.search(r"\.(png|jpe?g|svg|css|js|woff2?)(\?|$)", v, re.I):
            rr = get(v)
            if rr:
                save_any("UPSLINK-" + slug(v), rr, v)
    for c in ("https://www.ups.com/assets/resources/webcontent/en_US/fuel-surcharge.json",
              "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges/_jcr_content.json",
              "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges.model.json"):
        rr = get(c)
        if rr:
            (OUT / ("UPSFEED-" + slug(c) + ".txt")).write_text(rr.text[:200000])
    # the tables in the page's scripts
    for m in re.finditer(r"<script[^>]*src=\"([^\"]+)\"", r.text):
        v = urljoin(u, m.group(1))
        if re.search(r"fuel|surcharge", v, re.I):
            rr = get(v)
            if rr:
                (OUT / ("UPSJS-" + slug(v) + ".txt")).write_text(rr.text[:300000])


if __name__ == "__main__":
    import sys as _s
    if "--upsraw" in _s.argv:
        upsraw()
    elif "--ti" in _s.argv:
        site("https://transimpact.com/carrier-updates", depth=2, limit=80)
        fuelpages()
    elif "--diesel" in _s.argv:
        diesel()
    elif "--pb" in _s.argv:
        pitney()
    else:
        sec(1090727, "UPS", {"10-Q", "10-K", "8-K"}, True)
        sec(1048911, "FDX", {"10-Q", "10-K", "8-K"}, True)
        releases()
        fedex_statbooks()
        usps()
    (OUT / "_log.txt").write_text("\n".join(LOG))
    print("\n".join(LOG))
