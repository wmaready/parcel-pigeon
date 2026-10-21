"""Collect parcel news, keep what matters to shippers, and write plain-English stories.

Run: python pipeline/news.py
Writes data/news.json (live stories) and data/review.json (things a person should check).
"""
import datetime as dt, difflib, json, os, re, sys, urllib.parse
import feedparser, requests, trafilatura, yaml
from common import dedupe_live, ROOT, load, save, h, get, claude, parse_json, numbers_supported, MODEL_FAST, MODEL_WRITE, is_primary, primary_first, clock_worthy, tier, _words, not_a_source, cycle_of, kind_of
from scoop import is_covered, notify, PRESS, ask, big, keywords

MAX_NEW_PER_RUN = 18          # cost guard: stories written per run (about 2-4 cents each); the rest wait for the next run
MAX_AGE_DAYS = 7
MAX_SCREEN = 160              # headlines screened per run (fast model, 20 per call), best outlets first; the rest wait
PER_FEED = 100                # entries read from each feed or search (Google News returns up to 100)
KEEP_LIVE = 250

CATEGORIES = ["Peak season", "Pricing & GRI", "Fees & rules", "Fuel", "Technology & tools", "Carrier strategy", "Postal",
              "Amazon", "Regional & alternative", "Network & operations", "Deals & partnerships", "Labor",
              "Regulation & trade", "International", "Earnings & markets", "Documents", "M&A",
              "Same-day & gig delivery", "Partnerships", "3PL & fulfillment", "Cold chain", "Drones & robots", "Legal",
              "Market reports", "Guide changes"]
CARRIERS = ["UPS", "FedEx", "USPS", "Amazon", "OnTrac", "DHL", "Regional", "Industry"]

PREFILTER = re.compile(r"\b(ups|fedex|usps|postal|amazon|ontrac|dhl|parcel|package|surcharge|gri|rate increase|fuel|"
                       r"last[- ]mile|delivery|shipping|shipper|carrier|teamsters|de minimis|tariff|ground advantage|"
                       r"veho|uniuni|gofo|lso|spee-dee|doordash|uber freight|returns|api|rfid|label|tracking|software|integration|"
                       r"network 2\.0|strategy|investor day|ceo|chief|restructur\w*|acquisition|automation|robot\w*|ai)\b", re.I)

TRIAGE_SYSTEM = f"""You screen news for Parcel Pigeon, a news app for anyone in small parcel shipping.
Keep EVERY item related to small parcel: carriers (UPS, FedEx, USPS, Amazon Shipping, OnTrac, DHL, regional and
alternative carriers, gig and courier networks), pricing, surcharges, fuel, networks and service, labor, regulation
and trade that touches parcels (tariffs, de minimis, customs, postal law), carrier finances, carrier technology and tools,
carrier strategy and leadership, e-commerce delivery and returns, EVERY item about regional and alternative carriers
(OnTrac, Spee-Dee, GLS US, UniUni, LSO, Veho, Better Trucks, GOFO, Jitsu, CDL, Pitney Bowes, DHL eCommerce, SpeedX, Dragonfly
and similar), EVERY merger, acquisition, sale, spin-off, SPAC, IPO or major funding round involving any parcel carrier, courier,
shipping software or parcel reseller, EVERY item on gig and on-demand delivery platforms (DoorDash, Uber Eats/Uber Direct, Instacart,
Shipt, Gopuff, Roadie) and retailers' same-day/next-day delivery programs and the partnerships behind them, EVERY carrier
partnership (national or regional) with retailers, marketplaces, gig platforms or tech firms, 3PL and fulfillment news, cold chain
and healthcare parcel logistics, AI and software for shipping (rating, audit, routing, agents), drones and delivery robots and the
rules that govern them (e.g. FAA Part 108), and lawsuits, labor cases, regulatory actions and patent or antitrust suits touching
parcel delivery, EVERY release of a parcel or e-commerce shipping market report, index, survey or forecast (Pitney Bowes,
ShipMatrix, Adobe, Deloitte, NRF, Narvar, AlixPartners, Logistics Managers' Index, Census, USPS OIG, PRC and similar; category
"Market reports", kind "Analysis"), AND opinion pieces, commentary, analysis, interviews
and general industry news, even when there is no price change. Freight, ocean, LTL and trucking items are kept ONLY if
they state a direct effect on small parcel. Drop items that are not about parcel at all, pure stock tips, sponsored
content, and anything about one private shipper's own contract.

International items: this is a U.S. parcel news service. Keep a non-U.S. item ONLY if (a) it affects U.S. shipping or
U.S. shippers (tariffs, de minimis, customs, cross-border lanes into or out of the U.S., carriers or platforms that serve
U.S. shippers, U.S. carriers' international networks), or (b) it is a big move by a national post or a global carrier
or logistics group (India Post, Canada Post, Royal Mail, Deutsche Post/DHL, Japan Post and similar): a major partnership,
a major acquisition or sale, a new service, a network overhaul, a strike. DROP small local or regional foreign items
(a state government's shipment of local goods, a small foreign courier's new depot, local festival or crop shipments,
one city's delivery tweak) and small foreign carriers' routine news. When unsure, drop it.

Local items: DROP routine hyper-local U.S. items: one post office's hours or temporary closure, one facility's hours, local
holiday-deadline reminders, a petty local crime. KEEP local items that are news for the industry: a new service reaching a
town (drone or robot delivery starting somewhere), a federal raid or fraud or theft ring, a facility closure under a named
national program, a first-of-its-kind service. Those are fine as stories; they just don't start storylines (they may join
a company's ACTIVE storyline when they are the next chapter of that company's saga).
Late reports: DROP an item from a smaller or local outlet that reports, as if new, an event that happened weeks earlier and
that the major parcel and freight outlets already covered (check RECENT STORIES and the dates in the summary). DROP non-stories
(a site adding its own guides or directories, listicles, SEO explainers, product promotions). A "not yet announced" item IS a
story when the wait itself matters to shippers (e.g. UPS announcing its general rate increase later than FedEx, leaving
shippers less time to prepare).
Outlets: each item shows its outlet tier: T0 the company or regulator itself, T1 major business or wire press (Reuters, WSJ,
Bloomberg, CNBC, AP and similar), T2 parcel and logistics trade press, T3 everything else (local papers, aggregators,
press-release reposts, blogs). Keep EVERY T0, T1 and T2 item that is about small parcel. Be stricter with T3: keep it when
it adds a fact, a development or a local first-of-its-kind the others don't have; drop T3 rewrites of news the bigger
outlets carried. Each item also shows its publish date; compare it with the event's own date in the summary.
Discussion pieces: KEEP well-made commentary, columns, interviews and explainers from the parcel and freight trade press
(PARCEL magazine / parcelindustry.com, FreightWaves, Supply Chain Dive, DC Velocity, Logistics Management, SupplyChainBrain,
Post & Parcel) when they are about small parcel; mark kind "Opinion" (a view or argument) or "Analysis" (informational).

You also get RECENT STORIES already published (id: title) and ACTIVE STORYLINES (key: name). If an item reports the
same event as a recent story and adds NO new development, set "same_as" to that id. A new development in an ongoing story
(a new offer in labor talks, a ruling, a deal closing, a rate taking effect, a follow-up with new facts) is NOT same_as: keep
it as its own item and put it in that storyline. Storylines are how a news desk follows a subject over weeks or months. Be strict: an item joins a storyline only when it is directly about that
same subject (same company or program AND the same issue), not merely the same company or a loosely related theme.
One exception: a smaller or regional company's ongoing saga is ONE storyline. When a regional or alternative carrier, courier
or startup goes through a connected chain of events (funding, a go-public or sale deal and its fallout, the service trouble or
lawsuits that come with fast growth), use that company's ACTIVE storyline (the [company] shown with each one), whichever outlet
reports it, instead of opening a second storyline for the same company. Check the ACTIVE STORYLINES for the item's main company
before you make a new key. Only
small-parcel subjects get storylines (carrier pricing and surcharges, carrier networks and service, carrier labor, postal
policy and finances, parcel regulation and trade rules, deals that reshape who delivers parcels, delivery tech rolling out at
scale). No storylines for general finance (a private-equity firm selling a tech unit, stock moves), local events,
or opinion pieces; give those "thread": null. A storyline is a clear arc of real developments (announced, changed, ruled,
closed, took effect, or a confirmed wait for one), not a pile of related articles; when unsure, "thread": null. Items marked SUPPORTING SOURCE ONLY (other consultancies and audit firms) should get "same_as" when they cover a recent story and keep=false otherwise. Items in this batch that cover the same event as each other get the same short "event" key
(e.g. "ups-2027-gri"); every other kept item gets its own unique key.

Reply with JSON only: a list of objects
{{"i": index, "keep": true|false, "carriers": [subset of {CARRIERS} that the item is ABOUT (the subject or the acting party),
never a carrier only mentioned, compared or quoted in passing; ["Industry"] if no specific carrier],
"company": the one company the item is mainly about, by its common name (e.g. "UniUni", "UPS", "Royal Mail"), or null,
"category": one of {CATEGORIES}, "kind": "News"|"Opinion"|"Analysis", "event": short key, "same_as": id or null,
"score": 1-10 for how much the item matters to U.S. parcel shippers (10 = a dated price change from UPS, FedEx or USPS affecting most shippers; 7-9 = a big carrier network, labor, regulation or deal move; 4-6 = a regional carrier, platform or report worth knowing; 1-3 = minor or local),
"fit": "core" if it is plainly small parcel news, "edge" if you are keeping it but it is only loosely tied to small parcel
(general freight, trucking or ocean, broad retail or economy, tech not specific to shipping, a local story),
"thread": the key of the ACTIVE STORYLINE it belongs to, or a new short lowercase key (e.g. "ups-teamsters-contract",
"usps-delivering-for-america", "de-minimis-end", "fedex-network-2", "ups-amazon-glide-down", "2027-gri") when it is part of a
subject likely to keep developing (labor talks, lawsuits and rulings, regulation, network overhauls, pending deals, a rate
cycle, a carrier's ongoing strategy), or null for a one-off item. Yearly events (holiday peak surcharges, the annual
rate increase, USPS price changes) use the ACTIVE storyline for that subject; the app splits it by year on its own}}."""

