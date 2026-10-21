"""Shared helpers for the Parcel Pigeon pipeline."""
import hashlib, json, os, re, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "Mozilla/5.0 (ParcelPigeon news reader; +https://github.com)"}
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_FAST = os.environ.get("PW_MODEL_FAST", "claude-haiku-5-5")
MODEL_WRITE = os.environ.get("PW_MODEL_WRITE", "claude-sonnet-5-5")


def load(name, default):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return default
    return default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False))


def h(s):
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:12]


def get(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


USAGE = {"calls": 0, "in": 0, "cached": 0, "written": 0, "out": 0}


def _usage_report():
    if USAGE["calls"]:
        print(f"claude usage this step: {USAGE['calls']} calls, {USAGE['in'] + USAGE['cached'] + USAGE['written']} input tokens "
              f"({USAGE['cached']} read from cache), {USAGE['out']} output tokens")


import atexit
atexit.register(_usage_report)


def cached_system(system):
    """The instructions go out with a cache marker: the same instructions sent again within a few minutes (every story
    in a run, every storyline in a pass) are read from Anthropic's prompt cache at a tenth of the price. Replies are
    identical; only the bill changes. Short instructions below the cache minimum are simply not cached."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if system else system


def track(j):
    u = (j or {}).get("usage") or {}
    USAGE["calls"] += 1
    USAGE["in"] += u.get("input_tokens", 0); USAGE["out"] += u.get("output_tokens", 0)
    USAGE["cached"] += u.get("cache_read_input_tokens", 0) or 0; USAGE["written"] += u.get("cache_creation_input_tokens", 0) or 0


def claude(model, system, user, max_tokens=1500):
    """Call the Claude Messages API and return the text reply."""
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    for attempt in range(3):
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": cached_system(system),
                  "messages": [{"role": "user", "content": user}]},
            timeout=120,
        )
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        j = r.json(); track(j)
        return "".join(b.get("text", "") for b in j.get("content", []))
    raise RuntimeError("Claude API unavailable after retries")


def parse_json(text):
    """Pull the first JSON object or array out of a model reply. If the reply was cut off mid-list,
    keep every complete item instead of failing."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    try:
        return json.loads(m.group(1) if m else text)
    except json.JSONDecodeError:
        # only salvage a reply that IS a list; never pull a list out of the middle of a broken object
        start = text.find("[")
        if start < 0 or (text.find("{") != -1 and text.find("{") < start):
            raise
        dec, out, i = json.JSONDecoder(), [], start + 1
        while True:
            while i < len(text) and text[i] in " \r\n\t,":
                i += 1
            if i >= len(text) or text[i] == "]":
                break
            try:
                obj, i = dec.raw_decode(text, i)
            except json.JSONDecodeError:
                break
            out.append(obj)
        if not out:
            raise
        return out


NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")


def numbers_supported(story_text, source_text):
    """Every number in the story must appear in the source. Returns the unsupported ones."""
    src = source_text.replace(",", "")
    missing = []
    for n in set(NUM.findall(story_text)):
        core = n.replace("$", "").replace("%", "").replace(",", "")
        if not core or core in {"1", "2", "3"}:  # impact levels, list counts
            continue
        base = core.rstrip("0").rstrip(".") if "." in core else core
        pat = r"(?<![\d.])" + re.escape(base) + (r"0*" if "." in core else "") + r"(?![\d])"
        if not re.search(pat, src):
            missing.append(n)
    return missing


# Sources that come straight from the company or regulator. These lead every story; trade press follows.
PRIMARY_DOMAINS = ["ups.com", "fedex.com", "usps.com", "prc.gov", "dhl.com", "ontrac.com", "amazon.com", "aboutamazon.com",
                   "uniuni.com", "gofo.com", "speedeedelivery.com", "gls-us.com", "lso.com", "shipveho.com", "bettertrucks.com",
                   "jitsu.com", "cdldelivery.com", "sec.gov", "federalregister.gov", "congress.gov", "uspsoig.gov",
                   "businesswire.com", "prnewswire.com", "globenewswire.com"]


def is_primary(url):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return any(host == d or host.endswith("." + d) for d in PRIMARY_DOMAINS)


# Outlet tiers, so a story leads with the carrier's own page, then the major business press, then the parcel and
# logistics trade press, and a local paper or aggregator that picked the story up days later only backs it up.
# Matched against the outlet's web address and its name (Google News gives both).
TIER1 = {"reuters.com": "reuters", "wsj.com": "wall street journal", "bloomberg.com": "bloomberg", "cnbc.com": "cnbc",
         "apnews.com": "associated press", "ft.com": "financial times", "nytimes.com": "new york times",
         "washingtonpost.com": "washington post", "businessinsider.com": "business insider", "axios.com": "axios",
         "forbes.com": "forbes", "fortune.com": "fortune", "barrons.com": "barron's", "marketwatch.com": "marketwatch",
         "theinformation.com": "the information", "techcrunch.com": "techcrunch", "npr.org": "npr", "cnn.com": "cnn"}
TIER2 = {"freightwaves.com": "freightwaves", "supplychaindive.com": "supply chain dive", "parcelindustry.com": "parcel industry",
         "logisticsmgmt.com": "logistics management", "dcvelocity.com": "dc velocity", "supplychainbrain.com": "supplychainbrain",
         "ttnews.com": "transport topics", "joc.com": "journal of commerce", "modernretail.co": "modern retail",
         "retaildive.com": "retail dive", "truckingdive.com": "trucking dive", "postandparcel.info": "post & parcel",
         "theloadstar.com": "the loadstar", "digitalcommerce360.com": "digital commerce 360", "aircargonews.net": "air cargo news",
         "ccjdigital.com": "commercial carrier journal", "supplychain247.com": "supplychain247", "inboundlogistics.com": "inbound logistics",
         "parcelandpostaltechnologyinternational.com": "parcel and postal technology", "retailtouchpoints.com": "retail touchpoints",
         "retailbrew.com": "retail brew", "pymnts.com": "pymnts", "dronexl.co": "dronexl", "therobotreport.com": "the robot report",
         "cepresearch.com": "cep research", "globaltrademag.com": "global trade", "ajot.com": "american journal of transportation",
         "stattimes.com": "stat times", "aircargoweek.com": "air cargo week", "chainstoreage.com": "chain store age",
         "transimpact.com": "transimpact"}


def _host(url):
    return re.sub(r"^https?://", "", url or "").split("/")[0].lower().removeprefix("www.")


def tier(src=None, url=None, domain=None):
    """0 = the company or regulator itself, 1 = major business or wire press, 2 = parcel and logistics trade press, 3 = everything else."""
    if url and is_primary(url) or domain and is_primary("https://" + domain):
        return 0
    hosts = [x for x in (_host(url), _host(domain)) if x]
    name = (src or "").lower()
    for n, table in ((1, TIER1), (2, TIER2)):
        if any(hh == d or hh.endswith("." + d) for hh in hosts for d in table) or any(v in name for v in table.values()):
            return n
    return 3


def primary_first(srcs):
    """Carrier or company sources first, then major press, then trade press, then the rest (stable within a tier)."""
    return sorted(srcs, key=lambda s: tier(s.get("src"), s.get("url")))


# ---------------------------------------------------------------- what earns a spot on the rate clock
# The rate clock is for cost changes and big events, not every date a story mentions.
CLOCK_CATS = {"Pricing & GRI", "Fees & rules", "Peak season", "Fuel", "Guide changes", "Postal", "Regulation & trade",
              "Network & operations", "International", "Amazon", "Regional & alternative", "Labor"}
NOT_CLOCK = re.compile(r"\b(sentenc\w*|prison|jail|court|trial|hearing|arraign\w*|plea|verdict|indict\w*|parole|"
                       r"lawsuit|testif\w*|deposition|funeral|birthday|anniversary|earnings call|conference|webinar|summit|"
                       r"expo|award)\b", re.I)


def clock_worthy(story, d):
    """True if a story date belongs on the rate clock: a price, fee, surcharge, service or rule change taking effect,
    or a big event (lvl 3). Court dates, sentencing, conferences and the like never qualify."""
    text = f"{d.get('w', '')} {story.get('title', '')}" if isinstance(d, dict) else story.get("title", "")
    if NOT_CLOCK.search(text):
        return False
    imp = d.get("imp") if isinstance(d, dict) else story.get("imp")
    if int(story.get("lvl") or 1) >= 3:
        return True
    if story.get("cat") not in CLOCK_CATS:
        return False
    return imp in ("up", "down") or int(story.get("lvl") or 1) >= 2


import urllib.parse

CACHE_PARAMS = {"v", "ver", "version", "t", "ts", "time", "cb", "cache", "_", "rev", "updated", "dl", "download"}


def canon(u):
    """Drop cache-busting query parameters (e.g. ?v=20261011034200) so the same file isn't mistaken for a new one."""
    p = urllib.parse.urlsplit(u)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k.lower() not in CACHE_PARAMS]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


