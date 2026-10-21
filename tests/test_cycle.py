"""On-cycle vs off-cycle rate changes, judged by the date a change TAKES EFFECT. The pipeline (common.cycle_of) and the
app (cycleOf in index.html) must give the same answer, so both are checked against the same cases."""
import json, os, re
import pytest
from common import cycle_of, kind_of

CASES = [  # (carrier, kind, effective date, expected[, announced])
    ("UPS", "gri", "2025-12-22", "on"), ("FedEx", "gri", "2027-01-04", "on"), ("FedEx", "surcharge", "2027-01-18", "on"),
    ("UPS", "surcharge", "2026-01-26", "off"),          # a size-rule change pushed past the January window
    ("UPS", "fuel_table", "2025-05-26", "off"), ("FedEx", "dim", "2025-08-18", "off"), ("UPS", "das", "2025-06-01", "off"),
    ("USPS", "price_change", "2026-01-18", "on"), ("USPS", "price_change", "2025-07-13", "off"),
    ("USPS", "price_change", "2026-04-26", "off"),      # the temporary 8% increase
    ("FedEx", "peak", "2026-09-28", "on"), ("USPS", "peak", "2026-10-04", "on"), ("FedEx", "peak", "2020-06-08", "off"),
    ("OnTrac", "fuel_table", "2026-10-26", "off"), ("UPS", "program", "2025-01-01", None), ("UPS", "gri", None, None),
    ("FedEx", "surcharge", "2027-02-01", "on", "2026-09-18"),    # zone change announced with the 2027 increase, staggered
    ("FedEx", "surcharge", "2027-02-01", "off"),                 # same date, no announcement known: judged by date alone
    ("UPS", "fuel_table", "2026-03-09", "off", "2026-02-06"),    # announced in February: not the annual cycle
]
WORDS = [("FedEx sets 5.9% average increase for 2027", "gri"), ("Royal Mail raises parcel prices by up to £1.45", "gri"),
         ("GOFO adds 4% emergency fuel surcharge from Oct. 26", "fuel_table"), ("FedEx residential demand surcharge reaches $0.80", "peak"),
         ("USPS adds $50 hazmat fee", "surcharge"), ("UPS opens Clark hub in the Philippines", None)]


def test_python_rule():
    for c, k, d, want, *ann in CASES:
        assert cycle_of(c, k, d, *ann) == want, (c, k, d, ann)
    for text, want in WORDS:
        assert kind_of(text) == want, text


def test_app_rule_matches_pipeline():
    pw = pytest.importorskip("playwright.sync_api")
    from conftest import ROOT
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page()
        html = (ROOT / "index.html").read_text()
        # just the rule's own code, run in a blank page: the app's cycleOf/kindOf exactly as shipped
        start = html.index("const COST_KINDS=new Set(")
        code = html[start:html.index("const OFFC_TAG=", start)]
        got = pg.evaluate("([code, cases, words]) => { eval(code + ';window.__c=cycleOf;window.__k=kindOf');"
                          "return [cases.map(([c,k,d,a]) => window.__c(c,k,d,a)), words.map(([t]) => window.__k(t))] }",
                          [code, [list(x[:3]) + [x[4] if len(x) > 4 else None] for x in CASES], WORDS])
        b.close()
    assert got[0] == [x[3] for x in CASES]
    assert got[1] == [w for _, w in WORDS]


def test_almanac_dates_are_in_order():
    from conftest import ROOT
    for e in json.loads((ROOT / "data" / "almanac.json").read_text()):
        if e.get("announced") and e.get("effective"):
            assert e["announced"] <= e["effective"], f"{e['id']}: announced after it took effect"