WRITE_SYSTEM = f"""You write for Parcel Pigeon, a small parcel trade news service in the style of Supply Chain Dive and
FreightWaves: neutral, factual, attributed. Use ONLY facts in the articles provided. Never invent numbers, dates or names;
every number must appear in the source text. Do not quote more than a few words. No advice, no recommendations, no
predictions of your own, no adjectives that judge (no "good news", "pain", "win"). Attribute claims ("UPS said",
"according to the filing"). If the source is an opinion or analysis, say whose view it is.

Never name a parcel consultancy or audit firm (TransImpact, Reveel, Shipware, Transportation Insight, Intelligent Audit,
Sifted, Lojistic, LJM Group, AFS and similar) in the title or text: call their work "an industry analysis".

Return JSON only, with exactly these keys:
"title": wire-style headline under 90 characters, subject first, present tense (e.g. "FedEx sets 5.9% average increase for 2027");
"sum": 1-3 sentences: what happened, who, when, key figures;
"imp": "up" if shippers' prices or fees rise, "down" if they fall, "watch" if the item is a developing matter, "info" otherwise;
"lvl": 1, 2 or 3 for how directly it changes shipper prices or service (3 = a dated price change for most shippers);
"docs": list of official carrier, USPS or regulator documents (or, for Market reports, the report itself) linked in the sources (rate guides, service guides,
  surcharge or fuel tables, notices, tariffs, filings), each {{"c":"carrier","t":"Rate guide|Service guide|GRI notice|Surcharges & fees|Peak|Fuel|Zones & DAS|Special program|Terms|Regulatory filing",
  "n":"the document's own title with year","y":year it applies to or null,"eff":"YYYY-MM-DD or null","u":"exact URL from the sources"}}; [] if none;
"tie": one sentence linking this to earlier related news ABOUT THE SAME COMPANY that the sources themselves mention (with month/year), or null. Never tie a story to another carrier's news;
"why": one sentence under 160 characters on why this matters to parcel shippers or the parcel market, from the sources only (who is affected and how big); never generic;
"plain": 1-2 sentences of the direct, factual effect on shippers (what changes, for whom, from when). If nothing changes
         for shippers, say so plainly (e.g. "No change to rates or service.");
"event_date": "YYYY-MM-DD" the day the company ANNOUNCED it (or the event happened), if the sources say and it is earlier than the article, else null;
"act": "YYYY-MM-DD" the day it TAKES EFFECT, if one is stated, else null. The announcement date and the effective date are
  different things: never put one in the other's place, and never infer an effective date from when it was announced;
"dates": list of {{"d":"YYYY-MM-DD","w":"what changes that day, under 70 characters","imp":"up|down|info","fx":null}} for future dates in the source
         about THIS story's own company only (never other carriers' events the article mentions in passing; one event per entry)
         ONLY when shippers' prices, surcharges, fees, service levels or rules change that day, or for a big industry event that
         shippers plan around (a network change, a regulation taking effect, a labor contract expiring). NEVER court dates,
         sentencing, hearings, trials, earnings calls, conferences or other dates about a person or a case; [] if none.
         "fx" drives the rate clock's animated explainer. Fill it ONLY with figures stated in the sources, else null:
         {{"t":"gri","car":"FedEx","pct":5.9}} for a general rate increase; {{"t":"das","added":1200,"fee":"$4.70"}} for a
         delivery-area ZIP list change; {{"t":"fuel","car":"UPS","diesel":4.10,"old":22.5,"new":24.0}} for a fuel table change;
         {{"t":"fee","car":"FedEx","items":[["what the fee is for","$25.00",25]]}} for a new flat fee;
         {{"t":"zone","car":"FedEx"}} for a zone chart change;
"category": one of {CATEGORIES} (use "M&A" for mergers, acquisitions, sales, spin-offs, SPACs, IPOs and funding rounds);
"kind": "News", "Opinion" or "Analysis";
"carriers": subset of {CARRIERS} that the story is ABOUT (the subject or the acting party), never a carrier only mentioned,
  compared or quoted in passing (a story about Amazon's delivery plans is ["Amazon"], not also USPS, UPS and FedEx), or ["Industry"];
"orgs": companies in the parcel world that the story is about (carriers, couriers, gig and last-mile networks, 3PLs, shipping
  or returns software, drone/robot delivery firms, retailers' delivery arms, investors in these): [{{"name":"...","what":"one line on
  what it does, from the sources","realm":"same realm names as deal parties"}}]; skip law firms, agencies, people and generic shippers; [] if none;
"rels": every business relationship between named companies that the sources state, for ANY story (not just M&A):
  [{{"a":"Company A","b":"Company B","k":"partner|acquired|merged|sold|spun|invested|owns","t":"short plain label, e.g. 'DoorDash and Kroger expand delivery partnership'"}}];
  a = buyer/owner/investor/seller; b = target/unit. Only real, announced relationships; [] if none;
"deal": for M&A only, else null. {{"title":"Buyer buys Target, under 10 words","buyer":"...","target":"...","value":"... or Undisclosed",
  "status":"Announced|Pending|Closed","ann":"YYYY-MM-DD announced or null","closed":"YYYY-MM-DD closed or null",
  "sum":"1-2 sentences: who bought what, from whom, for how much",
  "who":[["Buyer|Seller|Target|Merged with|Acquirer","Name","one sentence: what the company is and does"], ...],
  "why":"2-4 neutral sentences on significance: scale, what changes in the parcel market, and any earlier deals or news the sources connect it to. No advice.",
  "parties":[{{"name":"...","role":"Buyer|Seller|Target|Merged with|Acquirer|Parent|Backer","realm":"Ocean shipping & logistics|Contract logistics / 3PL|National parcel carrier|Postal operator|Gig / on-demand delivery|Retailer / marketplace|Cold chain / healthcare logistics|Drones, robots & autonomous delivery|Regional / last-mile carrier|Courier / same-day|Freight brokerage & parcel reselling|Shipping software|Supply chain software|Returns & reverse logistics|Private equity / investor|SPAC / public markets|Cross-border parcel platform","hq":"city, country or null","founded":"year or null","size":"one number fact or null","history":[{{"y":"YYYY","t":"prior owners, mergers, renames, funding, only as stated in the sources"}}]}}],
  "tree":{{"n":"top owner after the deal","c":[{{"n":"unit","nw":1 if newly added,"c":[...]}}]}},
  "note":"one line"}}.
When given several articles about the same event, write ONE story combining their facts. If one article is the company's
own announcement or filing, it is the source of truth: take every figure and date from it, and use the press articles only
for context it does not cover. Where they conflict, use the company's figure."""




_NAMES = None


def _names():
    """Every company on the map as (id, regex), longest names first, so 'FedEx Ground' wins over 'FedEx'."""
    global _NAMES
    if _NAMES is None:
        allp = load("seed.json", {}).get("players", []) + load("players.json", {}).get("players", [])
        out = []
        for p in allp:
            for nm in [p.get("n")] + (p.get("al") or []):
                if nm and len(str(nm)) > 2:
                    out.append((p["id"], p.get("parent"), str(nm)))
        out.sort(key=lambda x: -len(x[2]))
        _NAMES = [(i, par, re.compile(r"(?<![A-Za-z0-9])" + re.escape(nm) + r"(?![A-Za-z0-9])")) for i, par, nm in out]
    return _NAMES


def _cos(text):
    return {i for i, _, rx in _names() if rx.search(text or "")}


def own_only(story):
    """Keep a story's dates and context line about its own companies (tagged carriers and companies in the headline, with
    their parents and arms). A clause naming only other companies is dropped; stories with no company of their own keep all."""
    fam = {i: par for i, par, _ in _names()}
    tags = {str(c).lower() for c in story.get("c") or [] if c not in ("Industry", "Regional")}
    own = _cos(story.get("title", "")) | {i for i, _, rx in _names() if any(rx.pattern and rx.search(c) for c in (story.get("c") or []) if c not in ("Industry", "Regional"))}
    if not own and not tags:
        return
    own |= {fam.get(i) for i in own if fam.get(i)} | {i for i, par in fam.items() if par in own}
    foreign = lambda t: bool(_cos(t)) and not (_cos(t) & own)
    keep = []
    for d in story.get("dates") or []:
        if not isinstance(d, dict) or not d.get("w"):
            continue
        parts = [x for x in re.split(r"\s*;\s*", str(d["w"])) if x and not foreign(x)]
        if parts:
            keep.append(dict(d, w="; ".join(parts)))
    story["dates"] = keep
    if story.get("tie") and foreign(story["tie"]):
        story["tie"] = None


# The big carriers the writer tends to tag on any story that merely mentions them ("Amazon's plan to replace USPS" tagged
# USPS, UPS and FedEx too). index.html applies the same rule (storyCos) so older stories follow it as well.
BIG_TAGS = ("UPS", "FedEx", "USPS", "Amazon", "OnTrac", "DHL")


def subject_tags(story):
    """A story's carrier tags, limited to the companies it is about. When the headline names a company, a big-carrier tag
    stays only if that carrier (or its parent or one of its arms) is in the headline; a carrier the story only mentions
    goes. Stories whose headline names no company keep their tags (an industry report, "Postmaster General resigns")."""
    tags = list(story.get("c") or [])
    head = _cos(story.get("title", ""))
    if not head:
        return tags
    fam = {i: par for i, par, _ in _names()}
    roots = head | {fam[i] for i in head if fam.get(i)}          # the headline companies and their parents...
    own = roots | {i for i, par in fam.items() if par in roots}  # ...and their arms (Blue Dart -> DHL Group -> DHL Express)
    keep = [c for c in tags if c not in BIG_TAGS or (_cos(c) & own)]
    return keep or ["Industry"]


# ---------------------------------------------------------------- storylines: one subject, one storyline
def _co(x):
    return re.sub(r"[^a-z0-9]+", "", str(x or "").lower())


def resolve_thread(threads, key):
    """A storyline key the model reuses after that storyline was merged into another one points to the merged storyline."""
    if not key or key in threads:
        return key
    return next((k for k, t in threads.items() if key in (t.get("was") or [])), key)


def thread_company(t, key=""):
    """The main company a storyline follows: its "co" field, else the one company named in its name (as written there)."""
    if t.get("co"):
        return t["co"]
    found = {m.group(0) for _, _, rx in _names() for m in [rx.search(t.get("n") or "")] if m}
    # "UniUni" can match two map entries for the same company; one company means one distinct name in the text
    found = {x for x in found if not any(x != y and x in y for y in found)}
    return found.pop() if len(found) == 1 else None


def saga_candidates(threads, company, skip=(), days=365):
    """Existing storylines about the same main company that are still recent enough to continue, newest first."""
    co = _co(company)
    if len(co) < 2:
        return []
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    word = re.compile(r"(?<![a-z0-9])" + re.escape(str(company).lower()) + r"(?![a-z0-9])")
    out = [k for k, t in threads.items() if k not in skip and (t.get("last") or "") >= since and
           (_co(thread_company(t, k)) == co or word.search((t.get("n") or "").lower() + " " + k.replace("-", " ")))]
    return sorted(out, key=lambda k: threads[k].get("last") or "", reverse=True)[:6]


SAGA = """You keep a parcel news app's storylines tidy. A storyline follows one subject over weeks or months. You get a NEW
item (or a storyline) and EXISTING storylines about the same company, with their latest headlines. Say whether the new one
is the same ongoing saga as one of them. For a smaller or regional company (a regional carrier, a courier, a startup), its
funding, its go-public or sale deal and that deal's fallout, and the service trouble or lawsuits that come with its growth
are ONE saga. For a big carrier (UPS, FedEx, USPS, Amazon, DHL), the same saga means the same program or issue (one labor
contract, one network overhaul, one deal), not just the same company.
Reply with JSON only: {"same": "<existing key>" or null}"""