def known_doc_urls(lib=None):
    """Every document already on file (the app's built-in list plus data/docs.json), with cache stamps removed."""
    seed = load("seed.json", {})
    docs = (seed.get("docs") or []) + (lib if lib is not None else load("docs.json", []))
    return {canon(d.get("u") or "") for d in docs if d.get("u")}


# ---------------------------------------------------------------- one story per event
def _words(t):
    return {w for w in re.findall(r"[a-z0-9$%]+", (t or "").lower()) if len(w) > 2 and w not in
            {"the", "and", "for", "its", "with", "now", "new", "posts", "page", "files", "on", "list", "lists"}}


def same_event(a, b):
    """Two stories about the same thing: same carrier, a few days apart, and either the same source page or very
    similar headlines. Catches a watcher re-describing one page change in new words every hour."""
    if not set(a.get("c") or []) & set(b.get("c") or []):
        return False
    try:
        import datetime as _dt
        if abs((_dt.date.fromisoformat(a["date"][:10]) - _dt.date.fromisoformat(b["date"][:10])).days) > 4:
            return False
    except Exception:
        return False
    ua = canon(((a.get("srcs") or [{}])[0].get("url")) or a.get("url") or "")
    ub = canon(((b.get("srcs") or [{}])[0].get("url")) or b.get("url") or "")
    A, B = _words(a.get("title")), _words(b.get("title"))
    sim = len(A & B) / max(1, min(len(A), len(B)))
    return (ua and ua == ub and sim >= 0.34) or sim >= 0.7


