"""Shared helpers for the Parcel Pigeon pipeline."""
import datetime as dt, hashlib, json, os, re, time
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


def pdf_to_text(data, max_pages=None):
    """Text of a PDF, page by page ("[page N]" markers keep diffs and quotes pointing at the right page)."""
    import io
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages if max_pages is None else reader.pages[:max_pages]
    return "\n".join(f"[page {i+1}]\n" + (p.extract_text() or "") for i, p in enumerate(pages))


def h(s):
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:12]


def get(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


USAGE = {"calls": 0, "in": 0, "cached": 0, "written": 0, "out": 0, "usd": 0.0}

# ---------------------------------------------------------------- spend: what each call costs, paced across the month
# List prices in dollars per million tokens (input, output). Cache reads cost a tenth of the input price, cache writes 1.25x.
# Haiku 5.5 costs more on prompts over 100K tokens. Web search is $10 per 1,000 searches.
PRICES = {"haiku": (0.10, 0.50), "sonnet": (2.00, 10.00), "opus": (4.00, 20.00)}
SEARCH_USD = 0.01
# The Anthropic Console's monthly spend limit. Each day (U.S. Eastern, the readers' day) may spend what's left of it divided
# by the days left in the month, so a busy week can't use up the month and leave the app silent at the end of it. The
# day's allowance builds up through the day (a quarter of it is there at midnight, all of it by 6 p.m.), so one late-night
# run can't use the whole day and leave the morning with no news. A run that starts under what's built up finishes; past
# it, Claude calls wait for the next run and headlines wait unscreened (nothing is lost). Accuracy work is part of the news and is never cut on its own (reading blocked pages, re-confirming
# single-source stories, number checks). Only company research and the sweep are extras: they stop at half the day's
# allowance, so the news is the last thing to pause.
MONTHLY = float(os.environ.get("PP_MONTHLY_BUDGET") or 75)
LEDGERS = ("usage.json", "usage_sweep.json")              # the sweep runs alongside the news, so it keeps its own ledger
LEDGER = os.environ.get("PP_LEDGER") or LEDGERS[0]


ET = __import__("zoneinfo").ZoneInfo("America/New_York")
NOW = lambda: dt.datetime.now(ET)


def built_up(a, t=None):
    """How much of the day's allowance a run may have spent by now: a quarter at midnight Eastern, rising evenly to all
    of it by 6 p.m."""
    t = t or NOW()
    return a * min(1.0, 0.25 + 0.75 * (t.hour + t.minute / 60) / 18)


def cost(model, u):
    i, o = next((p for k, p in PRICES.items() if k in (model or "")), PRICES["sonnet"])
    cache_r, cache_w = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
    if "haiku" in (model or "") and (u.get("input_tokens", 0) + cache_r + cache_w) > 100_000:
        i, o = 0.50, 2.50
    usd = (u.get("input_tokens", 0) * i + cache_w * i * 1.25 + cache_r * i * 0.1 + u.get("output_tokens", 0) * o) / 1e6
    return usd + SEARCH_USD * ((u.get("server_tool_use") or {}).get("web_search_requests") or 0)


def spent(day=None):
    """(today, this month, this month before today) in dollars, from the ledgers plus this process's calls so far.
    A ledger's "carry" holds what the month had already spent before the ledger existed (from the Console)."""
    day = day or NOW().date().isoformat()
    today = before = 0.0
    for name in LEDGERS:
        led = load(name, {})
        led = led if isinstance(led, dict) else {}
        before += float((led.get("carry") or {}).get(day[:7]) or 0)
        for d, usd in (led.get("days") or {}).items():
            usd = usd if isinstance(usd, (int, float)) else 0     # a damaged entry must never stop every Claude call
            if d[:7] == day[:7]:
                if d < day:
                    before += usd
                elif d == day:
                    today += usd
    today += USAGE["usd"]
    return today, before + today, before


def allowance(day=None):
    """What today may spend: the rest of the monthly limit spread over the days left in the month, today included."""
    d = dt.date.fromisoformat(day) if day else NOW().date()
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return max(0.0, MONTHLY - spent(d.isoformat())[2]) / (nxt - d).days


PACE = {}


def paused(extra=False):
    """Why Claude calls should wait, or None. Decided once per run for the news itself (a run that starts finishes);
    extras are checked each time."""
    if extra:
        today, _, _ = spent()
        a = allowance()
        return f"extras pause at half of today's ${a:.2f} allowance (${today:.2f} spent)" if today >= a / 2 else None
    if "why" not in PACE:
        today, month, _ = spent()
        a = allowance()
        b = built_up(a)
        PACE["why"] = (f"${today:.2f} spent today of the ${b:.2f} built up so far (day's allowance ${a:.2f}; "
                       f"${month:.2f} of ${MONTHLY:.0f} this month)" if today >= b else None)
        if PACE["why"]:
            print(f"::notice title=Claude calls wait for a later run::{PACE['why']}. Headlines wait and are screened then.")
    return PACE["why"]


def extras_ok():
    return not API_DOWN and not paused(extra=True)


# Two small lanes skip the day's pacing, each with its own hard cap, so the pacing can never hold back what matters most:
# the breaking-news lane (news.py: at most BREAKING_PER_DAY big stories a day while the news is paused) and the nightly
# company-research slot (players.py --slot: a few candidates before the news on the 04 UTC run). What they spend still
# goes in the ledger, so the next days' allowances shrink to match and the month stays inside the limit. They stop too
# once the month is within MONTH_RESERVE of the limit, so the Console's hard limit is never the thing that stops the app.
MONTH_RESERVE = 1.50
UNPACED = {"on": False}


def month_full():
    """Why even the unpaced lanes must stop (the month is nearly at its limit), or None."""
    _, month, _ = spent()
    return f"${month:.2f} of ${MONTHLY:.0f} spent this month" if month >= MONTHLY - MONTH_RESERVE else None


class unpaced:
    """with unpaced(): Claude calls inside skip the day's pacing (never the month's limit)."""
    def __enter__(self):
        self.was = UNPACED["on"]; UNPACED["on"] = True
        return self

    def __exit__(self, *a):
        UNPACED["on"] = self.was


def _usage_report():
    if USAGE["calls"]:
        today, month, _ = spent()
        print(f"claude usage this step: {USAGE['calls']} calls, {USAGE['in'] + USAGE['cached'] + USAGE['written']} input tokens "
              f"({USAGE['cached']} read from cache), {USAGE['out']} output tokens, ${USAGE['usd']:.3f} "
              f"(today ${today:.2f} of ${allowance():.2f}; month ${month:.2f} of ${MONTHLY:.0f})")
        led = load(LEDGER, {})
        led = led if isinstance(led, dict) else {}
        days = led.setdefault("days", {})
        d = NOW().date().isoformat()
        days[d] = round(days.get(d, 0) + USAGE["usd"], 4)
        led["days"] = dict(sorted(days.items())[-120:])
        save(LEDGER, led)


import atexit
atexit.register(_usage_report)


def cached_system(system):
    """The instructions go out with a cache marker: the same instructions sent again within a few minutes (every story
    in a run, every storyline in a pass) are read from Anthropic's prompt cache at a tenth of the price. Replies are
    identical; only the bill changes. Short instructions below the cache minimum are simply not cached."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if system else system


def track(j):
    u = (j or {}).get("usage") or {}
    USAGE["calls"] += 1; USAGE["usd"] += cost((j or {}).get("model"), u)
    USAGE["in"] += u.get("input_tokens", 0); USAGE["out"] += u.get("output_tokens", 0)
    USAGE["cached"] += u.get("cache_read_input_tokens", 0) or 0; USAGE["written"] += u.get("cache_creation_input_tokens", 0) or 0


API_DOWN = {}      # set once the API refuses for a reason that won't change this run (credit, key, permission)


def api_check(r):
    """Raise with the API's own explanation instead of a bare "400 Bad Request". When the account itself is the problem
    (no credit, spend limit reached, bad key), say so loudly in the run summary and stop further calls this run."""
    if r.status_code < 400:
        return
    try:
        err = (r.json() or {}).get("error") or {}
    except Exception:
        err = {}
    kind, msg = err.get("type") or "", (err.get("message") or r.text[:200]).strip()
    fatal = r.status_code in (401, 403) or re.search(r"credit balance|billing|spend limit|usage limit|purchase credits", msg, re.I)
    if fatal and not API_DOWN:
        API_DOWN["why"] = f"{r.status_code} {kind}: {msg}"
        print(f"::error title=Claude API refused every call::{API_DOWN['why']} (check the Anthropic Console: credit balance, spend limit, API key)")
    raise RuntimeError(f"Claude API {r.status_code} {kind}: {msg}")


# Sonnet 5.5 and Haiku 5.5 think before answering, and the thinking counts against max_tokens: a 900-token brief once
# came back empty because thinking used all 900. Calls run at each model's own default effort (thinking is where the
# care goes: quality and accuracy come first), and THINK_ROOM is headroom on top of what the caller asks for, so the
# reply always gets its full max_tokens. Headroom costs nothing unless it is used. PP_EFFORT ("low", "medium", "high")
# overrides the effort for every call; leave it unset.
EFFORT = os.environ.get("PP_EFFORT") or None
THINK_ROOM = 16000


def with_effort(body, effort=None):
    effort = effort or EFFORT
    if effort:
        body["output_config"] = {"effort": effort}
    return body


def claude(model, system, user, max_tokens=1500, paced=True):
    """Call the Claude Messages API and return the text reply. paced=False skips the day's pacing (for the once-a-day
    brief, about 3 cents: readers expect it in the morning, not whenever the allowance has built up again)."""
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    if API_DOWN:
        raise RuntimeError("Claude API unavailable this run: " + API_DOWN["why"])
    if paced and not UNPACED["on"] and paused():
        raise RuntimeError("Claude calls paused: " + paused())
    if UNPACED["on"] and month_full():
        raise RuntimeError("Claude calls paused: " + month_full())
    for attempt in range(3):
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=with_effort({"model": model, "max_tokens": max_tokens + THINK_ROOM, "system": cached_system(system),
                              "messages": [{"role": "user", "content": user}]}),
            timeout=360,
        )
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (attempt + 1))
            continue
        api_check(r)
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
         "transimpact.com": "transimpact", "paymentsdive.com": "payments dive", "truckinginfo.com": "heavy duty trucking",
         "mlex.com": "mlex", "qz.com": "quartz", "seekingalpha.com": "seeking alpha", "mediapost.com": "mediapost",
         "logisticsmanager.com": "logistics manager", "supplychaindigital.com": "supply chain digital", "logisticsviewpoints.com": "logistics viewpoints",
         "freightcaviar.com": "freightcaviar", "joc.com": "joc", "theverge.com": "the verge", "geekwire.com": "geekwire"}


# Never a source: press-release spam sites, automated finance write-ups and AI-written market reports. Items from these
# are dropped at intake and never listed under a story.
NOT_SOURCES = ["einnews.com", "einpresswire.com", "openpr.com", "newsbreak.com", "gurufocus.com", "simplywall.st", "marketbeat.com",
               "tickerreport.com", "biggo.com", "trendhunter.com", "indexbox.io", "giiresearch.com", "marketresearchfuture.com",
               "openpr.de", "issuewire.com", "newswire.com", "prlog.org", "whatech.com"]
NOT_SOURCE_NAMES = ["ein news", "ein presswire", "openpr", "gurufocus", "simply wall st", "marketbeat", "indexbox", "trend hunter",
                    "newsbreak", "prlog", "issuewire"]


def not_a_source(src=None, url=None, domain=None):
    hosts = [x for x in (_host(url), _host(domain)) if x]
    name = (src or "").lower()
    return any(hh == d or hh.endswith("." + d) for hh in hosts for d in NOT_SOURCES) or any(n in name for n in NOT_SOURCE_NAMES)


def _host(url):
    return re.sub(r"^https?://", "", url or "").split("/")[0].lower().removeprefix("www.")


def tier(src=None, url=None, domain=None):
    """0 = the company or regulator itself, 1 = major business or wire press, 2 = parcel and logistics trade press, 3 = everything else."""
    if url and is_primary(url) or domain and is_primary("https://" + domain):
        return 0
    if any(h.endswith(".gov") for h in (_host(url), _host(domain)) if h):
        return 0          # government bodies and officials speak for themselves
    hosts = [x for x in (_host(url), _host(domain)) if x]
    name = (src or "").lower()
    for n, table in ((1, TIER1), (2, TIER2)):
        if any(hh == d or hh.endswith("." + d) for hh in hosts for d in table) or any(v in name for v in table.values()):
            return n
    return 3


def primary_first(srcs):
    """Carrier or company sources first, then major press, then trade press, then the rest (stable within a tier)."""
    return sorted(srcs, key=lambda s: tier(s.get("src"), s.get("url")))


# ---------------------------------------------------------------- on-cycle vs off-cycle rate changes
# Carriers used to change prices once a year (the general rate increase, with its surcharge and fee changes) plus the
# holiday peak. Changes outside those windows are "off-cycle", and they have become far more common. The app's
# cycleOf() in index.html applies the same rule; tests/test_cycle.py keeps the two in step.
COST_KINDS = {"gri", "price_change", "peak", "surcharge", "fee", "fuel_table", "dim", "das"}


def cycle_of(carrier, kind, effective, announced=None):
    """'on' or 'off' for a carrier price change by the date it TAKES EFFECT; None for anything that isn't one.
    On-cycle: the annual increase window (Dec 15 - Jan 20; for USPS its January price change) and peak surcharges in
    the September-January season. Everything else (a mid-year increase, a new surcharge in May, a temporary USPS
    increase, a summer fuel-table change) is off-cycle. A change announced with the annual increase (mid-August to
    mid-December) that takes effect by the end of February is part of that cycle, even when staggered (e.g. a zone change
    on Feb. 1)."""
    import datetime as _dt
    if kind not in COST_KINDS or not effective:
        return None
    try:
        d = _dt.date.fromisoformat(str(effective)[:10])
    except ValueError:
        return None
    if kind == "peak":
        return "on" if d.month >= 9 or d.month == 1 else "off"
    try:
        a = _dt.date.fromisoformat(str(announced)[:10]) if announced else None
    except ValueError:
        a = None
    if a and ((a.month, a.day) >= (8, 15) and (a.month, a.day) <= (12, 15)) and (d.month in (1, 2) or (d.month == 12 and d.day >= 15)) \
            and (d - a).days < 200:
        return "on"
    if carrier == "USPS":
        return "on" if d.month == 1 else "off"
    return "on" if (d.month == 12 and d.day >= 15) or (d.month == 1 and d.day <= 20) else "off"


def kind_of(text, cat=None):
    """Which kind of price change a story or rate clock line describes (for cycle_of), from its wording."""
    t = (text or "").lower()
    if re.search(r"peak|demand surcharge|holiday (price|surcharge|rate)", t):
        return "peak"
    if "fuel" in t:
        return "fuel_table"
    if re.search(r"general rate|\bgri\b|rate increase|average (net )?increase|price (change|increase)|prices? (rise|increase)|raises? (\w+ ){0,2}(rates|prices)|list rates", t):
        return "gri"
    if re.search(r"surcharge|\bfees?\b|zone|dimensional|\bdim\b|delivery area|divisor", t):
        return "surcharge"
    return "gri" if cat == "Pricing & GRI" else None


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


def doc_key(u):
    """One key per document, whatever address it was reached by: no scheme, www, cache stamp or trailing slash, and an
    Adobe asset (UPS serves the same rate guide from assets.ups.com and from its adobeaemcloud.com host) keyed by its id."""
    u = urllib.parse.unquote(str(u or ""))
    a = re.search(r"urn:aaid:aem:([0-9a-f-]{36})", u, re.I)
    if a:
        return "aem:" + a.group(1).lower() + ":" + u.split("?")[0].rstrip("/").split("/")[-1].lower()
    return re.sub(r"^https?://(www\.)?", "", canon(u), flags=re.I).rstrip("/").lower()


def known_doc_urls(lib=None):
    """Every document already on file (the app's built-in list plus data/docs.json): their addresses with cache stamps
    removed, plus each one's doc_key, so `doc_key(u) in known_doc_urls()` also catches the same file at another address."""
    seed = load("seed.json", {})
    docs = (seed.get("docs") or []) + (lib if lib is not None else load("docs.json", []))
    return {canon(d.get("u") or "") for d in docs if d.get("u")} | {doc_key(d["u"]) for d in docs if d.get("u")}


# The year a document is filed under (the app's docYear() in index.html follows the same rule). A year the document
# states for itself wins: "2026 UPS Rate Guide" is a 2026 document even if it was stored as 2025. A year inside a full
# date ("signed before Aug 1, 2018", "Dec 22, 2025 edition") is a date, not the document's year. Then the file name, then
# the upload folder (/uploads/2025/08/) for a document with no year, then the year stored. Market reports keep their
# publication year: a 2026 report on 2025 volume is a 2026 report.
_DATE_YEAR = re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(20[1-3]\d)", re.I)


def stated_years(text):
    return sorted({int(y) for y in re.findall(r"(?<![\d.])(20[1-3]\d)(?![\d.]?\d)", _DATE_YEAR.sub(" ", str(text or "")))})


ACRONYMS = {"ups": "UPS", "usps": "USPS", "dhl": "DHL", "gri": "GRI", "us": "U.S.", "fedex": "FedEx", "ontrac": "OnTrac", "ahs": "AHS", "das": "DAS", "zip": "ZIP"}


def doc_from_filename(carrier, filename, today=None):
    """(type, readable name, year) for a file a carrier just posted, from its file name. A "preview" file is next
    year's rates (UPS: "2027 Preview Package Rates"), named as such; a value-added/other-charges file is a surcharge
    document and a "... service package rates" file a rate guide, not a service guide."""
    import datetime as _dt
    today = today or _dt.date.today()
    low = filename.lower()
    kind = ("Surcharges & fees" if re.search(r"surcharge|ahs|lps|accessor|fee|value.?added|other.?charges", low) and "zip" not in low else
            "Zones & DAS" if re.search(r"zip|zone|area|das", low) else "Fuel" if "fuel" in low else
            "Service guide" if re.search(r"service.?guide", low) else "Terms" if re.search(r"terms|tariff|condition", low) else
            "Rate guide" if re.search(r"rate|price", low) else "Service guide" if "service" in low else "Special program")
    raw = re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", re.sub(r"\.(pdf|xlsx?)$", "", filename, flags=re.I))).strip()
    preview = bool(re.search(r"\bpreview\b", raw, re.I))
    year = doc_year({"c": carrier, "n": raw, "u": filename})
    if preview and not year and today.month >= 8:
        year = today.year + 1
    if not preview:
        name = raw
        return kind, (f"{carrier} {name}" if carrier.lower() not in name.lower() else name), year
    words = [w for w in re.sub(r"(?i)\bpreview\b", " ", raw).split() if w.lower() != carrier.lower() and not re.fullmatch(r"20\d\d", w)]
    text = re.sub(r"(?i)\bvalue added\b", "value-added", " ".join(words))
    text = re.sub(r"(?i)\bcwt\b", "hundredweight", text)
    small = {"and", "of", "to", "for", "the", "or"}
    title = " ".join(ACRONYMS.get(w.lower()) or ("-".join(p.capitalize() for p in w.split("-")) if w.lower() not in small else w.lower()) for w in text.split())
    return kind, f"{year} {carrier} {title} (preview)".strip() if year else f"{carrier} {title} (preview)", year


def doc_year(d):
    if d.get("c") != "Reports":
        t = stated_years(d.get("n"))
        if len(t) == 1:
            return t[0]
        if not t and d.get("u"):
            path = urllib.parse.unquote(urllib.parse.urlsplit(d["u"]).path)
            f = stated_years(path.rstrip("/").split("/")[-1])
            if len(f) == 1:
                return f[0]
            up = re.search(r"/uploads/(20[1-3]\d)/\d{2}/", path)
            if up and not d.get("y"):
                return int(up.group(1))
    return d.get("y")


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
    # B10: similar wording isn't enough. "UPS raises Ground fuel surcharge Nov 2" and "UPS raises Air fuel surcharge
    # Nov 9" are two events: a different effective date or a different service keeps them apart.
    ea, eb = _effective(a), _effective(b)
    if ea and eb and ea != eb:
        return False
    sa, sb = _service_set(a.get("title")), _service_set(b.get("title"))
    if sa and sb and sa != sb:
        return False
    ua = canon(((a.get("srcs") or [{}])[0].get("url")) or a.get("url") or "")
    ub = canon(((b.get("srcs") or [{}])[0].get("url")) or b.get("url") or "")
    A, B = _words(a.get("title")), _words(b.get("title"))
    sim = len(A & B) / max(1, min(len(A), len(B)))
    return (ua and ua == ub and sim >= 0.34) or sim >= 0.7


_SERVICE_NAMES = ["Ground Saver", "Ground Advantage", "Ground Economy", "Home Delivery", "Priority Mail Express", "Priority Mail",
                  "SurePost", "Next Day Air", "2nd Day Air", "Ground", "Air", "Express", "Freight", "International"]
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _service_set(title):
    """Carrier services a headline names ("Ground Saver" counts once, not also as "Ground")."""
    t, out = title or "", set()
    for s in _SERVICE_NAMES:
        if re.search(r"\b" + re.escape(s) + r"\b", t, re.I):
            out.add(s.lower())
            t = re.sub(r"\b" + re.escape(s) + r"\b", " ", t, flags=re.I)
    return out


def _effective(s):
    """The date a story's change takes effect: its act date, else a month-day date its headline states (as MM-DD)."""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(s.get("act") or "")):
        return s["act"][5:]
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", s.get("title") or "", re.I)
    return f"{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}" if m else None


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
        # an M&A card whose story merged into a twin follows the twin, so the card and News stay linked
        twin_of = {g["id"]: g["why"].split(":")[0].replace("Same event as ", "") for g in gone if g["why"].startswith("Same event as ")}
        if twin_of:
            dl, moved = load("deals.json", []), False
            for d in dl:
                if d.get("story") in twin_of:
                    d["story"] = twin_of[d["story"]]; moved = True
                for u in d.get("updates") or []:
                    if isinstance(u, dict) and u.get("story") in twin_of:
                        u["story"] = twin_of[u["story"]]; moved = True
            if moved:
                save("deals.json", dl)
        print(f"dedupe: removed or merged {len(gone)} stories (repeats of one event, or taken off by the editor)")
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out


