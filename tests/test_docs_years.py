"""Docs library: carrier, then year (newest first) under clear year headers; each document filed under the year it states
for itself; the same file never listed twice."""
import json, re
import pytest
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local web server fixture)
from test_polish import app


def test_doc_year_rule():
    from common import doc_year
    assert doc_year({"c": "UPS", "n": "2026 UPS Rate Guide", "y": 2025, "u": "https://x/a.pdf"}) == 2026
    assert doc_year({"c": "UPS", "n": "UPS Rate Guide", "y": None, "u": "https://x/2026-rate-guide.pdf"}) == 2026
    # a year inside a full date is a date, not the document's year
    assert doc_year({"c": "FedEx", "n": "FedEx One Rate pricing (agreements signed before Aug 1, 2018)", "y": 2025, "u": "https://x/p.html"}) == 2025
    assert doc_year({"c": "UPS", "n": "2026 UPS Retail Rate Guide (Dec 22, 2025 edition)", "y": 2026, "u": "https://x/r.pdf"}) == 2026
    # the upload folder dates a file that states no year of its own
    assert doc_year({"c": "Spee-Dee", "n": "Spee-Dee press release", "y": None, "u": "https://s.com/wp-content/uploads/2025/08/PR.pdf"}) == 2025
    # market reports keep their publication year
    assert doc_year({"c": "Reports", "n": "Parcel volume reached 23.9 billion in 2025", "y": 2026, "u": "https://x/r.pdf"}) == 2026
    assert doc_year({"c": "UPS", "n": "UPS terms", "y": None, "u": "https://x/terms.htm"}) is None


def test_doc_key_matches_the_same_file_at_two_addresses():
    from common import doc_key
    a = "https://assets.ups.com/adobe/assets/urn:aaid:aem:356d938a-4f0a-4c71-b50e-bdd890f50b47/original/as/daily-rates-us-en.pdf"
    b = "https://delivery-p55671-e392469.adobeaemcloud.com/adobe/assets/urn:aaid:aem:356d938a-4f0a-4c71-b50e-bdd890f50b47/original/as/daily-rates-us-en.pdf"
    assert doc_key(a) == doc_key(b) != doc_key(a.replace(".pdf", ".xlsx"))
    assert doc_key("https://pe.usps.com/a/Notice%20123.pdf?v=2") == doc_key("http://www.pe.usps.com/a/Notice 123.pdf")


def test_docs_data_is_clean():
    from common import doc_key, doc_year
    docs = json.loads((ROOT / "data/docs.json").read_text())
    keys = [doc_key(d["u"]) for d in docs if d.get("u")]
    assert len(keys) == len(set(keys)), "the same file is listed twice"
    wrong = [(d["n"], d.get("y"), doc_year(d)) for d in docs if doc_year(d) != d.get("y")]
    assert not wrong, wrong
    assert not any("%20" in d["n"] for d in docs)


def test_watch_does_not_refile_a_known_file(data_dir):
    import common, watch
    lib = common.load("docs.json", [])
    n = len(lib)
    item = {"carrier": "UPS", "name": "Rate and Service Guides"}
    watch.file_into_library(lib, item, "https://delivery-p55671-e392469.adobeaemcloud.com/adobe/assets/urn:aaid:aem:356d938a-4f0a-4c71-b50e-bdd890f50b47/original/as/daily-rates-us-en.pdf", None, baseline=True)
    assert len(lib) == n
    watch.file_into_library(lib, item, "https://www.ups.com/assets/2027%20UPS%20Rate%20Guide.pdf", None, baseline=True)
    assert lib[-1]["y"] == 2027 and "%20" not in lib[-1]["n"]


@pytest.mark.parametrize("width", [390, 1280])
def test_docs_grouped_by_carrier_then_year(site, width):
    from common import doc_year
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="docs"]')
        pg.wait_for_timeout(400)
        pg.evaluate("() => { docCar = 'All'; renderDocs() }")
        panels = pg.evaluate("""() => [...document.querySelectorAll('#lib > details.dcarp')].map(p => ({car: p.dataset.car,
            years: [...p.querySelectorAll(':scope > details.dyear > summary > b')].map(b => b.textContent),
            open: [...p.querySelectorAll(':scope > details.dyear')].filter(d => d.open).length}))""")
        assert len(panels) >= 5
        for p in panels:
            ys = [y for y in p["years"] if y != "Ongoing / undated"]
            assert ys == sorted(ys, reverse=True) and all(re.match(r"^20\d\d$", y) for y in ys), p
            if "Ongoing / undated" in p["years"]:
                assert p["years"][-1] == "Ongoing / undated"
            assert p["open"] <= 1
        # each row sits under its own year, and the app's rule agrees with the pipeline's
        rows = pg.evaluate("""() => [...document.querySelectorAll('#lib details.dyear .drow2')].map(r => ({id: r.id,
            year: r.closest('details.dyear').querySelector(':scope > summary > b').textContent}))""")
        docs = pg.evaluate("() => DOCS.map(d => ({id: docDomId(d), c: d.c, n: d.n, u: d.u, y: d.y, eff: d.eff, upd: d.upd, added: d.added, js: docYear(d)}))")
        by = {d["id"]: d for d in docs}
        for r in rows:
            d = by[r["id"]]
            py = doc_year(d) or (int((d.get("eff") or d.get("upd") or d.get("added") or "0")[:4]) or None)
            assert d["js"] == py, (d["n"], d["js"], py)
            assert r["year"] == (str(py) if py else "Ongoing / undated"), (d["n"], r["year"])
        assert len(rows) == len({r["id"] for r in rows}), "a document is listed twice"
        assert not any(re.search(r"(daily|retail) rates us en$", by[r["id"]]["n"]) for r in rows)
        assert pg.evaluate(OVERFLOW) is None


def test_docs_are_typed_so_they_land_in_the_right_folder_and_have_real_names():
    """Oct 26, 2026 (tools/docs_cleanup.py): rate guides aren't filed under programs, fuel files under fuel, and no title
    is a bare filename."""
    import json, re
    docs = json.loads((ROOT / "data" / "docs.json").read_text())
    t = {(d["c"], d["n"]): d["t"] for d in docs}
    assert t[("UPS", "2026 UPS Small Business Rate Guide")] == "Rate guide"
    assert t[("UPS", "UPS Small Business hundredweight rate guide")] == "Rate guide"
    assert t[("FedEx", "FedEx rate tools (zone locator, rate downloads)")] == "Rate guide"
    assert t[("UPS", "UPS fuel surcharge rate-change flyer (PDF)")] == "Fuel"
    assert t[("USPS", "USPS Handbook DM-204")] == "Service guide"
    assert t[("UPS", "UPS Small Business Rates page")] == "Special program"        # a program page stays a program
    raw = [d["n"] for d in docs if re.search(r"(\b(us en|TermsCond|ImpactedZIPS)\b|%2B|^Printable version$|^USPS (dm|pub)\d+$)", d["n"])]
    assert not raw, raw
