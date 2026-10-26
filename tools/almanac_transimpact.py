#!/usr/bin/env python3
"""Fold the carrier changes listed on transimpact.com/carrier-updates (and the posts they link to) into data/almanac.json.

Idempotent: an entry is added once (by id); announced dates and notes are set only where they are still empty or
carry the old "not confirmed" wording. Every figure below was read from the TransImpact post or the carrier page named
in the entry's sources. Where TransImpact is the only source the entry is "partial"; where a carrier page or a trade
outlet also shows it, "confirmed". Run: python3 tools/almanac_transimpact.py
"""
import json
import pathlib

ALM = pathlib.Path(__file__).resolve().parent.parent / "data" / "almanac.json"
TI = "https://transimpact.com/blog/"
FEDEX_CHANGES = "https://www.fedex.com/en-us/shipping/rate-changes.html"
FEDEX_FUEL = "https://www.fedex.com/en-us/shipping/fuel-surcharge.html"
UPS_FUEL = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges"
TI_ONLY = "Single source: TransImpact's carrier-updates page; not shown on the carrier's own page."


def e(carrier, year, kind, effective, headline, details, sources, conf="partial", note=None, announced=None, pct=None):
    return {"carrier": carrier, "year": year, "kind": kind, "announced": announced, "effective": effective, "pct": pct,
            "headline": headline, "details": details, "sources": sources, "conf": conf, "note": note,
            "id": f"{carrier.lower()}-{year}-{kind.replace('_', '-')}-{effective}"}


