#!/usr/bin/env python3
"""Oct 26, 2026: the year's three themes (data/themes.json) become storylines of their own in data/threads.json, with Coop's
walk-through and the news that ties to the underlying strategy. Every line below paraphrases the story it sits on.
New matching stories join later (pipeline/news.py roll_into_themes). Idempotent. Run: python3 tools/themes_to_storylines.py"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import h  # noqa: E402

BEATS_V = 3                                     # pipeline/news.py: a narration at this version is kept as written

THEMES = {
    "theme-ecommerce-split": {
        "n": "Splintering of eCommerce parcel from B2B/Premium parcel",
        "s": "UPS has cut Amazon volume by more than half and FedEx has spun off Freight and sold Supply Chain, while GOFO, Veho, OnTrac and "
             "other alternative carriers keep expanding. UniUni's go-public deal was terminated on Oct. 20.",
        "intro": "E-commerce parcel is splitting from B2B and premium parcel: alternative carriers gain share while UPS and FedEx pull back from e-commerce.",
        "now": "UPS and FedEx keep narrowing toward premium and logistics work while alternative carriers expand; UniUni's listing fell through Oct. 20.",
        "beats": {
            "h404": "Shein and Temu together sent almost 600,000 U.S. packages a day, a marketplace flow big enough to tighten air cargo out of China.",
            "h417": "Pitney Bowes sold a controlling stake in its Global Ecommerce unit and two entities filed Chapter 11; the unit lost about $136 million in 2023.",
            "h501": "UPS stopped handing Ground Saver parcels to USPS and delivered them itself, raising Ground Saver rates by nearly 10%.",
            "h503": "UPS said it will cut Amazon volume by more than half by the second half of 2026; Amazon was nearly 12% of its revenue.",
            "h513": "The $800 duty-free de minimis exemption ended for China and Hong Kong goods on May 2, 2025.",
            "h521": "Last-mile carrier UniUni raised $70 million to extend its North American network.",
            "h526": "De minimis ended for all countries on Aug. 29, 2025; the UPU said at least 25 countries halted postal shipments to the U.S.",
            "h531": "GOFO committed over $150 million to Los Angeles and Newark super hubs; it says its hubs cover 70% of the U.S. population.",
            "43": "FedEx began merging its Ground and Express pickup and delivery, with the U.S. rollout complete by the end of 2027.",
            "g16": "OnTrac expanded its ShipStation integration with marketplace shipping and pricing for packages under one pound.",
            "63": "Veho, Better Trucks, Jitsu, OnTrac and GOFO all added coverage or services; GOFO acquired Cirro E-Commerce.",
            "g15": "Veho said its network grew to 68 markets covering 46% of the U.S. population, and that parcel volume doubled.",
            "60": "UniUni agreed to go public through MAK Acquisition at about US$1.0 billion, reporting more than 1 million parcels a day.",
            "g09": "DHL eCommerce and USPS signed an exclusive multi-year last-mile contract valued at well over $10 billion.",
            "18": "UPS closed 23 buildings and planned about 30,000 job cuts for 2026 after cutting Amazon volume by more than half.",
            "nrf79508": "GOFO doubled its Dallas-area hub to 800,000 parcels a day and says its network reaches about 75% of the U.S. population.",
            "54": "Priority Courier Experts, owned by Trident Management, bought three regional couriers handling over 1 million pieces a year.",
            "rv5-fedex-freight-spin-done": "FedEx completed the FedEx Freight spin-off on June 1, 2026; Freight now trades separately as FDXF.",
            "52": "FedEx sold FedEx Supply Chain to CMA CGM for $1.4 billion; it folds into CEVA Logistics.",
            "a66617050d4e9": "Analysts disagree on whether UPS's stated focus on premium and logistics services means it will leave parts of parcel delivery.",
            "afb6fa67940a7": "MAK terminated the UniUni purchase agreement on Oct. 20; the planned go-public deal will not proceed.",
        },
    },
    "theme-ups-teamsters": {
        "n": "Continued battle between UPS and the Teamsters",
        "s": "The Driver Choice buyout is capped at 7,500 drivers, the Teamsters are challenging UPS over its Roadie gig deliveries, and the "
             "union's president has called a strike likely when the contract ends July 31, 2028.",
        "intro": "UPS is working to control labor costs while the Teamsters push back, and both are positioning for the contract that ends July 31, 2028.",
        "now": "Driver Choice is capped at 7,500 drivers, the Teamsters are challenging UPS over Roadie, and a 2028 strike is called likely.",
        "beats": {
            "h406": "UPS's Network of the Future plan: close or consolidate about 200 U.S. facilities and reach 400 automated buildings by the end of 2028.",
            "h511": "UPS said it will cut about 20,000 positions in 2025 and close 73 buildings by the end of June.",
            "a13f12c1da7be": "UPS and the Teamsters settled the Driver Choice dispute, capping it at 7,500 drivers and barring another severance program until July 31, 2028.",
            "g33": "An NLRB judge approved an Amazon DSP settlement without a joint-employer finding; the Teamsters called it a 'sham settlement'.",
            "g32": "Teamsters delegates voted to challenge UPS over routing work to its Roadie gig subsidiary; UPS says it complies with the contract.",
            "50": "An analyst argued the 2028 outcome will reshape the market: a hard line leaning on Roadie could let UPS dominate, concessions could shrink it.",
            "35": "Teamsters president Sean O'Brien said a strike is likely when the contract ends July 31, 2028.",
            "nr59b2c5": "Amazon added $1.9 billion to its Delivery Service Partner program for 2027, aimed at lifting delivery associate pay to nearly $24 an hour.",
            "acb44dbafb712": "An NLRB judge ruled UPS unlawfully restricted union insignia on safety vests; UPS plans to appeal.",
            "a66617050d4e9": "Analysts are split on whether UPS's pivot to premium and logistics services means leaving parts of parcel, as the 2028 talks near.",
            "abaae70647f04": "UPS and the Teamsters agreed to offer Driver Choice nationwide: $150,000 early-retirement payments, capped at 7,500 drivers.",
            "a57a06c26359c": "Amazon TOM Team drivers at an Indiana facility joined Teamsters Local 142 and asked Amazon to recognize the union.",
        },
    },
    "theme-amazon-insourcing": {
        "n": "Amazon insourcing volume (largest U.S. parcel carrier in 2025)",
        "s": "UPS finished cutting Amazon volume by more than half, Amazon and USPS agreed to trim its USPS volume by about 20%, and Amazon is "
             "opening its logistics network to outside businesses.",
        "intro": "Amazon is moving more of its volume into its own network and opening that network to others. It was the largest U.S. parcel carrier by volume in 2025.",
        "now": "UPS has finished its Amazon cutback, USPS kept most of Amazon's volume, and Amazon is selling its network to outside businesses.",
        "beats": {
            "h408": "Pitney Bowes counted Amazon Logistics at 5.9 billion U.S. parcels in 2023, passing UPS at 4.6 billion; USPS led at 6.6 billion.",
            "h503": "UPS said it will cut Amazon volume by more than half by the second half of 2026; UPS shares fell more than 14%.",
            "h511": "UPS said it will cut about 20,000 jobs and close 73 buildings as Amazon volume shrinks.",
            "h512": "Amazon said it will invest $4 billion by the end of 2026 to expand its rural delivery network to more than 200 delivery stations.",
            "h517": "FedEx confirmed a multi-year deal to deliver large packages for Amazon; Amazon said it does not replace UPS capacity.",
            "19": "Amazon handled 6.7 billion parcels in 2025 versus 6.6 billion for USPS, the largest U.S. carrier by volume; UPS still earns the most revenue.",
            "r01": "ShipMatrix: Amazon Logistics grew 9.9% to 6.7 billion parcels in 2025 while USPS and UPS each fell 8.6%.",
            "21": "After reports Amazon would cut its USPS volume by two-thirds, the two agreed to a cut of about 20%.",
            "18": "UPS closed 23 buildings and planned about 30,000 job cuts after cutting Amazon volume by more than half.",
            "17": "Amazon opened its logistics network, freight, warehousing and parcel delivery, to outside businesses; UPS and FedEx shares each fell about 9 to 10%.",
            "05": "Business Insider reported 'Project Aurelian,' a backup plan to extend Amazon's own delivery to about 95% of U.S. ZIP codes by 2029.",
            "aba40a11b6946": "An Amazon vice president said the network opened to all businesses after sellers asked to use it for off-Amazon volume.",
            "ae3846ec1ac41": "Jefferies said Amazon could grow U.S. delivery stations from about 575 to 950 by 2030 and carry more third-party parcels.",
            "a63ee5425135a": "An analysis says UPS's U.S. profit per package rose to about $1.16 from about $0.93 after the Amazon cutback; the math is the author's.",
        },
    },
}
ROLLUP = {
    "theme-ecommerce-split": r"alternative carrier|regional carrier|\bGOFO\b|\bVeho\b|\bOnTrac\b|\bUniUni\b|Better Trucks|\bJitsu\b|de minimis|FedEx (Supply Chain|Freight)|Ground Saver",
    "theme-ups-teamsters": r"Teamsters|Driver Choice|collective bargaining|Roadie|NLRB.*UPS|UPS.*NLRB|UPS.*2028",
    "theme-amazon-insourcing": r"Amazon.*(largest|volume|logistics network|delivery network|insourc)|(UPS|FedEx|USPS).*Amazon (volume|cutback)",
}


def apply():
    news = {n["id"]: n for n in json.loads((ROOT / "data/news.json").read_text())}
    news.update({n["id"]: n for n in json.loads((ROOT / "data/seed.json").read_text()).get("news", [])})
    tp = ROOT / "data/threads.json"
    threads = json.loads(tp.read_text())
    changed = 0
    for key, th in THEMES.items():
        ids = sorted((i for i in th["beats"] if i in news), key=lambda i: news[i]["date"])
        miss = [i for i in th["beats"] if i not in news]
        assert not miss, (key, miss)
        old = threads.get(key) or {}
        if old and old.get("ids") and set(old["ids"]) > set(ids):
            ids = sorted(old["ids"], key=lambda i: news[i]["date"]) if all(i in news for i in old["ids"]) else ids   # keep stories the pipeline added
        sig = h(",".join(ids))
        beats = {i: v for i, v in th["beats"].items() if i in ids}
        cos = sorted({c for i in ids for c in news[i].get("c", []) if c not in ("Industry", "Regional")})
        t = {"n": th["n"], "s": th["s"], "ids": ids, "first": news[ids[0]]["date"], "last": news[ids[-1]]["date"], "c": cos,
             "theme": True, "rv": sig, "cx": {"sig": sig, "v": BEATS_V, "beats": beats, "intro": th["intro"], "now": th["now"]}}
        if old.get("cx", {}).get("sig") == sig and old.get("cx", {}).get("beats"):          # the pipeline narrated a newer set: keep its lines
            t["cx"] = old["cx"]
        if threads.get(key) != t:
            threads[key] = t
            changed += 1
    tp.write_text(json.dumps(threads, indent=1, ensure_ascii=False) + "\n")
    mp = ROOT / "data/themes.json"
    themes = json.loads(mp.read_text())
    for tm, key in zip(themes["themes"], THEMES):
        tm["thread"], tm["rollup"] = key, ROLLUP[key]
        tm.pop("stories", None)
    mp.write_text(json.dumps(themes, indent=1, ensure_ascii=False) + "\n")
    return changed


if __name__ == "__main__":
    print("changed", apply())