def dedupe_live(live):
    """Keep the first story of each event (merging the others' sources into it); log the rest in retracted.json."""
    out, gone = [], []
    # data/drop.json: story ids the editor took off the site (small foreign items, off-topic pieces)
    drop = {d if isinstance(d, str) else d.get("id") for d in load("drop.json", [])}
    for s in [x for x in live if x.get("id") in drop]:
        gone.append({"id": s.get("id"), "why": "Removed by the editor: " + (s.get("title") or "")})
    live = [x for x in live if x.get("id") not in drop]
    for s in sorted(live, key=lambda x: (x.get("date") or "", x.get("id") or "")):
        twin = next((k for k in out if same_event(k, s)), None)
        if twin is None:
            out.append(s); continue
        have = {canon(x.get("url") or "") for x in twin.get("srcs") or []}
        for x in s.get("srcs") or []:
            if canon(x.get("url") or "") not in have:
                twin.setdefault("srcs", []).append(x)
        gone.append({"id": s.get("id"), "why": f"Same event as {twin.get('id')}: {twin.get('title')}"})
    if gone:
        log = load("retracted.json", [])
        known = {x.get("id") for x in log}
        save("retracted.json", log + [g for g in gone if g["id"] not in known])
        print(f"dedupe: removed or merged {len(gone)} stories (repeats of one event, or taken off by the editor)")
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out
