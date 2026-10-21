"""Company and regulator sources: SEC filings and the Federal Register come in as tier 0, with readable titles."""
import datetime as dt
import news as N

TODAY = dt.date.today().isoformat()
EDGAR = f"""<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>UNITED PARCEL SERVICE INC</title>
<entry><title>8-K - Current report</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1090727/000109072726000045/0001090727-26-000045-index.htm"/>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; {TODAY} &lt;b&gt;Item 7.01: Regulation FD Disclosure&lt;/b&gt; Item 9.01</summary>
<updated>{TODAY}T16:05:12-04:00</updated></entry></feed>"""
FEDREG = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Postal Service</title>
<item><title>New Mailing Standards for Domestic Mailing Services Products</title>
<link>https://www.federalregister.gov/documents/2026/10/20/2026-12345/new-mailing-standards</link>
<description>The Postal Service proposes to amend Mailing Standards for package dimensional weight.</description>
<pubDate>{dt.date.today().strftime('%a, %d %b %Y')} 00:00:00 -0400</pubDate></item></channel></rss>"""
INDEX = '<a href="/ix?doc=/Archives/edgar/data/1090727/000109072726000045/ups-20261020.htm">8-K</a> <a href="/Archives/edgar/data/1090727/000109072726000045/ex99-1.htm">EX-99.1</a>'
RELEASE = "<html><body><p>" + "UPS announces 2027 rates with an average net increase of 5.9 percent. " * 20 + "</p></body></html>"


class R:
    def __init__(self, text):
        self.text, self.content = text, text.encode("latin-1", "replace")


def test_primary_feeds_are_tier_0(data_dir, monkeypatch):
    cfg = {"primary": [{"name": "SEC: UPS 8-K", "kind": "edgar", "company": "UPS", "url": "https://sec.example/ups"},
                       {"name": "Federal Register: USPS", "kind": "fedreg", "url": "https://fr.example/usps"}],
           "direct": [{"name": "Trade", "url": "https://trade.example/feed"}], "discovery": ["parcel"]}
    calls = []
    monkeypatch.setattr(N.requests, "get", lambda url, **k: (calls.append(url), R(EDGAR))[1])
    monkeypatch.setattr(N, "get", lambda url, **k: (calls.append(url), R(FEDREG))[1])
    items = N.collect(cfg, primary_only=True)
    assert "https://trade.example/feed" not in calls, "the hourly run reads only company and regulator sources"
    sec = next(i for i in items if "SEC" in i["src"])
    assert sec["tier"] == 0 and sec["title"].startswith("UPS files SEC Form 8-K: ") and "7.01" in sec["title"]
    fr = next(i for i in items if "Mailing Standards" in i["title"])
    assert fr["tier"] == 0


def test_sec_filing_reads_the_press_release(monkeypatch):
    pages = {"index": INDEX, "ex99": RELEASE}
    monkeypatch.setattr(N.requests, "get", lambda url, **k: R(pages["ex99" if "ex99" in url else "index"]))
    text, url = N.article_text("https://www.sec.gov/Archives/edgar/data/1090727/000109072726000045/0001090727-26-000045-index.htm")
    assert url.endswith("ex99-1.htm") and "5.9 percent" in text