def same_saga(threads, candidates, title, summary, archive):
    """Ask the fast model whether a new item (or storyline) continues one of the candidate storylines. Returns its key or None."""
    if not candidates:
        return None
    text = f"NEW: {title}\n{(summary or '')[:300]}\n\nEXISTING STORYLINES:\n" + "\n".join(
        f"{k}: {threads[k].get('n')}\n" + "\n".join(f"  - {archive[i].get('date')}: {archive[i].get('title')}"
                                                    for i in threads[k].get("ids", [])[-4:] if i in archive) for k in candidates)
    try:
        got = parse_json(claude(MODEL_FAST, SAGA, text, max_tokens=200)) or {}
    except Exception as e:
        print(f"  storyline check failed: {e}", file=sys.stderr)
        return None
    k = got.get("same") if isinstance(got, dict) else None
    return k if k in candidates else None


def merge_threads(threads, src, dst, dates, live=(), name=None, status=None, co=None, add=()):
    """Fold storyline src into dst (dst is created when it doesn't exist yet). Story ids are combined in date order; Coop's
    step lines for every story stay; the intro and "where it stands" come from whichever side has the newest story; the
    narration and the editor review run again because the story set changed. Old keys are remembered in "was", so the
    pipeline files later items sent to an old key into the merged storyline."""
    a = threads.pop(src, None) if src != dst else None
    b = threads.setdefault(dst, {"n": (a or {}).get("n") or dst, "ids": []})
    if a is None and not add and not (name or status or co):
        return b
    a = a or {}
    ids = sorted({*b.get("ids", []), *a.get("ids", []), *add}, key=lambda i: (dates.get(i) or "", i))
    newer = a if (a.get("last") or "") > (b.get("last") or "") else b
    known = [dates[i] for i in ids if dates.get(i)]
    beats = {**((a.get("cx") or {}).get("beats") or {}), **((b.get("cx") or {}).get("beats") or {})}
    cx = {"sig": None, "v": BEATS_V, "beats": {i: v for i, v in beats.items() if i in ids}}
    for k in ("intro", "now"):
        # "now" describes the newest story, so it only comes from the side that has it; the intro can come from either
        v = (newer.get("cx") or {}).get(k) or (k == "intro" and ((b.get("cx") or {}).get(k) or (a.get("cx") or {}).get(k)))
        if v:
            cx[k] = v
    b.update({"ids": ids, "first": min(known) if known else b.get("first") or a.get("first"),
              "last": max(known) if known else max(b.get("last") or "", a.get("last") or ""),
              "c": sorted(set(b.get("c") or []) | set(a.get("c") or [])), "cx": cx})
    if newer.get("s"):
        b["s"] = newer["s"]
    if name:
        b["n"] = name[:60]
    if status:
        b["s"] = status
    if co or a.get("co"):
        b["co"] = co or b.get("co") or a.get("co")
    was = set(b.get("was") or []) | set(a.get("was") or []) | ({src} if src != dst else set())
    if was:
        b["was"] = sorted(was)
    b.pop("rv", None)
    for x in live:
        if x.get("thread") == src:
            x["thread"] = dst
    return b


def merge_sagas(limit=4):
    """Editor pass: storylines that follow the same company are checked in pairs; when the model says they are one saga,
    they become one storyline. Pairs found to be different are remembered ("apart"), so each pair is asked about once."""
    threads = load("threads.json", {})
    if len(threads) < 2:
        return
    seed, live = load("seed.json", {}), load("news.json", [])
    archive = {s["id"]: s for s in seed.get("news", []) + live if s.get("id")}
    dates = {i: s.get("date") for i, s in archive.items()}
    asked, changed = 0, False
    for k in sorted(threads, key=lambda k: threads[k].get("last") or "", reverse=True):
        if asked >= limit or k not in threads:
            continue
        t = threads[k]
        co = thread_company(t, k)
        cands = [c for c in saga_candidates(threads, co, skip={k}) if c not in (t.get("apart") or [])
                 and k not in (threads[c].get("apart") or [])] if co else []
        if not cands:
            continue
        last = archive.get((t.get("ids") or [""])[-1]) or {}
        asked += 1
        hit = same_saga(threads, cands, f"{t.get('n')} (latest: {last.get('title') or ''})", t.get("s") or "", archive)
        if hit:
            # the storyline with more stories keeps its key; the newer one's "where it stands" wins
            src, dst = (k, hit) if len(threads[hit].get("ids", [])) >= len(t.get("ids", [])) else (hit, k)
            merge_threads(threads, src, dst, dates, live, co=co)
            print(f"  storylines merged (same {co} saga): {src} -> {dst}")
        else:
            t["apart"] = sorted(set(t.get("apart") or []) | set(cands))
        changed = True
    if changed:
        save("threads.json", threads)
        save("news.json", live)

def gnews(q):
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:7d") + "&hl=en-US&gl=US&ceid=US:en"


# SEC asks automated readers to name themselves with a contact address
SEC_UA = {"User-Agent": "ParcelPigeon parcel-news reader " + (__import__("os").environ.get("SEC_CONTACT") or "bot@users.noreply.github.com")}


# what an 8-K's item numbers mean, so a filing's headline says what it is about
SEC_ITEMS = {"1.01": "a material agreement", "1.02": "an ended agreement", "2.01": "an acquisition or sale", "2.02": "results of operations",
             "2.03": "new debt", "2.05": "restructuring costs", "2.06": "an impairment", "3.01": "a listing change", "5.01": "a change in control",
             "5.02": "executive or board changes", "5.07": "shareholder vote results", "7.01": "a disclosure to investors", "8.01": "other events"}


def edgar_items(url, company, cutoff):
    """An SEC company's recent 8-K filings from data.sec.gov (the SEC's structured filings data), as intake items."""
    j = requests.get(url, headers=SEC_UA, timeout=25)
    j.raise_for_status()
    rec = (j.json().get("filings") or {}).get("recent") or {}
    cik = str(int(re.search(r"CIK(\d+)", url).group(1)))
    out = []
    for form, day, acc, items in zip(rec.get("form", []), rec.get("filingDate", []), rec.get("accessionNumber", []), rec.get("items", [])):
        if form not in ("8-K", "8-K/A") or dt.datetime.fromisoformat(day) < cutoff:
            continue
        what = [SEC_ITEMS[i] for i in (items or "").split(",") if i in SEC_ITEMS] or ["a current report"]
        out.append({"title": f"{company} files SEC Form {form}: {'; '.join(what)}", "date": day, "summary": f"Items {items}" if items else "",
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm",
                    "src": f"{company} SEC filing", "direct": True, "house": False, "tier": 0})
    return out


def primary_feeds(cfg):
    """The company and regulator sources read before anyone writes about them: SEC filings, the Federal Register,
    press-release wires and carrier newsrooms (sources.yaml "primary:"). Items from these count as tier 0."""
    out = []
    for f in cfg.get("primary", []):
        kind = f.get("kind", "rss")
        url = gnews(f["q"]) if kind == "gnews" else f["url"]
        out.append((f["name"], url, kind != "gnews", False, kind, f.get("company")))
    return out


def collect(cfg, primary_only=False):
    items, cutoff = [], dt.datetime.utcnow() - dt.timedelta(days=MAX_AGE_DAYS)
    feeds = primary_feeds(cfg)
    if not primary_only:
        feeds += [(f["name"], f["url"], True, f.get("house", False), "rss", None) for f in cfg.get("direct", [])] + \
                 [(q, gnews(q), False, False, "gnews", None) for q in cfg.get("discovery", [])]
    health, today = load("feed_health.json", {}), dt.date.today().isoformat()
    for name, url, direct, house, kind, company in feeds:
        fh = health.setdefault(name, {"direct": direct})
        if kind == "edgar":
            try:
                got = edgar_items(url, company, cutoff)
            except Exception as e:
                fh.update({"err": str(e)[:120], "fails": fh.get("fails", 0) + 1, "last_try": today})
                print(f"  feed failed: {name}: {e}", file=sys.stderr)
                continue
            fh.update({"err": None, "fails": 0, "last_try": today, "entries": len(got), "last_ok": today})
            items += got
            continue
        try:
            parsed = feedparser.parse(get(url).content)
        except Exception as e:
            fh.update({"err": str(e)[:120], "fails": fh.get("fails", 0) + 1, "last_try": today})
            print(f"  feed failed: {name}: {e}", file=sys.stderr)
            continue
        fh.update({"err": None, "fails": 0, "last_try": today, "entries": len(parsed.entries)})
        if parsed.entries:
            fh["last_ok"] = today
        for e in parsed.entries[:PER_FEED]:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = dt.datetime(*ts[:6]) if ts else dt.datetime.utcnow()
            if when < cutoff:
                continue
            src = (e.get("source") or {}).get("title") if not direct else name
            dom = (e.get("source") or {}).get("href") if not direct else url
            title = e.get("title", "").strip()
            if not direct and src and title.endswith(" - " + src):
                title = title[: -len(" - " + src)]          # Google News appends the outlet to every headline
            if not direct and not_a_source(src, None, dom):
                continue          # press-release spam and automated write-ups never become sources
            summary = re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", e.get("summary", ""))).strip()
            items.append({"title": title, "url": e.get("link", ""), "summary": summary[:600],
                          "date": when.strftime("%Y-%m-%d"), "src": src or name, "direct": direct, "house": house,
                          "tier": 0 if kind == "fedreg" else 2 if direct and not house else tier(src, None, dom)})
    save("feed_health.json", health)
    return items


BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
_GN = {}
_GN_CTX = [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0]


