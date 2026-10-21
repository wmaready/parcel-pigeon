"""Carrier pages: a bot wall must never be saved as a rate guide."""
import fetch as F

FEDEX_BLOCK = ("| | We're sorry, we can't process your request right now. It appears you don't have permission to view this webpage. "
               "Incident Number: 18.f0f12417.1791775305.f5d4bfc2 For assistance with your shipping needs, you can call us anytime "
               "at 1.800.GoFedEx 1.800.463.3339 or visit fedex.com. Thank you for choosing FedEx. |")
UPS_BLOCK = ('Access Denied\nYou don\'t have permission to access "/us/en/support/shipping-support/shipping-costs-rates" on this '
             'server.\n0.47a7cb17.1791775231.13ae51fc')
REAL_PAGE = "OnTrac Rates & Surcharges\nOnTrac Shipping Rates\n" + "Zone 2 1 lb $9.10 residential surcharge applies\n" * 200


def test_block_pages_are_recognized():
    assert F.is_blocked(FEDEX_BLOCK)
    assert F.is_blocked(UPS_BLOCK)
    assert F.is_blocked("<html><body><h1>Access Denied</h1></body></html>")
    assert F.is_blocked("", status=403)


def test_real_pages_are_not_blocked():
    assert not F.is_blocked(REAL_PAGE)
    # a long real page that merely mentions the words is still real
    assert not F.is_blocked("Access denied claims are rare. " + "rate table line\n" * 500)


def test_pdf_checks():
    assert not F.is_blocked("", 200, True, b"%PDF-1.7 ...")
    assert F.is_blocked("", 200, True, b"<html>Access Denied</html>")


def page(content, via="direct", when=None, ctype="text/html"):
    return lambda url, timeout: F.Page(content, {"content-type": ctype}, url, via, when)


def test_falls_back_past_a_block(monkeypatch):
    monkeypatch.setattr(F, "ROUTES", [page(FEDEX_BLOCK.encode()), lambda u, t: None,
                                      page(b"<html><body>" + b"Rate guide text " * 300 + b"</body></html>", "archive", "2026-10-19")])
    got = F.fetch("https://www.fedex.com/x.html")
    assert got.via == "archive" and got.when == "2026-10-19"


def test_all_routes_blocked_raises(monkeypatch):
    monkeypatch.setattr(F, "ROUTES", [page(UPS_BLOCK.encode())])
    try:
        F.fetch("https://www.ups.com/x")
    except F.Blocked:
        return
    raise AssertionError("a bot wall must raise Blocked")


def test_pdf_wanted_html_returned(monkeypatch):
    monkeypatch.setattr(F, "ROUTES", [page(b"<html>Access Denied</html>"), page(b"%PDF-1.4 real", "proxy", ctype="application/pdf")])
    assert F.fetch("https://www.fedex.com/a/FedEx_Standard_List_Rates_2027.pdf").via == "proxy"