# ---------------------------------------------------------------- deals: one card per transaction
# A deal is followed from announcement to its end. Later stories about it (a closing, a breach notice, a termination) update
# the same card instead of opening a second one. The app (index.html, dealSame) mirrors this matching exactly.
DEAL_STATUSES = ("Announced", "Pending", "Closed", "Terminated", "Blocked", "Withdrawn")
DEAL_ENDED = {"Terminated", "Blocked", "Withdrawn"}          # the deal will not happen
DEAL_DONE = DEAL_ENDED | {"Closed"}                           # nothing more to wait for
_DEAL_STOP = set("corp corporation inc incorporated llc lp llp ltd limited plc co company group holdings holding "
                 "acquisition acquisitions the sa se ag nv bv gmbh spa srl pte pty spac".split())
# fields an update never changes: the card keeps the transaction's name, first story and announcement date
DEAL_FIXED = ("buyer", "target", "title", "ann", "story", "who", "why", "ties", "parties", "tree")


def deal_tokens(name):
    """A company name reduced to the words that identify it: lowercase, no parenthetical, no legal suffixes or
    words like Corp, Inc, Acquisition, Holdings. "MAK Acquisition Corp. (SPAC)" -> ["mak"]."""
    s = re.sub(r"\([^)]*\)", " ", str(name or "").lower())
    s = re.sub(r"[.'’&]", "", s)
    return [w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _DEAL_STOP]


