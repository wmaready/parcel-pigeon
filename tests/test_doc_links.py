"""B21: the Docs link checker records http_status, final_url, content_verified and checked_at. A redirect to a home
page, an error.page or an "Access denied"/"Request Access" title is not verified; a blocked check is never "broken";
a 200 alone is never "confirmed". The cases are the ones the review found. No network."""
import pytest
import audit as A

GUIDE = "https://www.ups.com/assets/resources/webcontent/en_US/2025-hundredweight-rates-preview.pdf"


def test_brief_cases():
    r = A.classify_link(GUIDE, "2025 UPS Hundredweight rates preview", 200, "https://www.ups.com/error.page", "text/html", "UPS")
    assert r["state"] == "wrong-page" and r["content_verified"] is False
    gls = A.classify_link("https://gls-group.com/US/en/fuel-surcharge-matrix-dec-2025.pdf", "GLS US fuel surcharge matrix",
                          200, "https://gls-group.com/US/en/home/", "text/html", "GLS US | Home")
    assert gls["state"] == "wrong-page" and gls["content_verified"] is False
    veho = A.classify_link("https://www.shipveho.com/knowledge-hub/service-guide-last-mile-delivery", "Veho service guide",
                           200, "https://www.shipveho.com/knowledge-hub", "text/html", "Knowledge Hub | Veho")
    assert veho["state"] == "wrong-page"
    for title in ("Access Denied", "Request Access | FedEx"):
        assert A.classify_link("https://www.fedex.com/x/guide.html", "FedEx guide", 200, "https://www.fedex.com/x/guide.html",
                               "text/html", title)["content_verified"] is False


def test_blocked_is_never_broken_and_200_is_never_confirmed_alone():
    for status in (403, 429, 503, None):
        r = A.classify_link(GUIDE, "guide", status, GUIDE)
        assert r["state"] == "blocked" and r["content_verified"] is None
    assert A.classify_link(GUIDE, "guide", 200, GUIDE, blocked=True)["state"] == "blocked"
    assert A.classify_link(GUIDE, "guide", 404, GUIDE)["state"] == "broken"
    pdf = A.classify_link(GUIDE, "2025 UPS Hundredweight rates preview", 200, GUIDE, "application/pdf")
    assert pdf["state"] == "opens" and pdf["content_verified"] is None         # opens; content not confirmed
    page = A.classify_link("https://www.ups.com/us/en/sbr", "UPS Small Business Rates page", 200, "https://www.ups.com/us/en/sbr",
                           "text/html", "Small Business Rates | UPS")
    assert page["content_verified"] is True                                    # the title names the document


class Resp:
    def __init__(self, status, url, ctype, body=b""):
        self.status_code, self.url, self.headers, self._b = status, url, {"content-type": ctype}, body

    def iter_content(self, n):
        yield self._b

    def close(self):
        pass


def test_check_records_the_four_fields(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **k: Resp(200, "https://gls-group.com/US/en/home/", "text/html",
                                                                b"<html><title>GLS US | Home</title><body>" + b"x" * 5000 + b"</body></html>"))
    rec = A.check_doc_link("https://gls-group.com/US/en/fuel-2025.pdf", "GLS US fuel surcharge, Jul 2025")
    assert rec["http_status"] == 200 and rec["final_url"] == "https://gls-group.com/US/en/home/"
    assert rec["content_verified"] is False and rec["checked_at"][:2] == "20"
    def boom(url, **k):
        raise requests.ConnectionError("reset")
    monkeypatch.setattr(requests, "get", boom)
    rec = A.check_doc_link(GUIDE, "guide")
    assert rec["state"] == "blocked" and rec["content_verified"] is None and rec["http_status"] is None