NEW = [
    # ---- 2025 ----
    e("FedEx", 2025, "fuel_table", "2025-02-10",
      "FedEx raises domestic fuel surcharge: Express +1 pt, Ground and Home Delivery +1.75 pts",
      ["Fuel surcharge percentages up 1% for Domestic Express and 1.75% for Ground and Home Delivery, effective Feb 10, 2025",
       "Came a month after the 5.9% GRI took effect on Jan 6, 2025"],
      [TI + "fedex-updates-domestic-fuel-surcharge-and-ground-economy-das/"], note=TI_ONLY),
    e("FedEx", 2025, "das", "2025-02-10",
      "FedEx Ground Economy Delivery Area Surcharge up 55%: $4.00 to $6.20, Extended $5.35 to $8.30",
      ["Standard Ground Economy DAS $4.00 to $6.20; Extended DAS $5.35 to $8.30, effective Feb 10, 2025",
       "TransImpact: in line with the recent UPS SurePost DAS increases"],
      [TI + "fedex-updates-domestic-fuel-surcharge-and-ground-economy-das/"], note=TI_ONLY),
    e("UPS", 2025, "price_change", "2025-03-24",
      "UPS zone adjustments for certain origin and destination ZIP code pairs",
      ["Zone pricing changes for certain origin/destination ZIP code pairs, effective March 24, 2025"],
      [TI + "ups-announces-zone-adjustments-effective-march-24-2025/"], note=TI_ONLY + " Which ZIP pairs moved was not listed."),
    e("UPS", 2025, "surcharge", "2025-05-18",
      "UPS surge fee on U.S. to Canada exports: $1.25/lb Worldwide Economy, $0.49/lb other export services",
      ["Surge fee on shipments from the U.S. to Canada effective May 18, 2025; no end date announced",
       "$1.25 per lb on Worldwide Economy; $0.49 per lb on other export services"],
      [TI + "ups-announces-surge-fee-from-u-s-to-canada/"], note=TI_ONLY),
    e("FedEx", 2025, "surcharge", "2025-06-02",
      "FedEx adds a Demand Surcharge on U.S. to Canada exports",
      ["New Demand Surcharge Fee on exports to Canada effective June 2, 2025"],
      [TI + "fedex-to-add-demand-surcharge-fee-from-us-to-canada/"], note=TI_ONLY + " Amount not in the source we read."),
    e("UPS", 2025, "fuel_table", "2025-06-23",
      "UPS Domestic Air fuel surcharge +0.75 pt; UPS and FedEx Ground both reach a record 20%",
      ["UPS Domestic Air fuel surcharge up 0.75%, matching FedEx Express at 18.75%",
       "UPS and FedEx Ground fuel surcharges both 20%, a record; the previous peak was FedEx at 19.50% in mid-2022"],
      [TI + "ups-matches-fedex-with-record-high-fuel-surcharge/"], note=TI_ONLY),
    e("UPS", 2025, "fee", "2025-08-29",
      "UPS adds Entry Preparation Charge on Canada-to-U.S. imports ($10 up to $200, $20 from $200.01 to $800)",
      ["UPS Standard shipments from Canada into the U.S.: $10.00 for value for duty $0.00-$200.00; $20.00 for $200.01-$800.00",
       "Effective Aug 29, 2025, as the U.S. ended de minimis duty-free entry"],
      [TI + "chaos-in-international-shipping-new-ups-fees-and-mail-suspensions/"], note=TI_ONLY),
    e("UPS", 2025, "fee", "2025-09-08",
      "UPS adds a $2.50 International Processing Fee on select premium import services",
      ["$2.50 per shipment on UPS Worldwide Express, Worldwide Express Plus and Worldwide Express NA1, effective Sept 8, 2025"],
      [TI + "chaos-in-international-shipping-new-ups-fees-and-mail-suspensions/",
       "https://www.supplychaindive.com/news/ups-international-processing-fee-worldwide-2025/758526/"],
      note="TransImpact gives Sept 8; the trade outlet reported the fee in late August."),
    e("FedEx", 2025, "peak", "2025-09-22",
      "FedEx 2025 international peak demand surcharges, Sept 22 to Oct 19",
      ["Import and export demand surcharges apply Sept 22 to Oct 19, 2025",
       "TransImpact: UPS and FedEx international peak fees run $0.10 to $0.52 per lb depending on the origin and destination"],
      [TI + "ups-and-fedex-announce-2025-international-peak-season-fees/"], note=TI_ONLY),
    e("UPS", 2025, "peak", "2025-10-26",
      "UPS 2025 international peak surge fees, Oct 26 to Jan 17, 2026",
      ["Import and export surge fees across UPS's full peak window, Oct 26, 2025 to Jan 17, 2026",
       "Per-lb fees range from $0.10 to $0.52 depending on the origin and destination"],
      [TI + "ups-and-fedex-announce-2025-international-peak-season-fees/"], note=TI_ONLY),
    e("UPS", 2025, "fuel_table", "2025-11-24",
      "UPS raises international air fuel tables, export and import",
      ["International Air Export and Import fuel surcharge tables raised across the board, effective Nov 24, 2025",
       "At $2.35 jet fuel (Nov 20, 2025): 26% on Air Export and 29.75% on Air Import under the new tables"],
      [TI + "ups-updates-international-fuel-surcharge-rates-for-air-services/"], note=TI_ONLY),
    e("FedEx", 2025, "other", "2025-12-01",
      "FedEx suspends its Money-Back Guarantee for all shippers",
      ["Suspended Dec 1, 2025, citing reduced air capacity from MD-11 safety inspections",
       "Ground was already excluded from service guarantees; International and Air guarantees suspended",
       "UPS extended delivery commitments during the disruption; no end date given"],
      [TI + "fedex-suspends-money-back-guarantee-amid-md-11-fleet-inspections/"], note=TI_ONLY),
    # ---- 2026 ----
    e("UPS", 2026, "surcharge", "2026-01-18",
      "UPS temporary Surge Fee on all U.S. exports except Israel, Jan 18 to Feb 14",
      ["Applies to exports from the U.S. to all destinations except Israel, Jan 18 to Feb 14, 2026",
       "Surge fees apply in addition to other charges and are subject to change"],
      [TI + "ups-announces-temporary-surge-fee-for-u.s.-export-shipments/"], note=TI_ONLY + " Fee amount not in the source we read."),
    e("UPS", 2026, "fuel_table", "2026-03-02",
      "UPS international ground fuel +1 pt for Canada and Mexico services",
      ["UPS Standard import and export to and from Canada and Mexico, effective March 2, 2026",
       "At $3.71 diesel (Feb 16, 2026): 21.75%, up from 20.75%; still reset weekly on the diesel price"],
      [TI + "ups-announces-fuel-surcharge-adjustment-for-international-ground-import/export-services/"], note=TI_ONLY),
    e("FedEx", 2026, "surcharge", "2026-03-05",
      "FedEx international demand surcharge on U.S.-Middle East (Zone K) shipments",
      ["$0.50 per lb on exports to Zone K; $0.70 per lb on imports from Zone K",
       "In place from March 5, 2026 until further notice"],
      [TI + "parcel-carrier-updates/"], note=TI_ONLY),
    e("UPS", 2026, "surcharge", "2026-04-19",
      "UPS Surge Emergency Fee: $0.23/lb on U.S. shipments to and from most international destinations",
      ["Broad per-pound fee from April 19, 2026, calculated on billable weight, with fuel surcharge on top",
       "Two tiers for inbound shipments from Asia; China and Hong Kong fell from $0.32 to $0.23/lb after April 26",
       "The March 22 Middle East surcharges stay in place; no end date for either"],
      [TI + "ups-rolls-out-surge-emergency-fee/"], note=TI_ONLY),
    e("FedEx", 2026, "price_change", "2026-04-20",
      "FedEx One Rate pricing increases again",
      ["One Rate pricing increase effective April 20, 2026",
       "Follows earlier 2026 adjustments, including a February update adding pricing for the FedEx Extra Small Box"],
      [TI + "another-increase-to-fedex-one-rate-pricing-effective-april-20-2026/"], note=TI_ONLY + " The size of the increase was not in the source we read."),
    e("FedEx", 2026, "fuel_table", "2026-05-11",
      "FedEx raises international fuel surcharges: export +2%, import +2.5%",
      ["Export surcharges up 2% and import surcharges up 2.5%, effective May 11, 2026",
       "Followed six weeks later by the June 22 merge of the export and import tables"],
      [TI + "fedex-consolidates-international-fuel-surcharge-tables/", FEDEX_FUEL], note=TI_ONLY),
    e("UPS", 2026, "surcharge", "2026-05-31",
      "UPS adds flat Surge Emergency Fees to export accessorials: AHS $8.75, LPS $96, OML $514",
      ["Flat per-package fees on U.S. export shipments to all destinations from May 31, 2026",
       "Additional Handling $8.75; Large Package Surcharge $96; Over Maximum Limits $514; fuel surcharge applies on top",
       "Replace the per-pound model for these charges; in effect until further notice"],
      [TI + "ups-adds-new-surge-emergency-fees-and-higher-fuel-surcharges/"], note=TI_ONLY),
    e("UPS", 2026, "fuel_table", "2026-06-01",
      "UPS raises international fuel tables, ground and air",
      ["International Ground (Canada and Mexico): new table starts at 27.25% at diesel $4.82-$4.94 and reaches 30.25% at $6.26-$6.38, +0.25 pt per $0.12",
       "International Air Export 41% to 44%; Air Import 44.75% to 47.75%, +0.25 pt per $0.04 of Gulf Coast jet fuel",
       "Reset every Monday on the latest EIA price"],
      [TI + "ups-adds-new-surge-emergency-fees-and-higher-fuel-surcharges/", UPS_FUEL], note=TI_ONLY),
    e("FedEx", 2026, "das", "2026-07-20",
      "FedEx adds ZIP codes to Delivery Area and Pickup Area Surcharge lists",
      ["28 standard contiguous U.S., 10 extended and 74 remote ZIP codes added, effective July 20, 2026",
       "Applies to both Delivery Area Surcharges (DAS) and Pickup Area Surcharges (PAS)"],
      [FEDEX_CHANGES], conf="confirmed"),
    e("FedEx", 2026, "fee", "2026-07-20",
      "FedEx Disbursement Fee: greater of $17.50 or 2.5% (was $15 or 2%)",
      ["Disbursement Fee on duty, tax and merchandise processing charges rises from the greater of $15 or 2% to the greater of $17.50 or 2.5%",
       "Effective July 20, 2026"],
      [FEDEX_CHANGES], conf="confirmed",
      note="TransImpact lists it under July 30; FedEx's rate-changes page gives July 20."),
    e("UPS", 2026, "fuel_table", "2026-08-01",
      "UPS export fuel surcharge +1%",
      ["TransImpact reports UPS raising its export fuel surcharge by 1% on Aug 1, 2026"],
      [UPS_FUEL], note=TI_ONLY),
    e("FedEx", 2026, "fee", "2026-08-03",
      "FedEx renames the U.S. Inbound Processing Fee the Inbound Processing Fee",
      ["Name change effective Aug 3, 2026; FedEx points to its Service Guide for the details"],
      [FEDEX_CHANGES], conf="confirmed",
      note="A Reddit post says the fee now covers shipments to EU member states; FedEx's page does not say so, so it is left out."),
    e("UPS", 2026, "fuel_table", "2026-08-10",
      "UPS Ground and Ground Saver fuel tables +0.5 to 1 pt on the lower bands",
      ["Lower bands raised 0.5% to 1% and the lower bands expanded, effective Aug 10, 2026",
       "TransImpact: UPS's previous fuel-table update was April 13, 2026"],
      ["https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/ups-ground-saver"], note=TI_ONLY),
    e("UPS", 2026, "fuel_table", "2026-11-02",
      "UPS changes the domestic Ground, Ground Saver and Air fuel tables",
      ["UPS's rate-change flyer (published Oct 23, 2026) replaces the U.S. Ground Domestic, Ground Saver and Domestic Air fuel tables on Nov 2, 2026",
       "Sample points in the flyer: Ground at diesel $6.25-$6.34 is 30.00%; Air at jet fuel $4.41-$4.46 is 33.25%"],
      [UPS_FUEL, "https://delivery-p55671-e392469.adobeaemcloud.com/adobe/assets/urn:aaid:aem:8ea98d87-766b-4135-8267-b9c4d3a6daad/original/as/fuelsurcharge-us-en.pdf"],
      conf="confirmed", note="Published by UPS; the size of the change against the old table was not computed."),
]