def deal_names_match(a, b):
    """Same company: the same identifying words, or one name's words all inside the other's ("Evri" / "Evri Group")."""
    A, B = set(deal_tokens(a)), set(deal_tokens(b))
    return bool(A and B) and (A <= B or B <= A)


def deal_same(x, y):
    """Two deal records describe the same transaction: targets match and buyers match (a merger may be written either way round)."""
    if not x or not y:
        return False
    m = deal_names_match
    return (m(x.get("target"), y.get("target")) and m(x.get("buyer"), y.get("buyer"))) or \
           (m(x.get("target"), y.get("buyer")) and m(x.get("buyer"), y.get("target")))


def deal_status(deal, *texts):
    """The deal's status, from the allowed list. A story that plainly reports the end of a deal ("MAK terminates UniUni deal")
    is not left as Announced or Pending even if the writer said so."""
    raw = str((deal or {}).get("status") or "").strip().lower()
    st = next((s for s in DEAL_STATUSES if s.lower() == raw), "Announced")
    if st in ("Announced", "Pending"):
        t = " ".join(str(x or "") for x in texts)
        if re.search(r"\b(terminat\w*|called off|calls off|scrap(s|ped)?|abandon(s|ed)?)\b", t, re.I):
            st = "Terminated"
        elif re.search(r"\bblocked\b|\bblocks\b", t, re.I):
            st = "Blocked"
        elif re.search(r"\bwithdr[ae]w\w*\b|\bwithdrawn\b", t, re.I):
            st = "Withdrawn"
    return st


