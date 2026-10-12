"""Collect parcel news, keep what matters to shippers, and write plain-English stories.

Run: python pipeline/news.py
Writes data/news.json (live stories) and data/review.json (things a person should check).
"""
import datetime as dt, difflib, json, re, sys, urllib.parse
import feedparser, trafilatura, yaml
from common import ROOT, load, save, h, get, claude, parse_json, numbers_supported, MODEL_FAST, MODEL_WRITE, is_primary, primary_first, clock_worthy
from scoop import is_covered, notify, PRESS, ask, big

MAX_NEW_PER_RUN = 18          # cost guard: stories written per run (about 2-4 cents each)
MAX_AGE_DAYS = 7
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

You also get RECENT STORIES already published (id: title). If an item covers the same event as a recent story, set
"same_as" to that id. Items marked SUPPORTING SOURCE ONLY (other consultancies and audit firms) should get "same_as" when they cover a recent story and keep=false otherwise. Items in this batch that cover the same event as each other get the same short "event" key
(e.g. "ups-2027-gri"); every other kept item gets its own unique key.

Reply with JSON only: a list of objects
{{"i": index, "keep": true|false, "carriers": [subset of {CARRIERS}, or ["Industry"] if no specific carrier],
"category": one of {CATEGORIES}, "kind": "News"|"Opinion"|"Analysis", "event": short key, "same_as": id or null,
"fit": "core" if it is plainly small parcel news, "edge" if you are keeping it but it is only loosely tied to small parcel
(general freight, trucking or ocean, broad retail or economy, tech not specific to shipping, a local story)}}."""

WRITE_SYSTEM = f"""You write for Parcel Pigeon, a small parcel trade news service in the style of Supply Chain Dive and
FreightWaves: neutral, factual, attributed. Use ONLY facts in the articles provided. Never invent numbers, dates or names;
every number must appear in the source text. Do not quote more than a few words. No advice, no recommendations, no
predictions of your own, no adjectives that judge (no "good news", "pain", "win"). Attribute claims ("UPS said",
"according to the filing"). If the source is an opinion or analysis, say whose view it is.

Return JSON only, with exactly these keys:
"title": wire-style headline under 90 characters, subject first, present tense (e.g. "FedEx sets 5.9% average increase for 2027");
"sum": 1-3 sentences: what happened, who, when, key figures;
"imp": "up" if shippers' prices or fees rise, "down" if they fall, "watch" if the item is a developing matter, "info" otherwise;
"lvl": 1, 2 or 3 for how directly it changes shipper prices or service (3 = a dated price change for most shippers);
"docs": list of official carrier, USPS or regulator documents (or, for Market reports, the report itself) linked in the sources (rate guides, service guides,
  surcharge or fuel tables, notices, tariffs, filings), each {{"c":"carrier","t":"Rate guide|Service guide|GRI notice|Surcharges & fees|Peak|Fuel|Zones & DAS|Special program|Terms|Regulatory filing",
  "n":"the document's own title with year","y":year it applies to or null,"eff":"YYYY-MM-DD or null","u":"exact URL from the sources"}}; [] if none;
"tie": one sentence linking this to earlier related news that the sources themselves mention (with month/year), or null;
"plain": 1-2 sentences of the direct, factual effect on shippers (what changes, for whom, from when). If nothing changes
         for shippers, say so plainly (e.g. "No change to rates or service.");
"act": "YYYY-MM-DD" effective date if one is stated, else null;
"dates": list of {{"d":"YYYY-MM-DD","w":"what changes that day, under 70 characters","imp":"up|down|info","fx":null}} for future dates in the source
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
"carriers": subset of {CARRIERS}, or ["Industry"];
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



def gnews(q):
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:7d") + "&hl=en-US&gl=US&ceid=US:en"


def collect(cfg):
    items, cutoff = [], dt.datetime.utcnow() - dt.timedelta(days=MAX_AGE_DAYS)
    feeds = [(f["name"], f["url"], True, f.get("house", False)) for f in cfg.get("direct", [])] + \
            [(q, gnews(q), False, False) for q in cfg.get("discovery", [])]
    for name, url, direct, house in feeds:
        try:
            parsed = feedparser.parse(get(url).content)
        except Exception as e:
            print(f"  feed failed: {name}: {e}", file=sys.stderr)
            continue
        for e in parsed.entries[:40]:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = dt.datetime(*ts[:6]) if ts else dt.datetime.utcnow()
            if when < cutoff:
                continue
            src = (e.get("source") or {}).get("title") if not direct else name
            items.append({"title": e.get("title", "").strip(), "url": e.get("link", ""), "summary": re.sub("<[^>]+>", " ", e.get("summary", ""))[:600],
                          "date": when.strftime("%Y-%m-%d"), "src": src or name, "direct": direct, "house": house})
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


def article_text(url):
    try:
        if "news.google.com" in (url or ""):
            real = gnews_decode(url)
            if not real:
                return None, url
            url = real
        import requests
        r = requests.get(url, headers=BROWSER, timeout=25, allow_redirects=True)
        if "news.google.com" in r.url or r.status_code >= 400:
            return None, r.url
        return trafilatura.extract(r.text, include_comments=False) or None, r.url
    except Exception:
        return None, url


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