# announced dates that TransImpact's list and a carrier or trade source agree on
ANNOUNCED = {
    "fedex-2026-gri-2026-01-05": ("2025-09-12", "FedEx announced Sept 12, 2025 (TransImpact; Supply Chain Dive URL dates the coverage to mid-September)."),
    "ups-2026-gri-2025-12-22": ("2025-10-31", "UPS announced Oct 31, 2025 per TransImpact; the Supply Chain Dive report followed in early November."),
    "fedex-2027-gri-2027-01-04": ("2026-09-18", "FedEx announced Sept 18, 2026 (TransImpact's Key Takeaways PDF, and the date one outlet gave)."),
}

# facts to add to entries that already exist
ENRICH = {
    "fedex-2026-fuel-table-2026-06-22": {
        "detail": "TransImpact: export +3.5% and import -0.75% in effective surcharge, after export +2% and import +2.5% on May 11, 2026",
        "source": TI + "fedex-consolidates-international-fuel-surcharge-tables/"},
    "ups-2025-surcharge-2025-05-18": {
        "detail": "TransImpact lists the invoice-copy, check/wire and late-payment fees as effective March 31, 2025 and the card swap as May 18",
        "source": TI + "ups-to-increase-fuel-surcharge-and-add-other-new-charges/"},
    "fedex-2025-dim-2025-08-18": {
        "detail": "TransImpact: the Inbound Processing Fee for U.S. import shipments tied to customs clearance also rose",
        "source": TI + "fedex-announces-several-rate-changes-effective-beginning-in-july-14-and-august-18/"},
}


def apply(alm):
    by = {x["id"]: x for x in alm}
    added = 0
    for n in NEW:
        if n["id"] not in by:
            alm.append(n)
            by[n["id"]] = n
            added += 1
    for i, (a, note) in ANNOUNCED.items():
        x = by.get(i)
        if x and not x.get("announced"):
            x["announced"] = a
            keep = [t for t in (x.get("note") or "").split(". ") if t and "date not confirmed" not in t]
            x["note"] = " ".join([note] + [t if t.endswith(".") else t + "." for t in keep])
    for i, f in ENRICH.items():
        x = by.get(i)
        if not x:
            continue
        if f["detail"] not in x["details"]:
            x["details"].append(f["detail"])
        if f["source"] not in x["sources"]:
            x["sources"].append(f["source"])
    return added


def main():
    alm = json.loads(ALM.read_text())
    n = apply(alm)
    ALM.write_text(json.dumps(alm, indent=1, ensure_ascii=False) + "\n")
    print("added", n, "entries; total", len(alm))


if __name__ == "__main__":
    main()