def _union_srcs(a, b):
    out, seen = [], set()
    for x in list(a or []) + list(b or []):
        u = (x or {}).get("url")
        if u and u not in seen:
            seen.add(u); out.append(x)
    return out


def _union_updates(a, b):
    out, seen = [], set()
    for x in list(a or []) + list(b or []):
        k = (x or {}).get("story") or ((x or {}).get("d"), (x or {}).get("t"))
        if x and x.get("d") and k not in seen:
            seen.add(k); out.append(x)
    return sorted(out, key=lambda u: u.get("d") or "")


def deal_overlay(base, ov):
    """The deal as readers see it: the built-in record with a newer pipeline update laid over it (same rules as the app)."""
    out = dict(base)
    if not ov or (ov.get("checked") or ov.get("d") or "") < (base.get("checked") or ""):
        return out
    for k, v in ov.items():
        if k == "srcs":
            out[k] = _union_srcs(base.get(k), v)
        elif k == "updates":
            out[k] = _union_updates(base.get(k), v)
        elif k in DEAL_FIXED and base.get(k) not in (None, "", []):
            continue
        elif k == "status":
            out[k] = deal_forward(base.get(k), v)
        elif v not in (None, "", []):
            out[k] = v
    return out


def deal_forward(prev, new):
    """Status only moves forward: a finished deal (closed or ended) isn't reopened, and Pending doesn't fall back to Announced."""
    if prev in DEAL_DONE and new not in DEAL_DONE:
        return prev
    if prev == "Pending" and new == "Announced":
        return prev
    return new or prev