def gnews_decode(url):
    """Google News links no longer redirect to the article: ask Google for the real address (the same two calls the
    Google News page makes). Uses the googlenewsdecoder package when installed, with this as the fallback."""
    m = re.search(r"news\.google\.com/(?:rss/)?(?:articles|read)/([^?/#]+)", url or "")
    if not m:
        return None
    aid = m.group(1)
    if aid in _GN:
        return _GN[aid]
    real = None
    try:
        from googlenewsdecoder import gnewsdecoder
        r = gnewsdecoder(url, timeout=15)
        if r.get("success"):
            real = r["decoded_url"]
    except Exception:
        pass
    if not real:
        try:
            import requests, time
            page = requests.get(f"https://news.google.com/rss/articles/{aid}?hl=en-US&gl=US&ceid=US:en", headers=BROWSER, timeout=15).text
            sg, ts = re.search(r'data-n-a-sg="([^"]+)"', page), re.search(r'data-n-a-ts="([^"]+)"', page)
            if sg and ts:
                inner = ["garturlreq", _GN_CTX, aid, int(ts.group(1)) if ts.group(1).isdigit() else ts.group(1), sg.group(1)]
                body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", json.dumps(inner, separators=(",", ":")), None, "generic"]]], separators=(",", ":")))
                r = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body, timeout=15,
                                  headers={**BROWSER, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
                hit = re.search(r'\\"garturlres\\",\\"(https?://[^"\\]+)', r.text)
                if hit:
                    real = hit.group(1)
            time.sleep(0.3)
        except Exception:
            pass
    _GN[aid] = real
    return real


def edgar_doc(index_url):
    """An SEC filing's index page lists its documents; the press release is exhibit 99 (else the main form)."""
    import requests
    page = requests.get(index_url, headers=SEC_UA, timeout=25).text
    docs = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', page, re.I)
    pick = next((d for d in docs if re.search(r"ex-?99", d, re.I)), docs[0] if docs else None)
    if not pick:
        return None, index_url
    u = "https://www.sec.gov" + pick
    return trafilatura.extract(requests.get(u, headers=SEC_UA, timeout=25).text, include_tables=True) or None, u


CLAUDE_READS = int(os.environ.get("PP_CLAUDE_READS") or 6)     # pages per run read through Claude's web fetch tool
READS = {"n": 0}


def claude_read(url):
    """Read a page through Claude's web fetch tool, which fetches from Anthropic's servers: it gets past many of the bot
    walls that turn away GitHub's runners (not paywalls). The page text comes straight from the tool result, never from
    the model's own words, so nothing in it can be paraphrased or invented."""
    from common import API_KEY, API_DOWN, track, api_check, THINK_ROOM
    if not API_KEY or API_DOWN or READS["n"] >= CLAUDE_READS:
        return None
    READS["n"] += 1
    # only fetches the page (the text comes from the tool, not the model), so it runs at low effort
    body = {"model": MODEL_WRITE, "max_tokens": 300 + THINK_ROOM, "output_config": {"effort": "low"},
            "tools": [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 1, "max_content_tokens": 20000}],
            "messages": [{"role": "user", "content": f"Fetch this page with web_fetch, then reply OK.\n{url}"}]}
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=180,
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        api_check(r)
        j = r.json(); track(j)
    except Exception as e:
        print(f"  web fetch failed for {url}: {e}", file=sys.stderr)
        return None
    for b in j.get("content", []):
        res = b.get("content") if b.get("type") == "web_fetch_tool_result" else None
        doc = (res or {}).get("content") if (res or {}).get("type") == "web_fetch_result" else None
        src = (doc or {}).get("source") or {}
        if src.get("type") == "text" and src.get("data"):
            text = src["data"]
            if "<" in text[:2000] and "</" in text:
                text = trafilatura.extract(text, include_comments=False) or text
            from fetch import is_blocked
            return None if is_blocked(text) else text
    return None


def article_text(url):
    try:
        if "sec.gov/Archives/edgar" in (url or "") and url.rstrip("/").endswith(("-index.htm", "-index.html")):
            return edgar_doc(url)
        if "news.google.com" in (url or ""):
            real = gnews_decode(url)
            if not real:
                return None, url
            url = real
        r = requests.get(url, headers=BROWSER, timeout=25, allow_redirects=True)
        if "news.google.com" in r.url:
            return None, r.url
        text = trafilatura.extract(r.text, include_comments=False) if r.status_code < 400 else None
        from fetch import is_blocked
        if not text or len(text) < 400 or is_blocked(text):
            text = claude_read(r.url) or text     # turned away or empty: try once more from Anthropic's servers
        return (text or None), r.url
    except Exception:
        return (claude_read(url) if url and "news.google.com" not in url else None), url


def lead_image(url):
    """og:image from a company, government or union page (press photos made for media use). None for logos/placeholders."""
    try:
        html = get(url).text
    except Exception:
        return None
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', html, re.I) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)', html, re.I)
    if not m:
        return None
    u = urllib.parse.urljoin(url, m.group(1).strip())
    if re.search(r"logo|placeholder|favicon|default|sprite|icon", u, re.I):
        return None
    return u


def similar(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.72


DATE_SYSTEM = """You get a parcel price-change story and the text of the carrier's own announcement. If the announcement states
the date the change takes effect, return JSON {"d":"YYYY-MM-DD","w":"what changes, under 70 characters","imp":"up"}.
If it does not, return {"d":null}. Use only the announcement text."""


def find_primary(query, carriers):
    """Find the company's own announcement (its site or its press-release wire) for an event reported by the press."""
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query + " when:14d") + "&hl=en-US&gl=US&ceid=US:en"
    try:
        entries = feedparser.parse(get(url).content).entries[:10]
    except Exception:
        return None
    for e in entries:
        text, final = article_text(e.get("link", ""))
        if final and is_primary(final) and text:
            return {"src": (e.get("source") or {}).get("title") or "Company announcement", "url": final}
    return None


def overlap(a, b):
    """Share of the shorter headline's key words found in the other (0..1)."""
    A, B = _words(a), _words(b)
    return len(A & B) / max(1, min(len(A), len(B))) if len(A & B) >= 3 else 0.0


def find_coverage(title, days=14):
    """Who else reported this event: the major and trade outlets' versions of a headline we only have from a small
    site, or from a paywalled one we can't read. Returns items in the same shape collect() makes, best outlets first."""
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(" ".join(keywords(title, 7)) + f" when:{days}d") + "&hl=en-US&gl=US&ceid=US:en"
    try:
        entries = feedparser.parse(get(url).content).entries[:30]
    except Exception:
        return []
    out = []
    for e in entries:
        src = (e.get("source") or {}).get("title") or ""
        t = (e.get("title") or "").strip()
        if src and t.endswith(" - " + src):
            t = t[: -len(" - " + src)]
        if overlap(t, title) < 0.4:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        out.append({"title": t, "url": e.get("link", ""), "summary": "", "date": dt.datetime(*ts[:6]).strftime("%Y-%m-%d") if ts else None,
                    "src": src or "News", "direct": False, "house": False, "tier": tier(src, None, (e.get("source") or {}).get("href"))})
    out = [x for x in out if x["date"] and x["tier"] <= 2][:12]
    if not out:
        return []
    # similar words are not the same event ("FedEx closes Memphis hub" vs "FedEx closes Calverton hub"): the fast model decides
    try:
        keep = parse_json(claude(MODEL_FAST, "You match news headlines. Reply with a JSON list of the numbers of the CANDIDATES that report the "
                                 "very same event as the HEADLINE (same company, same action, same place or figures). Different events "
                                 "that merely sound alike do not match. [] if none.",
                                 f"HEADLINE: {title}\n\nCANDIDATES:\n" + "\n".join(f"{i}. [{x['src']}] {x['title']}" for i, x in enumerate(out)), max_tokens=100))
        out = [out[i] for i in keep if isinstance(i, int) and 0 <= i < len(out)]
    except Exception:
        return []
    return sorted(out, key=lambda x: (x["tier"], x["date"]))


def find_effective_date(story):
    """Look for the carrier's own announcement of this price change and read the effective date from it."""
    q = " ".join(story["c"]) + " " + story["title"] + " effective"
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:30d") + "&hl=en-US&gl=US&ceid=US:en"
    try:
        entries = feedparser.parse(get(url).content).entries[:8]
    except Exception:
        return None
    carriers = [c.lower() for c in story["c"]]
    for e in entries:
        src = ((e.get("source") or {}).get("title") or "").lower()
        if not any(c in src for c in carriers) and "newswire" not in src and "business wire" not in src:
            continue  # only the carrier itself or its press-release wire
        text, final = article_text(e.get("link", ""))
        if not text:
            continue
        try:
            r = parse_json(claude(MODEL_FAST, DATE_SYSTEM, f"STORY: {story['title']}\n\nANNOUNCEMENT:\n{text[:6000]}", max_tokens=200))
        except Exception:
            continue
        if r.get("d") and r["d"] in text or (r.get("d") and r["d"][:4] in text):
            r.update({"src": (e.get("source") or {}).get("title") or "Carrier announcement", "url": final})
            return r
    return None


# Other parcel consultancies and audit firms: their articles can back up a story as an extra source,
# but they never become a story of their own and never appear in the TransImpact feed.
COMPETITOR_DOMAINS = ["shipware.com", "reveel.com", "transportationinsight.com", "ntgfreight.com", "sifted.com", "lojistic.com",
                      "enveyo.com", "intelligentaudit.com", "afs.net", "spendmanagementexperts.com", "refundretriever.com",
                      "ljmgroup.com", "parcelpath.com", "auditshipment.com"]