def add_source(story, item, url):
    srcs = story.setdefault("srcs", [{"src": story.get("src"), "url": story.get("url")}])
    if not any(x["url"] == url for x in srcs):
        srcs.append({"src": item["src"], "url": url, **({"house": True} if item.get("house") else {})})
        story["srcs"] = primary_first(srcs)
        story["src"], story["url"] = story["srcs"][0]["src"], story["srcs"][0]["url"]
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
    for b in ids.get("Backer", []):          # private equity or other backers of the buyer
        for a in buyers:
            if a != b and not any(e["a"] == b and e["b"] == a for e in seed.get("edges", []) + mp["edges"]):
                mp["edges"].append({"a": b, "b": a, "k": "invested", "y": None, "t": f"Backs {deal.get('buyer')}", "url": story["url"], "story": story["id"]})
    save("players.json", mp)


def add_candidates(orgs, story):
    """Companies a story is about that aren't on the market map yet. They wait as candidates until players.py
    researches them, confirms they're parcel players and links them to the map."""
    seed = load("seed.json", {})
    mp = load("players.json", {"players": [], "edges": []})
    known = seed.get("players", []) + mp["players"]
    names = {n.lower() for p in known for n in [p["n"]] + (p.get("al") or [])}
    ids = {p["id"] for p in known}
    changed = False
    for o in orgs[:4]:
        name = (o.get("name") or "").strip()
        realm = REALM_OF.get(o.get("realm"))
        if not name or not realm or name.lower() in names:
            continue
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

def main():
    cfg = yaml.safe_load((ROOT / "pipeline" / "sources.yaml").read_text())
    live, review, seen = load("news.json", []), load("review.json", []), set(load("seen.json", []))
    allitems = collect(cfg)
    week = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    retry = [x for x in review if x.get("type") == "headline-only" and (x.get("date") or "") >= week and not x.get("retried")]
    if retry:
        review = [x for x in review if x not in retry]
        allitems += [{"title": x["title"], "url": x["url"], "summary": "", "date": x["date"], "src": x.get("src") or "News",
                      "direct": False, "house": False, "retry": True} for x in retry]
        print(f"retrying {len(retry)} items that couldn't be read before")
    raw = [i for i in allitems if i["url"] and (i.get("retry") or h(i["url"]) not in seen) and (i.get("house") or PREFILTER.search(i["title"] + " " + i["summary"]))]
    for i in raw:
        # TransImpact posts go through the sweep like any outlet (as a story or a source); competitors only back up a story
        i["support_only"] = is_competitor(i["url"])
    # exact-headline repeats (the same wire story on several sites) collapse here; the rest go to triage
    batch = []
    for it in raw:
        if any(similar(it["title"], b["title"]) for b in batch):
            continue
        batch.append(it)
    print(f"{len(raw)} new candidates, {len(batch)} distinct headlines")
    batch = batch[:90]
    if not batch:
        save("seen.json", list(seen)[-6000:]); return

    recent = [s for s in live if s["date"] >= (dt.date.today() - dt.timedelta(days=14)).isoformat()][:60]
    head = "RECENT STORIES:\n" + "\n".join(f"{s['id']}: {s['title']}" for s in recent)
    # screen in chunks of 20 so a long first run can't overflow one reply; item numbers stay global
    verdicts = []
    for c0 in range(0, len(batch), 20):
        listing = head + "\n\nNEW ITEMS:\n" + "\n".join(
            f"{i}. [{b['src']}]{' (SUPPORTING SOURCE ONLY)' if b.get('support_only') else ''} {b['title']} :: {b['summary'][:250]}"
            for i, b in enumerate(batch) if c0 <= i < c0 + 20)
        try:
            verdicts += parse_json(claude(MODEL_FAST, TRIAGE_SYSTEM, listing, max_tokens=4000))
        except Exception as e:
            print(f"triage chunk {c0}-{c0 + 19} skipped: {e}")
    for b in batch:
        seen.add(h(b["url"]))
    by_id = {s["id"]: s for s in live}
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
    print(f"triage: {len(groups)} new events, {merged} sources added to existing stories")

    written = 0
    for key, members in groups.items():
        if written >= MAX_NEW_PER_RUN:
            break
        try:
            texts, srcs = [], []
            for item, v in members[:3]:
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
            story = {"id": "a" + h(lead_url), "date": min(it["date"] for it, _, _ in texts), "c": s.get("carriers") or v.get("carriers") or ["Industry"],
                     "cat": s.get("category") or v.get("category") or "Network & operations", "kind": s.get("kind") or v.get("kind") or "News",
                     "title": s["title"], "sum": s["sum"], "imp": s.get("imp", "info"), "lvl": int(s.get("lvl", 1)), "plain": s["plain"], "tie": s.get("tie"),
                     "act": s.get("act"), "dates": s.get("dates") or [],
                     "src": ordered[0]["src"], "url": ordered[0]["url"], "srcs": ordered, "auto": True}
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
            written += 1
        except Exception as e:
            print(f"  story skipped: {type(e).__name__}: {e}", file=sys.stderr)

    live.sort(key=lambda s: s["date"], reverse=True)
    save("news.json", live[:KEEP_LIVE]); save("review.json", review[:200]); save("seen.json", list(seen)[-6000:])
    print(f"wrote {written} stories; {len(live)} live; {len(review)} in review")


if __name__ == "__main__":
    main()