def deals_merged(seed_deals, live_deals):
    """Every deal once: built-in deals with their updates from data/deals.json laid over them, then pipeline-only deals."""
    out = [dict(x) for x in seed_deals or []]
    for x in live_deals or []:
        if not x or not x.get("target"):
            continue
        i = next((i for i, y in enumerate(out) if deal_same(x, y)), None)
        if i is None:
            out.append(dict(x))
        else:
            out[i] = deal_overlay(out[i], x)
    return out


def deal_advance(cur, new, story):
    """What changes on an existing deal when a new story reports on it. Returns the fields to write (an overlay):
    status moves forward only (Announced -> Pending -> Closed, or to Terminated/Blocked/Withdrawn), the announcement date
    and title stay, the end or closing date is recorded, and the story joins the deal's timeline."""
    prev = deal_status(cur)
    st = deal_forward(prev, deal_status(new, new.get("title"), story.get("title")))
    day = (story.get("date") or "")[:10]
    when = ((new.get("ended") if st in DEAL_ENDED else new.get("closed") if st == "Closed" else None) or day)[:10]
    first = cur.get("ann") or cur.get("d")
    ups = cur.get("updates") or ([{"d": first[:10], "t": cur.get("title") or "Deal announced", "story": cur.get("story")}] if first else [])
    try:
        echo = st == prev and abs((dt.date.fromisoformat(when) - dt.date.fromisoformat(first[:10])).days) <= 3
    except (TypeError, ValueError):
        echo = False
    if echo:                                                     # more coverage of the announcement itself isn't a new step
        if ups and not ups[0].get("story") and story.get("id"):
            ups = [dict(ups[0], story=story["id"])] + ups[1:]
    else:
        ups = _union_updates(ups, [{"d": when, "t": story.get("title") or new.get("title") or "", "story": story.get("id")}])
    ov = {"buyer": cur.get("buyer"), "target": cur.get("target"), "title": cur.get("title"), "ann": cur.get("ann"),
          "story": cur.get("story") or story.get("id"), "status": st, "updates": ups,
          "srcs": _union_srcs(cur.get("srcs"), story.get("srcs") or [{"src": story.get("src"), "url": story.get("url")}]),
          "checked": max(str(cur.get("checked") or ""), day), "d": max(str(cur.get("d") or ""), when)}
    if st in DEAL_ENDED:
        ov["ended"] = cur.get("ended") if prev == st and cur.get("ended") else when
    if st == "Closed":
        ov["closed"] = cur.get("closed") if prev == "Closed" and cur.get("closed") else when
    if st != prev:
        ov["sum"] = new.get("sum") or cur.get("sum")
        ov["latest"] = new.get("latest") or f"{st} {when}: {story.get('title') or ''}".strip()
        if new.get("note"):
            ov["note"] = new["note"]
    else:
        ov["latest"] = new.get("latest") or cur.get("latest") or ""
    return {k: v for k, v in ov.items() if v not in (None, "")}


