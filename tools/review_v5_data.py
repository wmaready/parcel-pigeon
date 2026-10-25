"""Outside review v5 (Oct 24, 2026): the data fixes, applied in one deterministic pass. No model calls, no network.
Running it again changes nothing; it finds every record by id or by its own fields, never by position.

  python3 tools/review_v5_data.py          # writes data/*.json
  python3 tools/review_v5_data.py --dry    # prints what it would change

Fixes (numbers from the review brief):
  B2   UPS Small Business Rates (SBR): +4.5% and a new 5% fuel surcharge from Dec 21, 2026, published as a story
  B5   UPS 2027 rate clock: one Dec 21 line showing 5.9%, the other changes as sub-items; no label cut mid-word
  B7   UPS 2027 story title: "threshold" -> "minimum billable weight"
  B12  deal corrections (C.H. Robinson-RXO value, DHL-Venipak announced date, ShipStation Global name); the three
       Oct 13 parcel-index stories become one story with all their sources
  B14  almanac: UPS 2027 GRI announced (5.9%, Dec 21, 2026); SBR as its own entry
  B16  the Feb 2018 "Shipping With Amazon" article leaves the feed and the Amazon storyline
  B17  the Larsen interview story loses the unrelated Germany link (its own Supply Chain 24/7 interview stays)
  B18  storyline "where it stands" lines rest only on member stories; FedEx Freight spin-off completion added
  B19  USPS holiday send-by story: headline, Sept 22 announcement date, "Reminder" label
  B21  Docs entries whose links land on a homepage or error page are marked retired

Sources: each figure below is from the source named next to it, as checked in the review brief (Oct 24, 2026). The
network was not reachable when this script was written, so nothing here was re-read from the live pages; a person
should spot-check the links listed in the commit message.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from common import load, save, h          # noqa: E402

# ---------------------------------------------------------------- sources
UPS_RATES = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates"
UPS_SBR = "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates"
FEDEX_FREIGHT = "https://newsroom.fedex.com/newsroom/global-english/fedex-completes-spin-off-of-fedex-freight"
USPS_HOLIDAY = "https://about.usps.com/newsroom/national-releases/2026/0922-usps-recommends-2026-holiday-mailing-shipping-dates.htm"
DHL_VENIPAK = "https://group.dhl.com/en/media-relations/press-releases/2026/dhl-ecommerce-to-acquire-venipak-strengthening-its-position-across-the-baltic-region.html"
CHECKED = "2026-10-24"          # the review's fact-check date

# ---------------------------------------------------------------- ids
UPS27 = "w84705482dd2f"         # UPS announces the Dec 21, 2026 rate increase
UPS_FUEL = "w599d9089a65d"      # UPS Nov 2 fuel tables (a clock label cut at 70 characters)
SBR_ID = "rv5-ups-sbr-fuel"
FXF_ID = "rv5-fedex-freight-spin-done"
INDEX_KEEP = "a0ee60aceb401"
INDEX_DUPES = ["a25504a8149d3", "a6a52b69d2dfc"]
OLD_AMAZON = "a418fdd3e6f05"
LARSEN = "aba40a11b6946"
USPS_HOL = "a6cc2420ad66e"
GERMANY = "https://www.aboutamazon.com/company-news/amazon-germany-investment"

DROPS = {
    "a25504a8149d3": "Review v5 (B12): same Oct 13, 2026 parcel index study as a0ee60aceb401; merged there with its sources",
    "a6a52b69d2dfc": "Review v5 (B12): same Oct 13, 2026 parcel index study as a0ee60aceb401; merged there with its sources",
    OLD_AMAZON: "Review v5 (B16): the linked Mashable article is dated Feb 9, 2018, not current news",
}

# ---------------------------------------------------------------- B2: the SBR story
SBR_STORY = {
    "id": SBR_ID,
    "date": "2026-10-24",
    "c": ["UPS"],
    "cat": "Pricing & GRI",
    "kind": "News",
    "title": "UPS adds a 5% fuel surcharge to Small Business Rates and raises them 4.5% on Dec. 21",
    "sum": "UPS's Small Business Rates page says that from Dec. 21, 2026, Small Business Rates (SBR) rise 4.5% and a 5% fuel "
           "surcharge applies to all SBR shipments, domestic and international. The Additional Handling minimum billable weight "
           "also goes from 40 to 50 lb. The same page still advertises SBR rates as inclusive of the Delivery Area Surcharge and "
           "Fuel Surcharge.",
    "syn": "UPS's Small Business Rates page says that from Dec. 21, 2026, SBR rates rise 4.5% and a 5% fuel surcharge applies to "
           "all SBR shipments, domestic and international. For an SBR customer the two combine to about 9.7% (1.045 x 1.05), "
           "before any agreement terms. SBR is advertised as including fuel and delivery area surcharges, so a separate fuel "
           "surcharge removes the program's main stated benefit. The Additional Handling minimum billable weight goes from 40 "
           "to 50 lb on the same date.",
    "aff": [
        {"who": "UPS Small Business Rates shippers",
         "what": "Rates up 4.5% plus a new 5% fuel surcharge from Dec. 21, 2026: about 9.7% combined before agreement terms."},
        {"who": "Packages subject to Additional Handling",
         "what": "Minimum billable weight goes from 40 to 50 lb on Dec. 21, 2026."},
    ],
    "imp": "up",
    "lvl": 3,
    "plain": "Shippers on UPS Small Business Rates face about 9.7% more (1.045 x 1.05) from Dec. 21, 2026, before any agreement "
             "terms. SBR is advertised as including fuel and delivery area surcharges, so this removes the program's main "
             "stated benefit.",
    "why": "Removes a stated SBR benefit: SBR rates are advertised as including the fuel surcharge, and from Dec. 21, 2026 a 5% "
           "fuel surcharge applies on top of a 4.5% rate increase.",
    "tie": None,
    "act": "2026-12-21",
    "dates": [{"d": "2026-12-21", "w": "UPS Small Business Rates: 4.5% increase plus a new 5% fuel surcharge (about 9.7% combined)",
               "imp": "up"}],
    "src": "UPS Small Business Rates page",
    "url": UPS_SBR,
    "srcs": [{"src": "UPS Small Business Rates page", "url": UPS_SBR, "checked": CHECKED}],
    "auto": False,
    "primary": True,
    "added": "2026-10-25T12:00:00Z",
}

# ---------------------------------------------------------------- B18: the FedEx Freight completion story
FXF_STORY = {
    "id": FXF_ID,
    "date": "2026-06-01",
    "c": ["FedEx"],
    "cat": "Carrier strategy",
    "kind": "News",
    "title": "FedEx completes FedEx Freight spin-off",
    "sum": "FedEx completed the FedEx Freight spin-off on June 1, 2026. FedEx Freight is an independent public company "
           "(NYSE: FDXF). FedEx kept 19.9% at separation.",
    "imp": "info",
    "lvl": 2,
    "plain": "FedEx Freight now trades on its own as FDXF; FedEx kept a 19.9% stake at separation.",
    "tie": None,
    "act": None,
    "dates": [],
    "src": "FedEx Newsroom",
    "url": FEDEX_FREIGHT,
    "srcs": [{"src": "FedEx Newsroom", "url": FEDEX_FREIGHT, "checked": CHECKED}],
    "auto": False,
    "primary": True,
    "thread": "fedex-freight-spin",
}

# ---------------------------------------------------------------- B5: the one UPS Dec 21 clock line
UPS27_DATE = {
    "d": "2026-12-21",
    "w": "UPS 2027 rate increase: 5.9% average (Ground, Air, International)",
    "imp": "up",
    "fx": {"t": "gri", "car": "UPS", "pct": 5.9, "src": UPS_RATES},
    "fees": [
        ["UPS", "Additional Handling minimum billable weight", "40 lb to 50 lb"],
        ["UPS", "Area Surcharge ZIP list", "Changes"],
        ["UPS", "ZIP codes aligned to zones", "Change"],
        ["UPS", "Origin-ZIP surcharge, Ground and Ground Saver (Qualified customers)", "Amount not yet stated"],
    ],
}

# ---------------------------------------------------------------- B14: almanac
UPS27_ALM = {
    "carrier": "UPS",
    "year": 2027,
    "kind": "gri",
    "announced": "2026-10-23",
    "effective": "2026-12-21",
    "pct": 5.9,
    "headline": "UPS 2027 GRI: 5.9% average for Ground, Air and International (Daily Rates), effective Dec 21, 2026",
    "details": [
        "Daily Rates for UPS Ground, UPS Air and International: average net increase of 5.9%, effective Dec 21, 2026",
        "Additional Handling minimum billable weight 40 -> 50 lb; Area Surcharge and zone ZIP lists change",
        "New per-package surcharge on Ground and Ground Saver from certain origin ZIPs for Qualified customers (amount not stated)",
        "UPS says detailed rate previews will follow; individual impact varies by shipping profile and UPS agreement",
        "Small Business Rates change separately: +4.5% plus a new 5% fuel surcharge (entry ups-2027-sbr-2026-12-21)",
    ],
    "sources": [UPS_RATES],
    "conf": "confirmed",
    "note": "Announced date: Oct 23, 2026 is when the notice was first found on UPS's Important Updates page (story "
            "w84705482dd2f, detected 2026-10-23, UTC). UPS's page prints no posting date, so it may have gone up late on "
            "Oct 22 U.S. time.",
    "id": "ups-2027-gri",
    "story": UPS27,
}
SBR_ALM = {
    "carrier": "UPS",
    "year": 2027,
    "kind": "price_change",
    "announced": None,
    "effective": "2026-12-21",
    "pct": 4.5,
    "headline": "UPS Small Business Rates: +4.5% plus a new 5% fuel surcharge from Dec 21, 2026",
    "details": [
        "SBR rates rise 4.5%, effective Dec 21, 2026",
        "A 5% fuel surcharge applies to all SBR shipments, domestic and international",
        "About 9.7% combined (1.045 x 1.05) before agreement terms",
        "The SBR page still advertises SBR rates as inclusive of Delivery Area Surcharge and Fuel Surcharge",
        "Additional Handling minimum billable weight 40 -> 50 lb",
    ],
    "sources": [UPS_SBR],
    "conf": "confirmed",
    "note": "From UPS's Small Business Rates page as checked on Oct 24, 2026. The page states no announcement date.",
    "id": "ups-2027-sbr-2026-12-21",
    "story": SBR_ID,
}

# ---------------------------------------------------------------- B18: "where it stands", from member stories only
NO_NEWER = "No newer verified milestone."
FXF_NOW = ("FedEx completed the FedEx Freight spin-off on June 1, 2026. FedEx Freight is an independent public company "
           "(NYSE: FDXF). FedEx kept 19.9% at separation.")
THREAD_FIX = {
    # key: {"s": summary, "now": Coop's where-it-stands line, "add": ids to add, "remove": ids to take out, "beats": new beats}
    "fedex-freight-spin": {
        "s": "FedEx completed the FedEx Freight spin-off on June 1, 2026; FedEx Freight trades as FDXF and FedEx kept 19.9% at separation.",
        "now": FXF_NOW,
        "intro": "FedEx spun off FedEx Freight, the largest U.S. LTL carrier, into its own public company.",
        "add": [FXF_ID],
        "beats": {FXF_ID: "FedEx completed the spin-off; FedEx Freight trades on the NYSE as FDXF, and FedEx kept 19.9%."},
    },
    "fedex-network-2": {"now": "FedEx expects the U.S. rollout to finish by the end of 2027."},
    "usps-big-shipper-deals": {
        "s": "USPS signed a new Amazon agreement that trims Amazon's USPS volume by about 20%, an exclusive DHL eCommerce "
             "last-mile contract worth over $10 billion, and a same-day delivery pilot for Amazon.",
        "now": "USPS's same-day pilot for Amazon added Columbia, S.C., from Oct. 20 with a 500-package cap.",
    },
    "amazon-network-buildout": {
        "s": "Amazon has opened its logistics network to outside businesses and added LTL labels for sellers, and a Business "
             "Insider report describes a contingency plan to reach about 95% of U.S. ZIP codes by 2029.",
        "now": "Next dated step: Amazon's regional delivery pricing for heavy and bulky items arrives in early 2027.",
        "remove": [OLD_AMAZON],
    },
    "ups-amazon-glide-down": {
        "s": "UPS says it has completed cutting its Amazon volume by more than half, after closing 23 buildings in early 2026 "
             "and planning about 30,000 job cuts for the year.",
        "now": "UPS says the Amazon volume reduction and network reconfiguration are complete.",
    },
    "tariff-refunds": {
        "s": "FedEx, UPS and DHL have begun passing IEEPA tariff refunds to customers, and CBP has started processing refunds "
             "for some finally liquidated entries.",
        "now": "CBP has begun processing refunds for some finally liquidated entries, according to an Oct. 6 court filing.",
    },
    "carrier-gri": {
        "s": "UPS set a 5.9% average increase for Dec. 21, 2026, DHL 5.9% for Jan. 1 and FedEx 5.9% for Jan. 4, 2027.",
        "now": "UPS's 5.9% average increase takes effect Dec. 21, 2026, DHL's 5.9% on Jan. 1 and FedEx's 5.9% on Jan. 4, 2027.",
        "intro": "Carriers keep announcing 5.9% average rate increases each year; UPS, DHL and FedEx have each set 5.9% again.",
        "add": [UPS27],
        "beats": {UPS27: "UPS set a 5.9% average increase for Ground, Air and International Daily Rates from Dec. 21, 2026."},
    },
    "usps-pricing": {
        "s": "USPS set July 13, 2025 shipping price increases, with Ground Advantage up about 7.1%, after earlier annual and mid-year changes.",
        "now": NO_NEWER,
    },
    "peak-surcharges": {
        "now": "Per-package peak fees begin Oct. 24 to 26; UPS and Amazon rise to $0.75 from Nov. 22 and FedEx to $0.80 from Nov. 23.",
    },
    "usps-service-network": {
        "now": "USPS's longer delivery estimates for packages to and from Guam, Alaska, Hawaii and other areas outside the "
               "mainland took effect Oct. 1, 2026.",
    },
    "usps-finances": {"now": NO_NEWER},
    "parcel-volume-amazon": {
        "s": "Amazon is now the largest U.S. carrier by volume; 2025 market totals are 23.9 billion parcels (ShipMatrix) and "
             "23.1 billion (Pitney Bowes).",
    },
    "usps-leadership": {
        "s": "David Steiner has been Postmaster General since July 2025; a Reuters report in September 2026 said he wants to "
             "step down, which USPS denied.",
        "now": NO_NEWER,
    },
    "drone-delivery": {
        "s": "MassDOT told Amazon its Aeronautics Division must complete a suitability review before any drone operations "
             "begin in Westborough.",
        "now": "Amazon's Westborough drone site awaits a MassDOT suitability review, and the FAA's Part 108 rule was still "
               "unpublished as of Oct. 9.",
    },
}

# ---------------------------------------------------------------- B21: Docs entries that land on the wrong page
RETIRED = {
    ("UPS", "2025 UPS Hundredweight rates preview"):
        "Retired by the carrier, last seen Oct 22, 2026 (our saved copy is from that day); the link now goes to a UPS error page",
    ("GLS US", "GLS US fuel surcharge matrix, effective Dec 15, 2025"):
        "Retired by the carrier, last seen date not on file; the link now opens the GLS homepage (checked Oct 24, 2026)",
    ("GLS US", "GLS US fuel surcharge, Jul 2025"):
        "Retired by the carrier, last seen date not on file; the link now opens the GLS homepage (checked Oct 24, 2026)",
    ("GLS US", "GLS US fuel surcharge, ground and priority, Sep 2024"):
        "Retired by the carrier, last seen date not on file; the link now opens the GLS homepage (checked Oct 24, 2026)",
    ("GLS US", "2023 GLS priority rates"):
        "Retired by the carrier, last seen date not on file; the link now opens the GLS homepage (checked Oct 24, 2026)",
    ("GLS US", "GLS US 2024 peak season surcharge"):
        "Retired by the carrier, last seen date not on file; the link now opens the GLS homepage (checked Oct 24, 2026)",
    ("Veho", "Veho service guide: last-mile delivery"):
        "Retired by the carrier, last seen date not on file; the link now goes to Veho's Knowledge Hub, and Doc watch gets "
        "404 Not Found (last try Oct 25, 2026)",
}


# ================================================================ helpers
def find(lst, sid):
    return next((s for s in lst if isinstance(s, dict) and s.get("id") == sid), None)


def insert_by_date(news, story):
    """Put a story where the date-ordered feed (newest first) expects it, without reordering anything else."""
    i = next((i for i, s in enumerate(news) if (s.get("date") or "") < story["date"]), len(news))
    news.insert(i, story)


def union_srcs(a, b):
    seen, out = set(), []
    for x in (a or []) + (b or []):
        u = (x or {}).get("url")
        if u and u not in seen:
            seen.add(u); out.append(x)
    return out


# ================================================================ the fixes
def fix_news(news, log):
    # B2: the SBR story
    if not find(news, SBR_ID):
        insert_by_date(news, copy.deepcopy(SBR_STORY)); log.append("B2  + story " + SBR_ID)
    # B18: the FedEx Freight completion story
    if not find(news, FXF_ID):
        insert_by_date(news, copy.deepcopy(FXF_STORY)); log.append("B18 + story " + FXF_ID)

    # B5 + B7: the UPS 2027 story
    s = find(news, UPS27)
    if s:
        t = s["title"].replace("Additional Handling threshold", "Additional Handling minimum billable weight")
        if t != s["title"]:
            s["title"] = t; log.append("B7  UPS 2027 title: minimum billable weight")
        if s.get("dates") != [UPS27_DATE]:
            s["dates"] = [copy.deepcopy(UPS27_DATE)]; log.append("B5  UPS 2027 clock: one 5.9% line with sub-items")
    # B5: the UPS fuel story's third label was cut at 70 characters; use the change's full wording
    s = find(news, UPS_FUEL)
    if s:
        full = {f"UPS: {c.get('what')}"[:70]: f"UPS: {c.get('what')}" for c in s.get("changes") or [] if c.get("what")}
        for d in s.get("dates") or []:
            w = d.get("w") or ""
            if len(w) == 70 and w in full and full[w] != w:
                d["w"] = full[w]; log.append(f"B5  {UPS_FUEL} clock label restored: {d['w']}")

    # B12: one story for the Oct 13 parcel index study
    keep = find(news, INDEX_KEEP)
    if keep:
        extra = [x for d in INDEX_DUPES for x in ((find(news, d) or {}).get("srcs") or [])]
        merged = union_srcs(keep.get("srcs"), extra)
        if merged != keep.get("srcs"):
            keep["srcs"] = merged; log.append(f"B12 {INDEX_KEEP}: {len(merged)} sources")
        tc = "The analysis comes from investment bank TD Cowen and a parcel analytics firm, FreightWaves reported."
        if any("freightwaves.com" in (x.get("url") or "") for x in merged) and tc not in keep["sum"]:
            keep["sum"] = keep["sum"].rstrip() + " " + tc
    # B12 / B16: stories that leave the feed (logged in drop.json, which the pipeline's dedupe_live honors)
    gone = set(DROPS)
    before = len(news)
    news[:] = [s for s in news if s.get("id") not in gone]
    if len(news) != before:
        log.append(f"B12 B16 removed {before - len(news)} stories from the feed")

    # B17: the Larsen interview story keeps its own Supply Chain 24/7 interview link, loses the Germany page
    s = find(news, LARSEN)
    if s and any(x.get("url") == GERMANY for x in s.get("srcs") or []):
        s["srcs"] = [x for x in s["srcs"] if x.get("url") != GERMANY]
        s["src"], s["url"] = s["srcs"][0]["src"], s["srcs"][0]["url"]
        log.append(f"B17 {LARSEN}: unrelated Germany link removed; source is {s['src']}")

    # B19: USPS holiday send-by dates
    s = find(news, USPS_HOL)
    if s:
        want = {
            "title": "USPS recommends Dec. 17 Ground Advantage send-by date for the lower 48",
            "kind": "Reminder",
            "ann": "2026-09-22",
            "sum": "USPS announced its recommended 2026 holiday send-by dates on Sept. 22, and WSYR-TV repeated them in October. "
                   "For delivery before Dec. 25 in the lower 48 states, Ground Advantage and First-Class items are to be sent by "
                   "Dec. 17, Priority Mail by Dec. 18 and Priority Mail Express by Dec. 19. Ground Advantage to Alaska, Hawaii, "
                   "Puerto Rico and the territories should go by Dec. 16.",
        }
        for k, v in want.items():
            if s.get(k) != v:
                s[k] = v; log.append(f"B19 {USPS_HOL}: {k}")
        usps = {"src": "USPS Newsroom", "url": USPS_HOLIDAY, "checked": CHECKED}
        if not any(x.get("url") == USPS_HOLIDAY for x in s.get("srcs") or []):
            s["srcs"] = [usps] + (s.get("srcs") or [])
            s["src"], s["url"] = usps["src"], usps["url"]
            log.append(f"B19 {USPS_HOL}: USPS release added as the lead source")
        if s.pop("unconf", None):
            log.append(f"B19 {USPS_HOL}: no longer single-source")


def fix_drop(drop, log):
    have = {d if isinstance(d, str) else (d or {}).get("id") for d in drop}
    for sid, why in DROPS.items():
        if sid not in have:
            drop.append({"id": sid, "why": why}); log.append(f"drop.json + {sid}")


def fix_threads(threads, pool, log):
    for k, f in THREAD_FIX.items():
        t = threads.get(k)
        if not t:
            log.append(f"B18 storyline {k} not found, skipped"); continue
        ids = [i for i in t.get("ids", []) if i not in set(f.get("remove", []))]
        for i in f.get("add", []):
            if i not in ids:          # in date order, before the first member dated later; the others keep their order
                d = (pool.get(i) or {}).get("date") or ""
                at = next((n for n, j in enumerate(ids) if ((pool.get(j) or {}).get("date") or "") > d), len(ids))
                ids.insert(at, i)
        if ids != t.get("ids"):
            t["ids"] = ids; log.append(f"B18 {k}: stories {', '.join(ids)}")
        dates = [(pool.get(i) or {}).get("date") for i in ids if (pool.get(i) or {}).get("date")]
        if dates and t.get("last") != max(dates) and (f.get("add") or f.get("remove")):
            t["last"] = max(dates)
        if "s" in f and t.get("s") != f["s"]:
            t["s"] = f["s"]; log.append(f"B18 {k}: summary rewritten from member stories")
        cx = t.get("cx")
        if "now" in f and cx is not None and cx.get("now") != f["now"]:
            cx["now"] = f["now"]; log.append(f"B18 {k}: where it stands -> {f['now']}")
        elif "now" in f and cx is None:
            t["cx"] = cx = {"beats": {}, "now": f["now"]}
        if "intro" in f and cx is not None and cx.get("intro") != f["intro"]:
            cx["intro"] = f["intro"]; log.append(f"B18 {k}: intro rewritten")
        if cx is not None:
            beats = cx.setdefault("beats", {})
            for i in f.get("remove", []):
                beats.pop(i, None)
            for i, b in (f.get("beats") or {}).items():
                beats.setdefault(i, b)
            # the robots re-narrate a storyline only when its stories change: mark this narration as current for these ids
            if f.get("add") or f.get("remove"):
                cx["sig"] = h(",".join(i for i in ids if i in pool))
                cx.setdefault("v", 3)
        if f.get("add") or f.get("remove"):
            t["rv"] = h(",".join(ids))


def fix_almanac(alm, log):
    i = next((i for i, e in enumerate(alm) if e.get("id") == UPS27_ALM["id"]), None)
    if i is None:
        alm.append(copy.deepcopy(UPS27_ALM)); i = len(alm) - 1; log.append("B14 + almanac ups-2027-gri")
    elif alm[i] != UPS27_ALM:
        alm[i] = copy.deepcopy(UPS27_ALM); log.append("B14 almanac ups-2027-gri: announced, 5.9%, Dec 21, 2026")
    if not any(e.get("id") == SBR_ALM["id"] for e in alm):
        alm.insert(i + 1, copy.deepcopy(SBR_ALM)); log.append("B14 + almanac " + SBR_ALM["id"])
    else:
        j = next(j for j, e in enumerate(alm) if e.get("id") == SBR_ALM["id"])
        if alm[j] != SBR_ALM:
            alm[j] = copy.deepcopy(SBR_ALM)


def fix_deals(deals, log):
    def one(buyer, target):
        return next((x for x in deals if x.get("buyer") == buyer and x.get("target") == target), None)

    x = one("C.H. Robinson", "RXO")
    if x is None:
        log.append("B12 C.H. Robinson-RXO overlay not found, skipped")
    elif x.get("value") != "$5.8 billion implied transaction value":
        x["value"] = "$5.8 billion implied transaction value"; log.append("B12 C.H. Robinson-RXO value")
    x = one("DHL eCommerce International Holdings", "Venipak Lietuva, Venipak Latvija and Venipak Eesti")
    if x is None:
        log.append("B12 DHL-Venipak deal not found, skipped")
    else:
        if x.get("ann") != "2026-07-27":
            x["ann"] = "2026-07-27"; log.append("B12 DHL-Venipak announced 2026-07-27")
        # the announcement's own source (DHL Group's release, story nr1dab23, already in the deal's ties) goes with the date
        x["srcs"] = union_srcs([{"src": "DHL Group", "url": DHL_VENIPAK}], x.get("srcs"))
    x = one("Thoma Bravo", "WWEX Group (combined with Auctane)")
    latest = "WWEX Group and Auctane completed their merger on June 1, 2026; the combined company is named ShipStation Global."
    if x is None:
        log.append("B12 Thoma Bravo overlay not found, skipped")
    elif x.get("latest") != latest:
        x["latest"] = latest; log.append("B12 Thoma Bravo: combined company ShipStation Global")


def fix_docs(docs, log):
    for (c, n), d_text in RETIRED.items():
        d = next((d for d in docs if d.get("c") == c and d.get("n") == n), None)
        if d is None:
            log.append(f"B21 not in data/docs.json (index.html DOCLIB only): {c}: {n}"); continue
        want = {"cur": False, "d": d_text, "checked": CHECKED}
        if any(d.get(k) != v for k, v in want.items()):
            d.update(want); log.append(f"B21 retired: {c}: {n}")


def fix_state(curated, alm_state):
    """The editor pass and the almanac reader skip stories they have already seen; these two were written by hand."""
    cur = sorted(set(curated) | {SBR_ID, FXF_ID})
    read = list(alm_state.get("read", []))
    if SBR_ID not in read:
        read.append(SBR_ID)
    return cur, dict(alm_state, read=read)


def main(dry=False):
    files = {k: load(k + ".json", None) for k in ("news", "threads", "almanac", "deals", "docs", "drop", "curated", "almanac_state")}
    before = {k: json.dumps(v, ensure_ascii=False) for k, v in files.items()}
    log = []
    fix_news(files["news"], log)
    fix_drop(files["drop"], log)
    seed = load("seed.json", {})
    pool = {s["id"]: s for s in seed.get("news", []) + files["news"] if s.get("id")}
    fix_threads(files["threads"], pool, log)
    fix_almanac(files["almanac"], log)
    fix_deals(files["deals"], log)
    fix_docs(files["docs"], log)
    files["curated"], files["almanac_state"] = fix_state(files["curated"], files["almanac_state"])
    changed = [k for k, v in files.items() if json.dumps(v, ensure_ascii=False) != before[k]]
    print("\n".join(log) or "nothing to change")
    print("changed:", ", ".join(changed) or "none")
    if not dry:
        for k in changed:
            save(k + ".json", files[k])
    return changed


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