def is_competitor(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return any(host == d or host.endswith("." + d) for d in COMPETITOR_DOMAINS)


HIGH_STAKES = {"Pricing & GRI", "Peak season", "Fees & rules", "Fuel", "M&A", "Earnings & markets", "Legal", "Guide changes",
               "Deals & partnerships", "Regulation & trade"}


def unconfirmed(story):
    """Marked "Unconfirmed" in the app: a price, deal, earnings, legal or rules story that rests on a single source, and that
    source is neither the company, a regulator, the major press nor the trade press. Cleared as soon as a better source
    is listed. Everything else shows no mark, so the page stays clean."""
    srcs = [x for x in story.get("srcs") or [] if x.get("url")]
    if len({x.get("src") for x in srcs}) != 1 or story.get("kind") == "Alert":
        return False
    high = story.get("cat") in HIGH_STAKES or int(story.get("lvl") or 1) >= 2
    return high and tier(srcs[0].get("src"), srcs[0].get("url")) >= 3


def add_source(story, item, url):
    srcs = story.setdefault("srcs", [{"src": story.get("src"), "url": story.get("url")}])
    if not any(x["url"] == url for x in srcs):
        srcs.append({"src": item["src"], "url": url, **({"house": True} if item.get("house") else {})})
        story["srcs"] = primary_first(srcs)
        story["src"], story["url"] = story["srcs"][0]["src"], story["srcs"][0]["url"]
        if story.get("unconf") and not unconfirmed(story):
            story.pop("unconf")      # a second outlet, or the company, the major press or the trade press
        story["updated"] = item["date"]
        return True
    return False


REALM_OF = {"Ocean shipping & logistics": "global", "Contract logistics / 3PL": "3pl", "National parcel carrier": "national",
            "Regional / last-mile carrier": "regional", "Courier / same-day": "regional", "Freight brokerage & parcel reselling": "software",
            "Shipping software": "software", "Supply chain software": "software", "Returns & reverse logistics": "software",
            "Private equity / investor": "capital", "SPAC / public markets": "capital", "Cross-border parcel platform": "global",
            "Gig / on-demand delivery": "gig", "Retailer / marketplace": "retail", "Cold chain / healthcare logistics": "cold",
            "Drones, robots & autonomous delivery": "auto", "Postal operator": "national"}


def update_market_map(deal, story):
    """Every new deal adds its companies and the deal itself to the market map (data/players.json).
    Companies already on the map (built-in list in seed.json, or added earlier) are matched by name or alias."""
    seed = load("seed.json", {})
    mp = load("players.json", {"players": [], "edges": []})
    known = seed.get("players", []) + mp["players"]

    def find(name):
        n = (name or "").lower().strip()
        for p in known:
            if n and (n == p["n"].lower() or n in [a.lower() for a in p.get("al", [])]):
                return p["id"]
        return None

    def slug(name):
        base = re.sub(r"[^a-z0-9]+", "", name.lower())[:14] or "co"
        ids, s, k = {p["id"] for p in known}, base, 2
        while s in ids:
            s, k = f"{base}{k}", k + 1
        return s

    who = {w[1]: w for w in deal.get("who", []) if len(w) > 2}
    ids = {}   # role -> [ids]; a deal can have two buyers or several targets
    for party in deal.get("parties", []) or [{"name": deal.get("buyer"), "role": "Buyer"}, {"name": deal.get("target"), "role": "Target"}]:
        name = party.get("name")
        if not name:
            continue
        pid = find(name)
        if not pid:
            pid = slug(name)
            p = {"id": pid, "n": name, "realm": REALM_OF.get(party.get("realm"), "3pl"), "own": None, "tk": None, "parent": None,
                 "hq": party.get("hq"), "yr": party.get("founded"), "s": (who.get(name) or [None, None, ""])[2] or f"{party.get('realm') or 'Company'} named in {story['title']}.",
                 "al": [], "src": story["url"], "auto": True, "added": story["date"], "story": story["id"]}
            mp["players"].append(p)
            known.append(p)
        ids.setdefault(party.get("role", ""), []).append(pid)
    buyers = ids.get("Buyer") or ids.get("Acquirer") or [x for x in [find(deal.get("buyer"))] if x]
    targets = ids.get("Target") or ids.get("Merged with") or [x for x in [find(deal.get("target"))] if x]
    k = "merged" if ids.get("Merged with") and not ids.get("Target") else "acquired"
    for a in buyers:
        for b in targets:
            if a == b:
                continue
            edge = {"a": a, "b": b, "k": k, "y": (deal.get("closed") or deal.get("ann") or story["date"])[:4], "t": deal.get("title") or story["title"],
                    "url": story["url"], "story": story["id"]}
            if not any(e["a"] == a and e["b"] == b and e["k"] == k for e in seed.get("edges", []) + mp["edges"]):
                mp["edges"].append(edge)
    for a in ids.get("Seller", []):          # the seller gives up the target
        for b in targets:
            if a != b and not any(e["a"] == a and e["b"] == b and e["k"] == "sold" for e in seed.get("edges", []) + mp["edges"]):
                mp["edges"].append({"a": a, "b": b, "k": "sold", "y": (deal.get("closed") or deal.get("ann") or story["date"])[:4],
                                    "t": f"{deal.get('title') or story['title']} (seller)", "url": story["url"], "story": story["id"]})
    # a closed deal moves the target into the buyer's family tree (the app applies "moves" on top of the researched trees)
    if str(deal.get("status") or "").lower() == "closed" and len(buyers) == 1:
        byid = {p["id"]: p for p in known}
        moves = mp.setdefault("moves", [])
        for b in targets:
            if b == buyers[0] or any(m["id"] == b and m.get("parent") == buyers[0] for m in moves):
                continue
            moves.append({"id": b, "k": "bought", "parent": buyers[0], "from": (byid.get(b) or {}).get("parent") or (ids.get("Seller") or [None])[0],
                          "d": (deal.get("closed") or story["date"])[:10], "url": story["url"], "t": deal.get("title") or story["title"], "story": story["id"]})
    for b in ids.get("Backer", []):          # private equity or other backers of the buyer
        for a in buyers:
            if a != b and not any(e["a"] == b and e["b"] == a for e in seed.get("edges", []) + mp["edges"]):
                mp["edges"].append({"a": b, "b": a, "k": "invested", "y": None, "t": f"Backs {deal.get('buyer')}", "url": story["url"], "story": story["id"]})
    save("players.json", mp)


NOT_MOVER = re.compile(r"\b(cpas?|llp|accounting|accountants|law (firm|group)|attorneys|legal|consult(ing|ants?)|advisors?|advisory|"
                       r"staffing|recruit\w*|insurance agency|tax)\b", re.I)


def add_candidates(orgs, story):
    """Companies a story is about that aren't on the market map yet. They wait as candidates until players.py
    researches them, confirms they're parcel players and links them to the map."""
    seed = load("seed.json", {})
    mp = load("players.json", {"players": [], "edges": []})
    known = seed.get("players", []) + mp["players"]
    names = {n.lower() for p in known for n in [p["n"]] + (p.get("al") or [])}
    ids = {p["id"] for p in known}
    changed = False
    if story.get("edge"):
        return          # loosely related stories don't add companies to a parcel market map
    for o in orgs[:4]:
        name = (o.get("name") or "").strip()
        realm = REALM_OF.get(o.get("realm"))
        if not name or not realm or name.lower() in names or NOT_MOVER.search(name):
            continue
        if realm == "capital" and story.get("cat") != "M&A":
            continue    # investors join the map through deals they lead, not every story that names them
        base = re.sub(r"[^a-z0-9]+", "", name.lower())[:14] or "co"
        pid, k = base, 2
        while pid in ids:
            pid, k = f"{base}{k}", k + 1
        mp["players"].append({"id": pid, "n": name, "realm": realm, "own": None, "tk": None, "parent": None, "hq": None, "yr": None,
                              "s": (o.get("what") or "")[:200], "al": [], "src": story["url"], "auto": True, "pending": True,
                              "added": story["date"], "story": story["id"]})
        names.add(name.lower()); ids.add(pid); changed = True
    if changed:
        save("players.json", mp)


def add_relations(rels, story):
    """Partnerships, investments and ownership named in any story go on the market map (data/players.json).
    Only links between companies already on the map are added automatically; unknown companies wait for a deal story or a person."""
    if not rels:
        return
    seed = load("seed.json", {})
    mp = load("players.json", {"players": [], "edges": []})
    known = seed.get("players", []) + mp["players"]

    def find(name):
        n = (name or "").lower().strip()
        for p in known:
            if n and (n == p["n"].lower() or n in [x.lower() for x in p.get("al", [])]):
                return p["id"]
        return None
    allE = seed.get("edges", []) + mp["edges"]
    for r in rels:
        a, b, k = find(r.get("a")), find(r.get("b")), r.get("k")
        if not (a and b and a != b and k in ("partner", "acquired", "merged", "sold", "spun", "invested", "owns")):
            continue
        y = story["date"][:4]
        if any(e["a"] in (a, b) and e["b"] in (a, b) and e["k"] == k and str(e.get("y")) == y for e in allE):
            continue
        e = {"a": a, "b": b, "k": k, "y": y, "t": (r.get("t") or story["title"])[:120], "url": story["url"], "story": story["id"]}
        mp["edges"].append(e); allE.append(e)
    save("players.json", mp)


def publish_extras(story, s, live=()):
    """Library docs, deal card and market-map entries for a story. Runs only once the story is live,
    so a held or first-to-report story doesn't leak through the deal tracker or the map."""
    if s.get("docs"):
        lib = load("docs.json", [])
        src_urls = {x["url"] for x in story["srcs"]}
        for dd in s["docs"]:
            report = story["cat"] == "Market reports"
            if dd.get("u") in src_urls and (is_primary(dd["u"]) or report) and not any(x.get("u") == dd["u"] for x in lib):
                lib.append({"c": "Reports" if report else (dd.get("c") or story["c"][0]), "t": "Market report" if report else (dd.get("t") or "Rate guide"), "n": dd.get("n") or story["title"],
                            "y": dd.get("y"), "eff": dd.get("eff"), "u": dd["u"], "d": f"Found with: {story['title']}",
                            "cur": True, "added": story["date"],
                            "why": {"how": "story", "story": story["id"], "title": story["title"], "when": story["date"]}})
        save("docs.json", lib)
    try:
        add_candidates(s.get("orgs") or [], story)
    except Exception as e:
        print(f"  new players: {e}", file=sys.stderr)
    try:
        add_relations(s.get("rels") or [], story)
    except Exception as e:
        print(f"  relations: {e}", file=sys.stderr)
    if s.get("deal") and story["cat"] == "M&A":
        dl = load("deals.json", [])
        d = dict(s["deal"]); d.update({"d": d.get("closed") or story["date"], "story": story["id"], "url": story["url"],
                                       "srcs": story.get("srcs") or [{"src": story["src"], "url": story["url"]}],
                                       "checked": story["date"]})
        # tie in earlier coverage of the same companies
        names = [w for w in re.findall(r"[A-Z][A-Za-z0-9&]+", f'{d.get("buyer","")} {d.get("target","")}') if len(w) > 3 and w not in ("Corp", "Group", "Acquisition", "Capital", "Management")]
        d["ties"] = [{"d": n["date"], "t": n["title"], "story": n["id"]} for n in list(live) + load("seed.json", {}).get("news", [])
                     if n["id"] != story["id"] and any(w in n["title"] for w in names)][:4]
        same = next((x for x in dl if x.get("buyer") == d.get("buyer") and x.get("target") == d.get("target")), None)
        if same: same.update({k: v for k, v in d.items() if v})   # status changes, e.g. Pending -> Closed
        else: dl.insert(0, d)
        save("deals.json", dl)
        try:
            update_market_map(d, story)
        except Exception as e:
            print(f"  market map: {e}", file=sys.stderr)

BACKFILL = """You organize a parcel news desk's archive into storylines: subjects followed over weeks or months (labor talks,
lawsuits and rulings, regulation, network overhauls, pending deals, rate cycles, a carrier's ongoing strategy).
You get stories as "id | date | title". Group the stories that belong to the same storyline; skip one-off stories.
Only group stories that are clearly about the same ongoing subject. Reply JSON only:
[{"key": "short-lowercase-key", "n": "storyline name under 40 characters", "s": "one sentence: where it stands now, from the titles only", "ids": ["id", ...]}]
Every storyline needs at least 2 stories."""



ANNUAL = [(re.compile(r"peak|holiday surcharge|demand surcharge", re.I), "peak"), (re.compile(r"\bgri\b|rate increase|general rate", re.I), "gri"),
          (re.compile(r"usps.*(price|pricing)", re.I), "usps")]


def season_of(kind, d):
    """The rate year or peak season a storyline date belongs to. Same calendar as the app (stories.js thrCycle): peak runs into January; next year's rates start late summer."""
    try:
        y, m = int(str(d)[:4]), int(str(d)[5:7])
    except ValueError:
        return None
    return (y - 1 if m <= 1 else y) if kind == "peak" else (y + 1 if m >= 8 else y) if kind == "gri" else (y + 1 if m >= 10 else y) if kind == "usps" else y


def cycle_count(t, key, story, live):
    """Earlier stories in the same storyline, counting only this year's cycle for yearly storylines, so a new peak
    season starts again at 'First report' instead of 'Update 9'."""
    ids = t.get("ids", [])
    kind = next((k for rx, k in ANNUAL if rx.search(f"{key} {t.get('n') or ''}")), None)
    if not kind:
        return len(ids)
    dates = {s["id"]: s.get("date") for s in load("seed.json", {}).get("news", []) + list(live)}
    cur = season_of(kind, story.get("date"))
    return sum(1 for i in ids if season_of(kind, dates.get(i)) == cur)

def backfill_threads(live):
    """One time: group what's already published (and the app's built-in stories) into storylines."""
    pool = {s["id"]: s for s in load("seed.json", {}).get("news", []) + live if s.get("id")}
    rows = sorted(pool.values(), key=lambda s: s.get("date") or "")[-220:]
    if len(rows) < 4:
        return {}
    try:
        res = parse_json(claude(MODEL_WRITE, BACKFILL, "\n".join(f"{s['id']} | {s.get('date')} | {s.get('title')}" for s in rows), max_tokens=6000)) or []
    except Exception as e:
        print("storyline backfill failed:", e, file=sys.stderr); return {}
    threads = {}
    for t in res if isinstance(res, list) else []:
        key = re.sub(r"[^a-z0-9-]+", "-", str(t.get("key") or "").lower()).strip("-")[:60]
        ids = sorted([i for i in t.get("ids") or [] if i in pool], key=lambda i: pool[i].get("date") or "")
        if not key or len(ids) < 2:
            continue
        threads[key] = {"n": str(t.get("n") or key)[:60], "s": t.get("s"), "ids": ids, "first": pool[ids[0]].get("date"),
                        "last": pool[ids[-1]].get("date"), "c": sorted({c for i in ids for c in pool[i].get("c") or []})}
        for n, i in enumerate(ids):
            if i in {x["id"] for x in live}:
                st = next(x for x in live if x["id"] == i)
                st["thread"] = key
                if n:
                    st["upd"] = n + 1
    save("threads.json", threads)
    print(f"storylines: grouped the archive into {len(threads)} storylines")
    return threads


def main():
    cfg = yaml.safe_load((ROOT / "pipeline" / "sources.yaml").read_text())
    live, review, seen = load("news.json", []), load("review.json", []), set(load("seen.json", []))
    threads = load("threads.json", {})
    if not threads:
        threads = backfill_threads(live)
    primary_only = "--primary" in sys.argv        # the hourly run: company and regulator sources only
    allitems = collect(cfg, primary_only)
    week = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    retry = [] if primary_only else \
        [x for x in review if x.get("type") == "headline-only" and (x.get("date") or "") >= week and not x.get("retried")]
    if retry:
        review = [x for x in review if x not in retry]
        allitems += [{"title": x["title"], "url": x["url"], "summary": "", "date": x["date"], "src": x.get("src") or "News",
                      "direct": False, "house": False, "retry": True} for x in retry]
        print(f"retrying {len(retry)} items that couldn't be read before")
    raw = [i for i in allitems if i["url"] and (i.get("retry") or h(i["url"]) not in seen) and (i.get("house") or PREFILTER.search(i["title"] + " " + i["summary"]))]
    for i in raw:
        # TransImpact posts go through the sweep like any outlet (as a story or a source); competitors only back up a story
        i["support_only"] = is_competitor(i["url"])
    # best outlets first, newest first within a tier: when a busy news day has more headlines than one run screens,
    # the carrier's own posts, the major press and the trade press go first and the rest wait for the next run
    raw.sort(key=lambda i: (i.get("tier", 3), -int((i.get("date") or "0000-00-00").replace("-", ""))))
    # exact-headline repeats (the same wire story on several sites) collapse here, keeping the best outlet's copy; the rest go to triage
    batch = []
    for it in raw:
        if any(similar(it["title"], b["title"]) for b in batch):
            continue
        batch.append(it)
    print(f"{len(raw)} new candidates, {len(batch)} distinct headlines" + (f"; screening the best {MAX_SCREEN}, the rest wait" if len(batch) > MAX_SCREEN else ""))
    batch = batch[:MAX_SCREEN]
    if not batch:
        save("seen.json", list(seen)[-6000:]); return

    recent = [s for s in live if s["date"] >= (dt.date.today() - dt.timedelta(days=14)).isoformat()][:60]
    active = sorted(((k, t) for k, t in threads.items() if (t.get("last") or "") >= (dt.date.today() - dt.timedelta(days=120)).isoformat()),
                    key=lambda kt: kt[1].get("last") or "", reverse=True)[:60]
    head = "RECENT STORIES:\n" + "\n".join(f"{s['id']}: {s['title']}" for s in recent) + \
           "\n\nACTIVE STORYLINES:\n" + ("\n".join(f"{k}: {t.get('n')}" + (f" [{thread_company(t, k)}]" if thread_company(t, k) else "") + f" (last {t.get('last')})"
                      for k, t in active) or "(none yet)")
    # screen in chunks of 20 so a long first run can't overflow one reply; item numbers stay global
    verdicts, screened = [], set()
    for c0 in range(0, len(batch), 20):
        # events named in earlier batches of this run, so the same event screened in two batches gets one key
        so_far = {}
        for v in verdicts:
            if v.get("keep") and v.get("event") and 0 <= v.get("i", -1) < len(batch):
                so_far.setdefault(v["event"], batch[v["i"]]["title"])
        listing = head + ("\n\nEVENTS ALREADY FOUND THIS RUN (reuse the key when an item reports the same event):\n" +
                          "\n".join(f"{k}: {t}" for k, t in list(so_far.items())[-80:]) if so_far else "") + "\n\nNEW ITEMS:\n" + "\n".join(
            f"{i}. [{b['src']} T{b.get('tier', 3)}, {b.get('date')}]{' (SUPPORTING SOURCE ONLY)' if b.get('support_only') else ''} {b['title']} :: {b['summary'][:250]}"
            for i, b in enumerate(batch) if c0 <= i < c0 + 20)
        try:
            got = parse_json(claude(MODEL_FAST, TRIAGE_SYSTEM, listing, max_tokens=4000))
            verdicts += got
            screened.update(range(c0, min(c0 + 20, len(batch))))
        except Exception as e:
            # not marked seen: these headlines are screened again next run instead of being lost
            print(f"triage chunk {c0}-{c0 + 19} skipped, will retry next run: {e}")
    for i in screened:
        seen.add(h(batch[i]["url"]))
    by_id = {s["id"]: s for s in live}
    archive = {**{x["id"]: x for x in load("seed.json", {}).get("news", []) if x.get("id")}, **by_id}   # storyline history
    groups, merged = {}, 0
    for v in verdicts:
        if not v.get("keep") or not (0 <= v.get("i", -1) < len(batch)):
            continue
        item = batch[v["i"]]
        if v.get("same_as") in by_id:
            if add_source(by_id[v["same_as"]], item, item["url"]):
                merged += 1
            continue
        if item.get("support_only"):
            continue  # house and competitor posts only ever back up an existing story
        groups.setdefault(v.get("event") or f"e{v['i']}", []).append((item, v))
    for members in groups.values():
        members.sort(key=lambda m: (m[0].get("tier", 3), m[0].get("date") or ""))
    print(f"triage: {len(groups)} new events, {merged} sources added to existing stories")
    # strongest stories first, so the per-run cap never spends itself on minor items; minor loose-fit items are skipped.
    # Ties: plainly-parcel items before loosely related ones, then best outlet, then most outlets covering it.
    sc = lambda m: max(int(v.get("score") or 5) for _, v in m)
    order = sorted(((k, m) for k, m in groups.items() if not (sc(m) <= 3 and all(v.get("fit") == "edge" for _, v in m))),
                   key=lambda kv: (-sc(kv[1]), 0 if any(v.get("fit") != "edge" for _, v in kv[1]) else 1,
                                   min(m[0].get("tier", 3) for m in kv[1]), -len(kv[1])))

    written = 0
    for n_ev, (key, members) in enumerate(order):
        if written >= MAX_NEW_PER_RUN:
            # over this run's writing budget: these events are written next run, not dropped
            later = [m[0] for _, ms in order[n_ev:] for m in ms]
            for it in later:
                seen.discard(h(it["url"]))
            print(f"{len(order) - n_ev} events wait for the next run (writing budget {MAX_NEW_PER_RUN} reached)")
            break
        try:
            # a story we only have from a small or late outlet, or from a paywalled one we can't read: find the
            # major and trade outlets' versions, so the story leads with them and carries the date the news broke
            if min(m[0].get("tier", 3) for m in members) >= 2 or members[0][0].get("tier") == 1:
                have = {m[0]["url"] for m in members} | {m[0]["title"] for m in members}
                lead_d = dt.date.fromisoformat(members[0][0]["date"])
                extra = [x for x in find_coverage(members[0][0]["title"]) if x["tier"] <= 2 and x["url"] not in have and x["title"] not in have
                         and abs((dt.date.fromisoformat(x["date"]) - lead_d).days) <= 10][:3]
                for x in extra:
                    seen.add(h(x["url"]))
                members = sorted(members + [(x, members[0][1]) for x in extra], key=lambda m: (m[0].get("tier", 3), m[0].get("date") or ""))
                if extra:
                    print(f"  found {len(extra)} better source(s) for: {members[0][0]['title'][:70]}")
            texts, srcs = [], []
            for item, v in members[:4]:
                text, final_url = article_text(item["url"])
                if text and len(text) >= 400:
                    texts.append((item, final_url, text))
                srcs.append({"src": item["src"], "url": final_url})
            if not texts:
                item = members[0][0]
                review.insert(0, {"type": "headline-only", "title": item["title"], "url": srcs[0]["url"], "src": item["src"], "date": item["date"], "retried": bool(item.get("retry")),
                                  "note": "Couldn't read the article automatically. Write it up by hand or delete this entry."})
                continue
            lead_item, lead_url, _ = texts[0]
            v = members[0][1]
            prompt = "\n\n".join(f"ARTICLE {n+1}\nSource: {it['src']}\nPublished: {it['date']}\nHeadline: {it['title']}\n\n{tx[:9000 // len(texts)]}"
                                   for n, (it, _, tx) in enumerate(texts))
            tkey = (v.get("thread") or "").strip().lower()[:60] or None
            if tkey and not re.match(r"^[a-z0-9][a-z0-9-]{2,59}$", tkey):
                tkey = None
            tkey = resolve_thread(threads, tkey)
            if tkey and tkey not in threads and v.get("company"):
                # a "new" storyline for a company that already has one: ask whether it is the same saga before opening a second
                tkey = same_saga(threads, saga_candidates(threads, v["company"]), lead_item["title"], lead_item.get("summary"), archive) or tkey
            prior = [archive[i] for i in (threads.get(tkey) or {}).get("ids", []) if i in archive][-4:] if tkey else []
            if tkey:
                prompt += ("\n\nSTORYLINE: " + ((threads.get(tkey) or {}).get("n") or tkey) + "\n" +
                    ("EARLIER COVERAGE (oldest first):\n" + "\n".join(f"- {x['date']}: {x['title']}. {x.get('sum','')}" for x in prior) +
                     "\nThis article is the next update in this storyline. " if prior else "This article starts a storyline. ") +
                    'Add three keys to your JSON: "thread_name": a short name for the storyline, under 40 characters '
                    '(e.g. "UPS–Teamsters contract"); "status": one sentence on where the storyline stands now; "new": ' +
                    ('one sentence on what is new compared with the earlier coverage and how that changes things for shippers '
                     '(only facts from the articles).' if prior else 'null.'))
            try:
                s = None
                for attempt in range(2):
                    try:
                        s = parse_json(claude(MODEL_WRITE, WRITE_SYSTEM, prompt if not attempt else prompt +
                            "\n\nYour last reply was not valid JSON. Reply with ONE JSON object only. Escape any double quotes inside text values.", max_tokens=2500))
                        if isinstance(s, dict) and s.get("title"):
                            break
                        s = None
                    except Exception as e:
                        print(f"  write attempt {attempt + 1} failed: {e}", file=sys.stderr)
                if not s:
                    continue
            except Exception as e:
                print(f"  write failed: {e}", file=sys.stderr); continue
            ordered = [{"src": it["src"], "url": u} for it, u, _ in texts] + [x for x in srcs if x["url"] not in {u for _, u, _ in texts}]
            ordered = primary_first(ordered)
            if not any(is_primary(x["url"]) for x in ordered):
                # Look for the company's own announcement so the story can lead with it
                prim = find_primary(" ".join(v.get("carriers") or []) + " " + lead_item["title"], v.get("carriers") or [])
                if prim:
                    ordered.insert(0, prim)
                    ptext, _ = article_text(prim["url"])
                    if ptext:
                        texts.insert(0, ({"src": prim["src"], "title": lead_item["title"], "date": lead_item["date"]}, prim["url"], ptext))
            # the date the news broke: the earliest report of it, read or not (a paywalled scoop still dates the story)
            pub = min([it["date"] for it, _, _ in texts] + [m[0]["date"] for m in members if m[0].get("date")])
            ev = str(s.get("event_date") or "")
            # a late report keeps the date the event happened, so it files in its place instead of topping the feed
            sdate = ev if re.match(r"^\d{4}-\d{2}-\d{2}$", ev) and ev < pub else pub
            story = {"id": "a" + h(lead_url), "date": sdate, "c": s.get("carriers") or v.get("carriers") or ["Industry"],
                     "cat": s.get("category") or v.get("category") or "Network & operations", "kind": s.get("kind") or v.get("kind") or "News",
                     "title": s["title"], "sum": s["sum"], "imp": s.get("imp", "info"), "lvl": int(s.get("lvl", 1)), "plain": s["plain"], "why": (str(s.get("why") or "")[:200] or None), "score": int(max((v2.get("score") or 5) for _, v2 in members)), "tie": s.get("tie"),
                     "act": s.get("act"), "dates": s.get("dates") or [],
                     "added": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "src": ordered[0]["src"], "url": ordered[0]["url"], "srcs": ordered, "auto": True}
            if re.match(r"^\d{4}-\d{2}-\d{2}$", ev):
                story["ann"] = ev          # the announcement date the sources state; never guessed from when we covered it
            if tkey:
                story["thread"] = tkey
                done_before = cycle_count(threads.get(tkey) or {}, tkey, story, live) if prior else 0
                if done_before:
                    story["upd"] = done_before + 1
                    if s.get("new"):
                        story["new"] = s["new"]
            # photos: only the company's own announcement image (never trade press), saved with the site
            for sx in story["srcs"]:
                if is_primary(sx["url"]):
                    img = lead_image(sx["url"])
                    try:
                        from media import story_photo
                        got = story_photo(img, story["id"]) if img else None
                    except Exception:
                        got = None
                    if got:
                        story["img"], story["thumb"], story["imgc"] = got[0], got[1], f"Image: {sx['src']}"
                        break
            # tagged only with the companies it is about, not every carrier it mentions
            story["c"] = subject_tags(story)
            # only the story's own company's dates and context: other carriers' events mentioned in passing are dropped
            own_only(story)
            # only cost changes and big events go on the rate clock
            story["dates"] = [d for d in story["dates"] if isinstance(d, dict) and clock_worthy(story, d)]
            if story.get("act") and not clock_worthy(story, {"w": story["title"], "imp": story.get("imp")}):
                story["act"] = None
            alltext = " ".join(tx + " " + it["title"] for it, _, tx in texts)
            missing = numbers_supported(" ".join([story["title"], story["sum"], story["plain"]]), alltext)
            if missing:
                # one rewrite that drops the figures the articles don't contain, instead of asking the editor
                try:
                    s2 = parse_json(claude(MODEL_WRITE, WRITE_SYSTEM, prompt + "\n\nYour draft used numbers that are not in the articles: "
                                           + ", ".join(missing) + ". Rewrite the full JSON using only numbers that appear in the articles; "
                                           "leave a figure out rather than estimate or convert it.", max_tokens=2500))
                    if isinstance(s2, dict) and s2.get("title") and s2.get("sum") and s2.get("plain"):
                        story.update({"title": s2["title"], "sum": s2["sum"], "plain": s2["plain"]})
                        missing = numbers_supported(" ".join([story["title"], story["sum"], story["plain"]]), alltext)
                except Exception as e:
                    print(f"  rewrite failed: {e}", file=sys.stderr)
            # on-cycle or off-cycle, judged by the date the change takes effect (never the date it was announced)
            if story["cat"] in ("Pricing & GRI", "Peak season", "Fees & rules", "Fuel", "Postal") and story.get("act") and story["imp"] in ("up", "down"):
                cyc = cycle_of((story["c"] or [""])[0], kind_of(story["title"], story["cat"]), story["act"], story.get("ann") or story["date"])
                if cyc == "off":
                    story["offc"] = True
            # Price changes belong on the rate clock; a story without a date can't get there.
            if story["cat"] in ("Pricing & GRI", "Peak season", "Fees & rules") and story["imp"] == "up" and not story["act"] and not story["dates"]:
                found = find_effective_date(story)
                if found:
                    story["act"] = found["d"]; story["dates"] = [found]
                    story["srcs"].append({"src": found["src"], "url": found["url"]})
                else:
                    review.insert(0, {"type": "missing-date", "story_id": story["id"], "title": story["title"],
                                      "note": "Price change with no effective date in the sources, so it is not on the rate clock. Add the date from the carrier's own notice."})
            # Official documents found in the sources go into the library (data/docs.json), the single list agents use
            story["_extras"] = {k: s.get(k) for k in ("docs", "deal", "rels", "orgs") if s.get(k)}
            # Everything publishes on its own. The only hold: a figure the sources still don't support after the rewrite,
            # on a story that changes prices for most shippers (lvl 3). Loosely related items publish, marked "edge".
            reasons = []
            if missing:
                story["unsupported_numbers"] = missing
                if int(story.get("lvl") or 1) >= 3:
                    reasons.append("These numbers aren't in the sources: " + ", ".join(missing))
                else:
                    print(f"  dropped (numbers not in sources: {', '.join(missing)}): {story['title'][:70]}")
                    written += 1
                    continue
            if v.get("fit") == "edge":
                story["edge"] = True
                story["lvl"] = 1
            primary = not any(any(p in x["src"].lower() for p in PRESS) for x in ordered)
            covered = is_covered(story["title"]) if primary else ["trade press source"]
            if primary and not covered:
                story["exclusive"] = True
            if reasons:
                url = ask(story, reasons, ordered)
                review.insert(0, {"type": "needs-ok", "issue": url, "story": story, "note": " ".join(reasons)})
                written += 1
                continue
            story.pop("_extras", None)
            live.insert(0, story); by_id[story["id"]] = story
            publish_extras(story, s, live)
            if tkey:
                t = threads.setdefault(tkey, {"n": s.get("thread_name") or tkey.replace("-", " ").title(), "ids": [], "first": story["date"]})
                if v.get("company") and not t.get("co"):
                    t["co"] = str(v["company"])[:40]
                if s.get("thread_name") and not prior:
                    t["n"] = s["thread_name"][:60]
                if s.get("status"):
                    t["s"] = s["status"]
                t["ids"] = [i for i in t["ids"] if i != story["id"]] + [story["id"]]
                t["last"] = max(t.get("last") or "", story["date"])
                t["c"] = sorted(set(t.get("c") or []) | set(story["c"]))
                save("threads.json", threads)
            written += 1
        except Exception as e:
            print(f"  story skipped: {type(e).__name__}: {e}", file=sys.stderr)

    live = dedupe_live(live)
    if not primary_only:
        # try to confirm a few single-source stories each run: a better outlet's report of the same event is attached
        recent = (dt.date.today() - dt.timedelta(days=10)).isoformat()
        for st in [x for x in live if unconfirmed(x) and x.get("date", "") >= recent and x.get("tried") != dt.date.today().isoformat()][:5]:
            st["tried"] = dt.date.today().isoformat()
            for x in find_coverage(st["title"], days=21)[:2]:
                real = gnews_decode(x["url"]) or x["url"]
                if add_source(st, x, real):
                    print(f"  confirmed by {x['src']}: {st['title'][:70]}")
    for st in live:
        if unconfirmed(st):
            st["unconf"] = True
        else:
            st.pop("unconf", None)
        offc = st.get("cat") in ("Pricing & GRI", "Peak season", "Fees & rules", "Fuel", "Postal") and st.get("imp") in ("up", "down") \
            and cycle_of((st.get("c") or [""])[0], kind_of(st.get("title"), st.get("cat")), st.get("act"), st.get("ann") or st.get("date")) == "off"
        if offc:
            st["offc"] = True
        else:
            st.pop("offc", None)
    save("news.json", live[:KEEP_LIVE]); save("review.json", review[:200]); save("seen.json", list(seen)[-6000:])
    from common import API_DOWN
    if API_DOWN:
        # the account itself is refusing calls (credit, spend limit, key): tell a person once a day, not just the log
        st = load("api_alert.json", {})
        if st.get("day") != dt.date.today().isoformat():
            notify("Parcel Pigeon: Claude API is refusing calls", "No stories can be screened or written until this is fixed. "
                   "Headlines are kept and will be processed once calls work again.\n\nThe API said: " + API_DOWN["why"] +
                   "\n\nCheck the Anthropic Console: credit balance, monthly spend limit, and that the ANTHROPIC_API_KEY secret is current.",
                   labels=("audit",))
            save("api_alert.json", {"day": dt.date.today().isoformat(), "why": API_DOWN["why"]})
    print(f"wrote {written} stories; {len(live)} live; {len(review)} in review")


BEATS = """You are Coop, the guide in a small-parcel news app, narrating one STORYLINE as an animated timeline. Each line
is read in a small speech bubble under a picture of that step (the rate change, the deal, the date), so be brief: one
sentence, sometimes two. Make every line earn its place: give the reader context they wouldn't get
from the headline alone. Connect the dots between steps, and use the CONTEXT section to add a real angle where it genuinely
fits: who owns whom, how big a player is, a related deal, what's next on the rate clock, what else that company is doing.
Plain, neutral, a little conversational; no hype, no advice, no predictions of your own.
Hard rules: use ONLY facts in the MILESTONES and CONTEXT below. Every number, date and name you write must appear there. Never
claim a cause or link that isn't stated or plainly implied; "meanwhile" is fine, "because" needs support. Don't restate the
headline. Never name a parcel consultancy or audit firm (say "an industry analysis").
Reply with JSON only:
{"intro": "one line, under 120 characters: what this storyline is about and why shippers care",
 "beats": {"<milestone id>": "one line, under 130 characters, for that step", ...},
 "now": "one line, under 140 characters: where it stands and what's next, only if the milestones or the rate clock say so"}"""
BEATS_V = 2


def thread_context(S, seed, live):
    """Facts from the rest of the app that can give a storyline context: the companies' profiles and owners, deals they're
    in, dated cost changes ahead on the rate clock, and other recent headlines about them."""
    players = seed.get("players", []) + load("players.json", {}).get("players", [])
    byname = {}
    for p in players:
        for nm in [p.get("n")] + (p.get("al") or []):
            if nm:
                byname[str(nm).lower()] = p
    byid = {p["id"]: p for p in players}
    names = {c for st in S for c in (st.get("c") or []) if c not in ("Industry", "Regional")}
    for st in S:
        for o in st.get("orgs") or []:
            if isinstance(o, dict) and o.get("name"):
                names.add(o["name"])
    out, seen = [], set()
    for nm in sorted(names)[:8]:
        p = byname.get(nm.lower())
        if not p or p["id"] in seen:
            continue
        seen.add(p["id"])
        par = byid.get(p.get("parent") or "")
        out.append(f"COMPANY {p['n']}: {(p.get('role') or p.get('s') or '')[:160]}" + (f" Part of {par['n']}." if par else "") +
                   (f" HQ {p['hq']}." if p.get("hq") else "") + (f" Founded {p['yr']}." if p.get("yr") else ""))
    words = {w.lower() for nm in names for w in re.findall(r"[A-Za-z][A-Za-z&]{2,}", nm)}
    hit = lambda txt: any(re.search(r"\b" + re.escape(w) + r"\b", (txt or "").lower()) for w in words)
    for d in (seed.get("deals", []) + load("deals.json", []))[:200]:
        if hit(f"{d.get('buyer')} {d.get('target')}"):
            out.append(f"DEAL {d.get('ann') or d.get('d')}: {d.get('title')} ({d.get('status')}, {d.get('value') or 'value undisclosed'}). {(d.get('sum') or '')[:200]}")
    today = dt.date.today().isoformat()
    for c in seed.get("clock", []):
        if (c.get("d") or "") >= today and hit(f"{c.get('c')} {c.get('w')}"):
            out.append(f"RATE CLOCK {c['d']}: {c.get('w')} ({c.get('c')})")
    ids = {st["id"] for st in S}
    recent = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    others = [n for n in live + seed.get("news", []) if n.get("id") not in ids and (n.get("date") or "") >= recent and hit(n.get("title"))]
    for n in sorted(others, key=lambda n: n.get("date") or "", reverse=True)[:5]:
        out.append(f"ALSO IN THE NEWS {n.get('date')}: {n.get('title')}")
    return "\n".join(out[:24])


def write_beats(limit=6):
    """Coop's narration for each storyline's timeline, rewritten when the storyline gets a new story. Every line is checked:
    a line with a number that isn't in the milestones or context is dropped (the app falls back to a plain date cue)."""
    threads = load("threads.json", {})
    if not threads:
        return
    seed, live = load("seed.json", {}), load("news.json", [])
    pool = {s["id"]: s for s in seed.get("news", []) + live if s.get("id")}
    done = 0
    for k, t in sorted(threads.items(), key=lambda kv: kv[1].get("last") or "", reverse=True):
        if done >= limit:
            break
        ids = [i for i in t.get("ids", []) if i in pool]
        if len(ids) < 2:
            continue
        sig = h(",".join(ids))
        if (t.get("cx") or {}).get("sig") == sig and (t.get("cx") or {}).get("v") == BEATS_V:
            continue
        S = sorted((pool[i] for i in ids), key=lambda s: s.get("date") or "")
        if len(S) > 8:
            ix = sorted({0, *[round(i * (len(S) - 1) / 7) for i in range(1, 7)], len(S) - 1})
            S = [S[i] for i in ix]
        ctx = thread_context(S, seed, live)
        text = f"STORYLINE: {t.get('n') or k}\nWHERE IT STANDS: {t.get('s') or ''}\n\nMILESTONES:\n" + "\n".join(
            f"id={s['id']} | {s.get('date')} | {s.get('title')} :: {(s.get('sum') or '')[:420]} {(s.get('new') or '')[:200]} {(s.get('tie') or '')[:200]}" for s in S) + \
            f"\n\nCONTEXT (from the rest of the app):\n{ctx or '(none)'}"
        done += 1
        try:
            got = parse_json(claude(MODEL_WRITE, BEATS, text, 1400)) or {}
        except Exception as e:
            print(f"  storyline narration failed for {k}: {e}", file=sys.stderr); continue
        ok = lambda line, n: isinstance(line, str) and 0 < len(line) <= n and not numbers_supported(line, text)
        beats = {i: v.strip() for i, v in (got.get("beats") or {}).items() if i in ids and ok(v, 140)}
        cx = {"sig": sig, "v": BEATS_V, "beats": beats}
        if ok(got.get("intro"), 130):
            cx["intro"] = got["intro"].strip()
        if ok(got.get("now"), 150):
            cx["now"] = got["now"].strip()
        t["cx"] = cx
        print(f"  storyline narration: {k} ({len(beats)} of {len(S)} steps)")
    save("threads.json", threads)


# ---------------------------------------------------------------- editor passes: what stays on the site, what's a storyline
CURATE = """You are the editor of Parcel Pigeon, a U.S. small-parcel news app for shippers and industry people. For each
published story decide:
"keep"  - real small-parcel news or a worthwhile discussion piece;
"drop"  - routine hyper-local items (one post office's hours or temporary closure, local deadline reminders, a petty
          local crime), a non-story (a site adding its own guides, a listicle, a promotion), a late re-report of an older
          event already covered, or not really about parcel.
Keep local stories that are industry news (a service like drone delivery starting in a town, a federal raid, a fraud or theft
ring, a closure under a named national program). A "not yet announced" story stays when the wait matters to shippers (a
carrier announcing its rate increase late). When genuinely unsure, keep.
Reply with JSON only: [{"id": "...", "v": "keep"|"drop", "why": "under 10 words"}]"""

REVIEW = """You review one STORYLINE in a small-parcel news app: a subject followed over weeks or months. Decide:
- "parcel": true if the subject is squarely small parcel (carrier pricing and surcharges, carrier networks and service,
  carrier labor, postal policy and finances, parcel regulation and trade rules, deals that reshape who delivers parcels,
  delivery tech rolling out at scale); false for general finance (a fund selling a tech unit), local events, or loose themes.
- "drop": ids of stories that don't belong in a tight arc: a different subject, a loose tie (same company, different issue;
  but for a storyline that follows one smaller or regional company's saga, its funding, deals, fallout and service trouble
  are all one arc, so keep those),
  a local item (it stays on the site, just not in the storyline), an opinion piece, a repeat that adds nothing new, or a
  side note. Keep each step a real development: announced, changed, ruled, closed, took effect, or a confirmed wait for one
  (e.g. one carrier still hasn't announced its increase). The result should read as one clear story in order.
- "n": a clear storyline name under 45 characters (keep the current one if it's good).
If fewer than two real developments remain, set "parcel": false.
Reply with JSON only: {"parcel": true|false, "drop": ["id", ...], "n": "..."}"""


def curate(limit=40):
    """Editor pass over published stories (each looked at once): hyper-local items, non-stories and stale re-reports are
    taken off (logged in data/drop.json with the reason, which dedupe_live honors)."""
    live = load("news.json", [])
    done = set(load("curated.json", []))
    since = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    pool = live + [x for x in load("seed.json", {}).get("news", []) if (x.get("date") or "") >= since]   # built-in stories too
    todo = [x for x in pool if x.get("id") not in done][:limit]
    if not todo:
        return
    text = "\n".join(f"id={x['id']} | {x.get('date')} | {x.get('src')} | {x.get('title')} :: {(x.get('sum') or '')[:260]}" for x in todo)
    try:
        res = parse_json(claude(MODEL_WRITE, CURATE, text, 2500)) or []
    except Exception as e:
        print("  curate failed:", e, file=sys.stderr); return
    drop = load("drop.json", [])
    have = {d if isinstance(d, str) else d.get("id") for d in drop}
    n = 0
    for r in res if isinstance(res, list) else []:
        if isinstance(r, dict) and r.get("v") == "drop" and r.get("id") in {x["id"] for x in todo} and r["id"] not in have:
            drop.append({"id": r["id"], "why": "Editor pass: " + str(r.get("why") or "")[:80]}); n += 1
    save("drop.json", drop)
    save("curated.json", sorted(done | {x["id"] for x in todo})[-5000:])
    if n:
        save("news.json", dedupe_live(live))
    print(f"curate: looked at {len(todo)} stories, took off {n}")


def review_threads(limit=8):
    """Each storyline is reviewed whenever its stories change: off-topic stories leave it, and storylines that aren't
    really about small parcel are dissolved (their stories stay on the site, just not threaded)."""
    threads = load("threads.json", {})
    if not threads:
        return
    seed, live = load("seed.json", {}), load("news.json", [])
    pool = {s["id"]: s for s in seed.get("news", []) + live if s.get("id")}
    dropped = {d if isinstance(d, str) else d.get("id") for d in load("drop.json", [])}
    done, changed = 0, False
    for k, t in list(threads.items()):
        ids = [i for i in t.get("ids", []) if i not in dropped]
        if ids != t.get("ids"):
            t["ids"] = ids; changed = True
        sig = h(",".join(ids))
        if t.get("rv") == sig or done >= limit:
            continue
        S = [pool[i] for i in ids if i in pool]
        if len(S) < 2:
            t["rv"] = sig; continue
        done += 1
        text = f"STORYLINE: {t.get('n') or k}\n" + "\n".join(f"id={x['id']} | {x.get('date')} | {x.get('title')} :: {(x.get('sum') or '')[:240]}" for x in S)
        try:
            r = parse_json(claude(MODEL_WRITE, REVIEW, text, 800)) or {}
        except Exception as e:
            print(f"  storyline review failed for {k}: {e}", file=sys.stderr); continue
        out = {i for i in (r.get("drop") or []) if i in ids}
        if r.get("parcel") is False:
            out = set(ids)
        for x in live:
            if x.get("id") in out and x.get("thread") == k:
                x.pop("thread", None); x.pop("upd", None)
        if out == set(ids):
            del threads[k]; changed = True
            print(f"  storyline dissolved (not a small-parcel subject): {t.get('n')}"); continue
        t["ids"] = [i for i in ids if i not in out]
        if isinstance(r.get("n"), str) and 3 < len(r["n"]) <= 60:
            t["n"] = r["n"]
        t["rv"] = h(",".join(t["ids"]))
        changed = True
        if out:
            print(f"  storyline {t.get('n')}: took out {len(out)} stories that didn't belong")
    if changed:
        save("threads.json", threads); save("news.json", live)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from scoop import crash_alert
        crash_alert("news.py --primary" if "--primary" in sys.argv else "news.py")
        raise
    for step in (curate, merge_sagas, review_threads):     # editor passes first, so Coop narrates the cleaned-up storylines
        try:
            step()
        except Exception as e:
            print(f"{step.__name__} skipped:", e, file=sys.stderr)
    try:
        write_beats()
    except Exception as e:
        print("storyline narration skipped:", e, file=sys.stderr)