def record_deal(deal, story):
    """Write a story's deal to data/deals.json. A deal already tracked (built in, or added earlier) is updated, keyed by
    its existing buyer and target so the app lays the update over the same card; only a new transaction adds a card.
    Returns the deal as readers now see it."""
    seed = load("seed.json", {}).get("deals", [])
    dl = load("deals.json", [])
    base = next((x for x in seed if deal_same(x, deal)), None)
    own = next((x for x in dl if deal_same(x, deal) or (base and deal_same(x, base))), None)
    if base or own:
        cur = deal_overlay(base, own) if base and own else (base or own)
        ov = deal_advance(cur, deal, story)
        if own:
            for k in ("buyer", "target", "title", "ann", "story"):
                if own.get(k) not in (None, ""):
                    ov.pop(k, None)                              # the record keeps its key, name and first story
            own.update(ov)
        else:
            dl.insert(0, ov)
        save("deals.json", dl)
        return deal_overlay(base, own or ov) if base else own
    d = dict(deal)
    st = deal_status(d, d.get("title"), story.get("title"))
    day = (story.get("date") or "")[:10]
    d.update({"status": st, "d": d.get("closed") or d.get("ended") or day, "story": story["id"], "url": story.get("url"),
              "srcs": story.get("srcs") or [{"src": story.get("src"), "url": story.get("url")}], "checked": day,
              "updates": [{"d": (d.get("ann") or day)[:10], "t": story.get("title") or d.get("title") or "", "story": story["id"]}]})
    if st in DEAL_ENDED:
        d["ended"] = d.get("ended") or day
    if not d.get("latest"):
        d["latest"] = f"{st} {(d.get('ended') or d.get('closed') or d.get('ann') or day)[:10]}"
    dl.insert(0, d)
    save("deals.json", dl)
    return d


