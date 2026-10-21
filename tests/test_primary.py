"""Company and regulator sources: SEC filings and the Federal Register come in as tier 0, with readable titles."""
import datetime as dt, json
import news as N

TODAY = dt.date.today().isoformat()
EDGAR = {"filings": {"recent": {"form": ["8-K", "10-Q", "8-K"], "filingDate": [TODAY, TODAY, "2020-01-01"],
          "accessionNumber": ["0001090727-26-000045", "0001090727-26-000044", "0001090727-20-000001"],
          "items": ["2.02,7.01,9.01", "", "8.01"]}}}
FEDREG = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Postal Service</title>
<item><title>New Mailing Standards for Domestic Mailing Services Products</title>
<link>https://www.federalregister.gov/documents/2026/10/20/2026-12345/new-mailing-standards</link>
<description>The Postal Service proposes to amend Mailing Standards for package dimensional weight.</description>
<pubDate>{dt.date.today().strftime('%a, %d %b %Y')} 00:00:00 -0400</pubDate></item></channel></rss>"""
INDEX = '<a href="/ix?doc=/Archives/edgar/data/1090727/000109072726000045/ups-20261020.htm">8-K</a> <a href="/Archives/edgar/data/1090727/000109072726000045/ex99-1.htm">EX-99.1</a>'
RELEASE = "<html><body><p>" + "UPS announces 2027 rates with an average net increase of 5.9 percent. " * 20 + "</p></body></html>"


class R:
    def __init__(self, text):
        self.text = text if isinstance(text, str) else json.dumps(text)
        self.content, self._j = self.text.encode("latin-1", "replace"), text
    def json(self):
        return self._j
    def raise_for_status(self):
        pass


def test_primary_feeds_are_tier_0(data_dir, monkeypatch):
    cfg = {"primary": [{"name": "SEC: UPS 8-K", "kind": "edgar", "company": "UPS", "url": "https://data.sec.gov/submissions/CIK0001090727.json"},
                       {"name": "Federal Register: USPS", "kind": "fedreg", "url": "https://fr.example/usps"}],
           "direct": [{"name": "Trade", "url": "https://trade.example/feed"}], "discovery": ["parcel"]}
    calls = []
    monkeypatch.setattr(N.requests, "get", lambda url, **k: (calls.append(url), R(EDGAR))[1])
    monkeypatch.setattr(N, "get", lambda url, **k: (calls.append(url), R(FEDREG))[1])
    items = N.collect(cfg, primary_only=True)
    assert "https://trade.example/feed" not in calls, "the hourly run reads only company and regulator sources"
    sec = [i for i in items if "SEC" in i["src"]]
    assert len(sec) == 1, "only recent 8-Ks: not the 10-Q, not the 2020 filing"
    assert sec[0]["tier"] == 0 and sec[0]["title"] == "UPS files SEC Form 8-K: results of operations; a disclosure to investors"
    assert sec[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1090727/000109072726000045/0001090727-26-000045-index.htm"
    fr = next(i for i in items if "Mailing Standards" in i["title"])
    assert fr["tier"] == 0


def test_sec_filing_reads_the_press_release(monkeypatch):
    pages = {"index": INDEX, "ex99": RELEASE}
    monkeypatch.setattr(N.requests, "get", lambda url, **k: R(pages["ex99" if "ex99" in url else "index"]))
    text, url = N.article_text("https://www.sec.gov/Archives/edgar/data/1090727/000109072726000045/0001090727-26-000045-index.htm")
    assert url.endswith("ex99-1.htm") and "5.9 percent" in text
