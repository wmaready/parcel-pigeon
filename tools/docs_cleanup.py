"""Oct 26, 2026: Docs placement. Fix document types so each lands in the right folder, and give filename-style titles real
names. Keyed by address, idempotent; applies to data/docs.json and to the app's built-in list (DOCLIB in index.html).
Run again after merging main's robot commits."""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = {   # address -> fields to set
 "https://delivery-p55671-e392469.adobeaemcloud.com/adobe/assets/urn:aaid:aem:8ea98d87-766b-4135-8267-b9c4d3a6daad/original/as/fuelsurcharge-us-en.pdf":
    {"n": "UPS fuel surcharge rate-change flyer (PDF)", "t": "Fuel", "eff": "2026-11-02", "d": "Domestic ground and air fuel tables changing Nov 2, 2026"},
}
BY_NAME = {   # (carrier, old name) -> fields to set, for items whose address varies or isn't stable
 ("UPS", "ups ground saver brand guidelines us en"): {"n": "UPS Ground Saver brand guidelines", "t": "Service guide"},
 ("UPS", "UPS small busines cwt rate guide us en"): {"n": "UPS Small Business hundredweight rate guide", "t": "Rate guide"},
 ("UPS", "UPS Ship API EU PID Requirements v1.2"): {"t": "Service guide"},
 ("UPS", "UPS Ground Saver labeling supplement (v1.8)"): {"t": "Service guide"},
 ("UPS", "2023 UPS Small Business Rate Guide"): {"t": "Rate guide"},
 ("UPS", "2026 UPS Small Business Rate Guide"): {"t": "Rate guide"},
 ("UPS", "2026 UPS Small Business hundredweight rates"): {"t": "Rate guide"},
 ("USPS", "USPS dm204"): {"n": "USPS Handbook DM-204", "t": "Service guide"},
 ("USPS", "USPS pub25"): {"n": "USPS Publication 25", "t": "Service guide"},
 ("USPS", "USPS SKU User Guide"): {"t": "Service guide"},
 ("USPS", "USPS SKU User Guide July2026"): {"n": "USPS SKU User Guide (July 2026)", "t": "Service guide"},
 ("USPS", "Printable version"): {"n": "USPS release: Postal Service prepped for the 2026 holiday season", "t": "Peak"},
 ("USPS", "Terms of use"): {"n": "USPS terms of use"},
 ("USPS", "USPS July 2026 Price Change   Notice123 PDF   7.10.26"): {"n": "USPS July 2026 price change, Notice 123 (PDF, Jul 10, 2026)"},
 ("Amazon", "Conditions of Use"): {"n": "Amazon Shipping conditions of use"},
 ("OnTrac", "2026 OnTrac AHS%2BLPSRates"): {"n": "2026 OnTrac Additional Handling and Large Package rates"},
 ("OnTrac", "OnTrac ImpactedZIPS 08242026"): {"n": "OnTrac service alert: impacted ZIP codes (Aug 24, 2026)"},
 ("FedEx", "FedEx IPIXF TermsCond"): {"n": "FedEx IPIXF terms and conditions"},
 ("FedEx", "FedEx FICE TermsCond"): {"n": "FedEx FICE terms and conditions"},
 ("FedEx", "FedEx IDP TermsCond"): {"n": "FedEx IDP terms and conditions"},
 ("FedEx", "FedEx rate tools (zone locator, rate downloads)"): {"t": "Rate guide"},
 ("FedEx", "FedEx Ground Economy rates and zones page"): {"t": "Rate guide"},
}


def apply(L):
    n = 0
    for d in L:
        new = FIX.get(d.get("u")) or BY_NAME.get((d.get("c"), d.get("n"))) or {}
        # already renamed? match on the new name too, so a second run changes nothing
        for k, v in new.items():
            if d.get(k) != v:
                d[k] = v; n += 1
    return n


def main():
    p = ROOT / "data" / "docs.json"
    docs = json.loads(p.read_text())
    a = apply(docs)
    p.write_text(json.dumps(docs, indent=1, ensure_ascii=False) + "\n")
    h = (ROOT / "index.html").read_text()
    m = re.search(r"^const DOCLIB=(\[.*\]);$", h, re.M)
    lib = json.loads(m.group(1))
    b = apply(lib)
    h = h[:m.start(1)] + json.dumps(lib, ensure_ascii=False) + h[m.end(1):]
    (ROOT / "index.html").write_text(h)
    print("docs.json", a, "changes; DOCLIB", b, "changes")


if __name__ == "__main__":
    main()