# ---------------------------------------------------------------- program promises (data/programs.json, B3)
# What each carrier program advertises as included (UPS Small Business Rates: "inclusive of Delivery Area Surcharge,
# Fuel Surcharge and other value-added services"), so a change that adds one of those charges is recognized as taking
# away a stated benefit instead of being reported as a routine fee change.
def _has(term, text):
    return bool(term) and re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", (text or "").lower()) is not None


def programs_for(carrier, *texts, urls=()):
    """The program records for this carrier that the texts name (by name or alias) or whose own pages are in `urls`."""
    out = []
    for p in (load("programs.json", {}) or {}).get("programs") or []:
        if not isinstance(p, dict) or (carrier and p.get("carrier") != carrier):
            continue
        names = [p.get("name"), p.get("short")] + list(p.get("aka") or [])
        if any(canon(u) in {canon(x) for x in p.get("pages") or []} for u in urls if u) or \
                any(_has(n, t) for n in names if n for t in texts):
            out.append(p)
    return out


def program_label(p):
    return p.get("short") or p.get("name") or "program"


def program_brief(progs):
    """The program records as prompt text: what each program says is included, with its source and check date, and the rule."""
    if not progs:
        return ""
    lines = []
    for p in progs:
        inc = "; ".join(f"{i['what']} included" for i in p.get("includes") or [])
        none = ", ".join(i["what"] for i in p.get("no_fees") or [])
        lines.append(f"- {p.get('name')} ({program_label(p)}): the carrier states it is \"{p.get('stated')}\". {inc}."
                     + (f" No {none} fees." if none else "") + f" Source: {(p.get('pages') or [''])[0]}, checked {p.get('checked')}.")
    return ("PROGRAM PROMISES (what the carrier advertises for these programs; a baseline, not news):\n" + "\n".join(lines) +
            "\nRule: if a change ADDS a charge the program says is included, or a fee it says it does not charge, it takes away a "
            "stated benefit: imp \"up\", lvl 2 or 3, and the \"why\" starts with \"Removes a stated <program> benefit: \" naming it.")


_REMOVAL = re.compile(r"\b(no longer (appl|charg|assess)|waiv|remov|eliminat|discontinu|exempt|will not apply|does not apply)", re.I)
# the charge is being applied or added (a mere mention, e.g. "the Area Surcharge ZIP list will change", is not)
_CHARGE = re.compile(r"\b(appl(y|ies|ied)|assessed|added|adds?|new|introduc\w*|will be charged|now charged|subject to)\b", re.I)
# a sentence restating the promise ("which include the fuel surcharge at no extra cost") is not a change to it
_STILL_INCLUDED = re.compile(r"\b(includ(e|es|ed|ing)|inclusive of|at no (extra|additional) (cost|charge)|free of charge)\b", re.I)
_STRONG_CHARGE = re.compile(r"\b(appl(y|ies|ied)|assessed|added|adds?|introduc\w*|will be charged|now charged)\b", re.I)


def benefit_removed(progs, changes=(), text=""):
    """(program, promise) for the first change that adds a charge a program says is included (or says it never charges).
    `changes` are proven audit changes ({what, after}) from a document that belongs to the program; `text` is a written
    story, where the program, the charge and the adding must all be in one sentence (an article about a general rate
    increase that mentions SBR elsewhere is not an SBR benefit change). None when nothing matches."""
    for p in progs:
        names = [n for n in [p.get("name"), p.get("short")] + list(p.get("aka") or []) if n]
        items = [f"{c.get('what') or ''} {c.get('after') or ''}" for c in changes if isinstance(c, dict)]
        items += [s for s in re.split(r"(?<=[.;!?])\s+", text or "") if any(_has(n, s) for n in names)]
        for promise in (p.get("includes") or []) + (p.get("no_fees") or []):
            for s in items:
                if any(_has(t, s) for t in promise.get("match") or []) and _CHARGE.search(s) and not _REMOVAL.search(s) \
                        and not (_STILL_INCLUDED.search(s) and not _STRONG_CHARGE.search(s)):
                    return p, promise
    return None


def apply_benefit_rule(obj, progs, changes=(), text=""):
    """B3 rule, enforced in code whatever the model wrote: a change that adds a charge the program says is included gets
    imp 'up', lvl at least 2, and a "why" starting "Removes a stated <program> benefit: ". Returns True when it applied."""
    hit = benefit_removed(progs, changes, text)
    if not hit:
        return False
    p, promise = hit
    label = program_label(p)
    head = f"Removes a stated {label} benefit: "
    obj["imp"] = "up"
    obj["lvl"] = max(2, int(obj.get("lvl") or 1))
    why = str(obj.get("why") or "")
    if not why.startswith(head):
        what = promise["what"]
        said = "was advertised as included" if promise in (p.get("includes") or []) else "was advertised as never charged"
        obj["why"] = head + f"{what} {said} in {p.get('name')}."
    # where the promise comes from, for the story page and a person checking it
    obj["benefit"] = {"program": p.get("id"), "what": promise["what"], "src": promise.get("src"), "checked": promise.get("checked")}
    return True
