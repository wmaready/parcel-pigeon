"""Phone alerts for Parcel Pigeon (web push through OneSignal).

Readers hear about each story on its own, as it comes in, but never a pile at once:
  Regular  every new story, rate clock reminder and new company joins a queue. Each run (every two hours) sends at most
           MAX_PER_RUN pushes. A quiet run (one or two items) sends each on its own, SPACING_MIN apart. A busy run
           (three or more) sends the biggest story on its own and rolls the rest into ONE "N more" note, so bigger news
           gets its own alert and small items never pile up. Regular pushes stay MIN_GAP_MIN apart across runs
           (alerts.py runs hourly from watch.yml too); big news skips the wait. No more than MAX_PER_DAY a day. Held overnight
           (9 p.m. to 7 a.m. Eastern). Weekly fuel moves go only to readers who set a threshold.
  Major    goes to the editor first: a GitHub issue (GitHub emails it) plus a push to the editor's own phone.
           Reply "send" on the issue to push it to everyone now, "hold" to stop it. With no reply it goes out
           automatically after AUTO_SEND_HOURS (never overnight).

Usage:
  python alerts.py            after news, fuel and docwatch: find new events, send regular alerts, open review issues
  python alerts.py --review   check open review issues: send approved or overdue ones, close held ones

Secrets (GitHub > Settings > Secrets and variables > Actions):
  ONESIGNAL_APP_ID    from OneSignal > Settings > Keys & IDs (not secret, but kept with the others)
  ONESIGNAL_API_KEY   the App API key from the same page
  PP_ADMIN_IDS        your own device's alert ID, shown under "Device ID" at the bottom of Docs & alerts > Alerts once alerts are on
  NTFY_TOPIC          optional extra phone push through the free ntfy app
"""
import datetime as dt
import json
import os
import re
import sys
import uuid
from zoneinfo import ZoneInfo

import requests
from urllib.parse import urljoin

from common import same_event, load, save, get, claude, parse_json, is_primary, MODEL_FAST, canon, known_doc_urls

ET = ZoneInfo("America/New_York")
AUTO_SEND_HOURS = float(os.environ.get("PP_AUTO_SEND_HOURS") or 2)
QUIET_START, QUIET_END = 21, 7          # Eastern; regular and automatic alerts wait for morning
MAX_REGULAR_SENDS = 8                    # copy is written for at most this many stories per run
MAX_PER_RUN = 2                          # separate story pushes per run (runs are two hours apart)
SPACING_MIN = 55                         # minutes between pushes sent in the same run
MAX_PER_DAY = 10                         # per day, all readers; anything past this stays in the app
MIN_GAP_MIN = 50                         # minutes between regular pushes across runs (big news skips the wait)
QUEUE_HOURS = 30                         # a story that hasn't gone out by then is old news; it stays in the app only
MAX_MAJOR_PER_RUN = 3
FRESH_DAYS = 2                           # only alert on stories from the last two days

APP_ID = os.environ.get("ONESIGNAL_APP_ID", "").strip()
API_KEY = os.environ.get("ONESIGNAL_API_KEY", "").strip()
ADMIN_IDS = [x.strip() for x in os.environ.get("PP_ADMIN_IDS", "").replace("\n", ",").split(",") if x.strip()]
REPO = os.environ.get("GITHUB_REPOSITORY", "wmaready/parcel-pigeon")
OWNER = REPO.split("/")[0]
GH = os.environ.get("GITHUB_TOKEN", "")
SITE = os.environ.get("SITE_URL") or f"https://{OWNER}.github.io/{REPO.split('/')[1]}/"
ICON = SITE + "icon-192.png"

# carriers are one 5-bit number per reader (tag "cm"); OneSignal's free plan allows 6 tags per reader
BITS = {"UPS": 1, "FedEx": 2, "USPS": 4, "Amazon": 8, "OnTrac": 16, "DHL": 16, "Regional": 16}
BIG4 = {"UPS", "FedEx", "USPS", "Amazon"}
PRICE_CATS = {"Pricing & GRI", "Fees & rules", "Peak season", "Fuel"}
DOC_CATS = {"Guide changes", "Documents"}
DEAL_CATS = {"M&A", "Deals & partnerships"}
TOPIC_TAG = {"rates": "t_rates", "docs": "t_docs", "deals": "t_deals", "news": "t_news"}
TOPIC_WORDS = {"rates": "rate changes", "docs": "carrier guide changes", "deals": "deals", "news": "stories"}


# ---------------------------------------------------------------- helpers
def now_et():
    return dt.datetime.now(ET)


def quiet(t=None):
    h = (t or now_et()).hour
    return h >= QUIET_START or h < QUIET_END


def next_morning(t):
    m = t.replace(hour=QUIET_END, minute=0, second=0, microsecond=0)
    return m if t.hour < QUIET_END else m + dt.timedelta(days=1)


def mask_of(carriers):
    m = 0
    for c in carriers or []:
        m |= BITS.get(c, 0)
    return m or None                     # None = industry-wide, goes to everyone who picked the topic


def carriers_in(text):
    out = []
    for c in BITS:
        if re.search(r"\b" + re.escape(c) + r"\b", text or "", re.I):
            out.append(c)
    return out


def short(s, n):
    s = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def audience(extra, mask):
    """OneSignal filters: the extra conditions, for every reader whose carrier number shares a bit with mask."""
    if not mask or mask == 31:
        return list(extra)
    out = []
    for m in range(1, 32):
        if m & mask:
            if out:
                out.append({"operator": "OR"})
            out += [{"field": "tag", "key": "cm", "relation": "=", "value": str(m)}, *extra]
    return out


SENT = None                              # this run's ledger of send keys (alerts_state.json "sent"), set by run()/review()
NS = uuid.UUID("6f1c0a52-3b7e-4a8e-9c1d-2f0b7d7e5a11")


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def push(heading, body, url, filters=None, ids=None, ttl=86400, key=None, after=None):
    """One notification. `key` makes it send-once: OneSignal drops any repeat with the same idempotency key
    (30 days), and the ledger in alerts_state.json skips it before that, so overlapping runs can't double-send."""
    if key and SENT is not None and key in SENT:
        print(f"  (already sent) {heading}")
        return {"id": "dup"}
    if not (APP_ID and API_KEY):
        print(f"  (push skipped, OneSignal keys not set) {heading}: {body}")
        return None
    # iOS shows the app name on top, then this title in bold, then the message
    msg = {"app_id": APP_ID, "isAnyWeb": True, "headings": {"en": short(heading, 60)}, "contents": {"en": short(body, 120)},
           "url": url, "chrome_web_icon": ICON, "firefox_icon": ICON, "ttl": ttl}
    if key:
        msg["idempotency_key"] = str(uuid.uuid5(NS, key))
    if after:
        msg["send_after"] = after.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S GMT+0000")
    if ids:
        msg["include_subscription_ids"] = ids
    else:
        msg["filters"] = filters or [{"field": "tag", "key": "cm", "relation": "exists"}]
    r = requests.post("https://api.onesignal.com/notifications?c=push", json=msg, timeout=30,
                      headers={"Authorization": f"Key {API_KEY}", "Content-Type": "application/json"})
    try:
        j = r.json()
    except Exception:
        j = {"text": r.text[:300]}
    print(f"  push [{r.status_code}] {heading} -> {j}")
    if key and SENT is not None and (j.get("id") or "not subscribed" in json.dumps(j.get("errors") or "")):
        SENT.append(key)
    return j


def ntfy(title, body, url):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=15,
                      headers={"Title": title, "Priority": "high", "Tags": "bird", "Click": url})
    except Exception as e:
        print("ntfy failed:", e, file=sys.stderr)


def gh(method, path, **kw):
    r = requests.request(method, f"https://api.github.com/repos/{REPO}{path}", timeout=30,
                         headers={"Authorization": f"Bearer {GH}", "Accept": "application/vnd.github+json"}, **kw)
    r.raise_for_status()
    return r.json() if r.text else {}


def story_link(s, big=False):
    """Opening a push lands on the story and highlights it; big ones get Coop's delivery animation first."""
    return f"{SITE}#{'alert' if big else 'story'}={s['id']}"


COPY_PROMPT = """Write phone notification text for each parcel-shipping news story. For each: "t" a short headline,
at most 45 characters, plain and specific (carrier + what changed, e.g. "UPS adds $1.25 peak fee"); "m" one short sentence,
at most 100 characters, saying what it means for shippers or when it starts. No emoji, no hype, no exclamation marks, no
facts that aren't in the story. Reply with JSON only: {"<id>": {"t": "...", "m": "..."}}"""


def numbers_ok(text, s):
    """Every figure in the alert text must appear in the story itself (title, summary or plain line)."""
    src = " ".join(str(s.get(k) or "") for k in ("title", "sum", "plain")).replace(",", "")
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text or ""):
        n = n.replace(",", "").rstrip(".")
        if n and not re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", src):
            return False
    return True


def push_copy(stories, state):
    """Short title + message per story, written once (fast model, a fraction of a cent) and kept in state."""
    cache = state.setdefault("copy", {})
    need = [s for s in stories if s["id"] not in cache]
    if need:
        try:
            got = parse_json(claude(MODEL_FAST, COPY_PROMPT, json.dumps(
                [{"id": s["id"], "title": s["title"], "summary": short(s.get("plain") or s.get("sum") or "", 400)} for s in need]), 1200)) or {}
            for s in need:
                g = got.get(s["id"]) or {}
                if g.get("t") and g.get("m") and numbers_ok(g["t"] + " " + g["m"], s):
                    cache[s["id"]] = {"t": short(g["t"], 50), "m": short(g["m"], 110)}
                elif g.get("t"):
                    print(f"  push copy for {s['id']} had a figure that isn't in the story; using the headline instead")
        except Exception as e:
            print("  short copy failed, using the headline:", e, file=sys.stderr)
    out = {}
    for s in stories:
        c = cache.get(s["id"])
        if not c:
            first = re.split(r"(?<=[.!?])\s", short(s.get("plain") or s.get("sum") or "", 400))[0]
            c = {"t": short(s["title"], 50), "m": short(first, 110)}
        out[s["id"]] = c
    if len(cache) > 1500:
        for k in list(cache)[:-1500]:
            cache.pop(k)
    return out


# ---------------------------------------------------------------- what counts as major
def is_major(s):
    cs = set(s.get("c") or [])
    lvl = int(s.get("lvl") or 1)
    if lvl >= 3:
        return True
    return False                         # only the biggest (lvl 3) wait for your OK; everything else alerts live


def topic_of(s):
    c = s.get("cat")
    if c in PRICE_CATS:
        return "rates"
    if c in DOC_CATS:
        return "docs"
    if c in DEAL_CATS:
        return "deals"
    return "news"


# ---------------------------------------------------------------- major: open a review issue
def already_reviewed(s):
    """True if any review issue (open or closed) already covers this story or the same headline."""
    try:
        for it in gh("GET", "/issues", params={"state": "all", "per_page": 100, "sort": "created", "direction": "desc"}):
            if not (it.get("title") or "").startswith(("Major alert:", "TEST Major alert:")):
                continue
            b = it.get("body") or ""
            if f'"story": "{s["id"]}"' in b or norm(s["title"])[:50] in norm(b):
                return True
    except Exception as e:
        print("  couldn't check earlier review issues:", e, file=sys.stderr)
    return False


def open_review(s, test=False, copy=None):
    if not test and already_reviewed(s):
        print("  review already exists for:", s["title"][:70]); return
    auto = now_et() + dt.timedelta(hours=AUTO_SEND_HOURS)
    if quiet(auto) and not test:
        auto = next_morning(auto)
    c = copy or {"t": short(s["title"], 50), "m": short(s.get("plain") or s.get("sum") or "", 110)}
    title, msg, url = c["t"], c["m"], story_link(s, big=True)
    body = ((f"@{OWNER} **TEST ALERT.** This is a practice run of the approval flow. Replying `send` pushes it to "
             f"**your phone only**, never to readers.\n\n") if test else "") + (f"@{OWNER} a major alert is ready. **Nothing has gone to readers yet.**\n\n"
            f"### Title\n{title}\n\n### Message\n{msg}\n\n### Link\n{url}\n\n---\n"
            f"- Reply **`send`** to push it to everyone now.\n"
            f"- Reply **`hold`** to stop it (closing the issue does the same).\n"
            f"- Want different wording? Edit the Title and Message above (··· menu > Edit), then reply `send`.\n"
            f"- Reply **`send docs`** to also add the carrier documents from this story to the Docs tab "
            f"(add a carrier to choose where they go, e.g. `send docs ontrac`).\n\n"
            f"If you don't reply, it goes out automatically at **{auto.strftime('%-I:%M %p ET, %a %b %-d')}**.\n\n"
            f"<!-- pp-alert {json.dumps({'auto_at': auto.isoformat(), 'story': s['id'], 'test': test, 'k': 'story:' + norm(s['title'])})} -->")
    issue = gh("POST", "/issues", json={"title": f"{'TEST ' if test else ''}Major alert: {title}", "body": body, "labels": ["alert-review"]})
    link = issue.get("html_url", f"https://github.com/{REPO}/issues")
    if not ADMIN_IDS:
        print("  PP_ADMIN_IDS is empty, so no approval push to your phone (check the secret's name and that it's under Actions > Secrets)")
    if ADMIN_IDS:
        # short and plain: what it is, and when it goes out on its own
        push("Test: approve this alert?" if test else "Approve this alert?",
             f"{title} · Reply send on GitHub to get the reader version" if test else
             f"{title} · Sends {auto.strftime('%-I:%M %p').lower()} unless you hold it",
             link, ids=ADMIN_IDS, ttl=6 * 3600, key=None if test else "review:" + s["id"])
    ntfy("Parcel Pigeon: approve alert?", title, link)
    print("  review issue:", link)


def parse_issue(body):
    def sec(name):
        m = re.search(r"###\s*" + name + r"\s*\n(.*?)(?=\n###|\n---|\Z)", body or "", re.S | re.I)
        return m.group(1).strip() if m else ""
    meta = re.search(r"<!-- pp-alert (\{.*?\}) -->", body or "", re.S)
    return sec("Title"), sec("Message"), sec("Link").split()[0] if sec("Link") else SITE, json.loads(meta.group(1)) if meta else {}


def review():
    global SENT
    if not GH:
        print("GITHUB_TOKEN not set"); return
    st = load("alerts_state.json", None) or {}
    SENT = st.setdefault("sent", [])
    try:
        _review()
    finally:
        cur = load("alerts_state.json", None) or {}
        cur["sent"] = list(dict.fromkeys(cur.get("sent", []) + st["sent"]))[-4000:]
        save("alerts_state.json", cur)


def _review():
    issues = gh("GET", "/issues", params={"state": "open", "labels": "alert-review", "per_page": 30})
    for it in issues:
        if it.get("pull_request") or (it.get("user") or {}).get("login") not in ("github-actions[bot]", OWNER):
            continue
        n = it["number"]
        title, msg, url, meta = parse_issue(it.get("body"))
        decision, docs, said = None, None, set()
        comments = gh("GET", f"/issues/{n}/comments", params={"per_page": 100})
        for c in comments:
            if (c.get("user") or {}).get("login") == "github-actions[bot]":
                said.add((c.get("body") or "")[:40])
            if c.get("author_association") != "OWNER" and (c.get("user") or {}).get("login") != OWNER:
                continue                 # public repo: only the owner's replies count
            w = (c.get("body") or "").strip().lower()
            if re.match(r"^(send|approve|approved|yes|go|run|publish|ok|okay)\s+now\b", w):
                decision = "now"
            elif re.match(r"^(send|approve|approved|yes|go|run|publish|ok|okay)\b", w):
                decision = "send"
            elif re.match(r"^(hold|no|stop|skip|cancel)\b", w):
                decision = "hold"
            if re.search(r"\b(docs?|documents?)\b", w):
                docs = doc_carrier(w) or ""          # "" = use the story's own carrier
        def note_once(body):
            if body[:40] not in said:
                gh("POST", f"/issues/{n}/comments", json={"body": body}); said.add(body[:40])
        extra = ["add-docs"] if docs is not None and not meta.get("test") else []
        docs_note = (f" Adding its carrier documents to the Docs tab{' under ' + docs if docs else ''} on the next "
                     f"hourly check; I'll comment here when they're in.") if extra else ""
        auto = dt.datetime.fromisoformat(meta["auto_at"]) if meta.get("auto_at") else None
        if decision is None and auto and now_et() >= auto and not quiet():
            decision = "auto"
        if decision is None:
            print(f"#{n} waiting" + (f" (auto at {auto:%-I:%M %p ET})" if auto else ""))
            continue
        if decision == "hold":
            gh("POST", f"/issues/{n}/comments", json={"body": "Held. Nothing was sent to readers." + docs_note})
            gh("PATCH", f"/issues/{n}", json={"state": "closed", "labels": ["alert-held"] + extra})
            print(f"#{n} held"); continue
        test = bool(meta.get("test"))
        if test and not ADMIN_IDS:
            note_once("Test not sent: add your Device ID as the PP_ADMIN_IDS secret (Settings > Secrets and variables > Actions), "
                      "then reply `send` again.")
            continue
        r = push(title, msg, url, ids=ADMIN_IDS if test else None, ttl=2 * 86400,
                 key=None if test else (meta.get("k") or "major:" + str(meta.get("story"))))
        if r is None:
            note_once("Couldn't send: the OneSignal keys aren't set in GitHub Secrets yet. Add them and reply `send` again.")
            continue
        nobody = "not subscribed" in json.dumps(r.get("errors") or "")
        ok = bool(r.get("id")) or nobody
        note = (f"Test sent to your phone only, exactly as readers would see it: **{title}** / {msg} (OneSignal id `{r.get('id')}`). "
                "If it didn't arrive, check that alerts are on in the app and that PP_ADMIN_IDS matches the Device ID shown there." if test and ok else
                "Sent to everyone with alerts on." if decision in ("send", "now") else
                f"Sent automatically (no reply within {AUTO_SEND_HOURS:g} hours).") if ok else \
               f"OneSignal didn't send it: `{json.dumps(r.get('errors') or r)[:300]}`"
        if ok:
            gh("POST", f"/issues/{n}/comments", json={"body": note + docs_note})
            gh("PATCH", f"/issues/{n}", json={"state": "closed", "labels": ["alert-sent"] + extra})
        else:
            note_once(note)
        print(f"#{n} {decision}: {note}")



# ---------------------------------------------------------------- "send docs": add a story's carrier documents to the Docs tab
DOC_TYPES = ["Rate guide", "Service guide", "GRI notice", "Surcharges & fees", "Peak", "Fuel", "Zones & DAS",
             "Special program", "Terms", "Regulatory filing"]
DOC_WORDS = r"rate|guide|surcharge|fee|notice|tariff|terms|zone|das|fuel|peak|accessorial|service|pricing|price|filing|schedule|\.pdf"


def doc_carriers():
    names = {d.get("c") for d in load("docs.json", []) if d.get("c")} | {"UPS", "FedEx", "USPS", "Amazon", "OnTrac", "DHL", "LSO", "Veho", "Spee-Dee", "GLS US"}
    return sorted(names - {"Reports"}, key=len, reverse=True)


def doc_carrier(text):
    t = re.sub(r"[^a-z0-9]", "", text.lower())
    for c in doc_carriers():
        if re.sub(r"[^a-z0-9]", "", c.lower()) in t:
            return c
    return None


def page_links(url):
    try:
        html = get(url, timeout=25).text
    except Exception as e:
        print("  couldn't read", url, e); return []
    out = []
    for href, text in re.findall(r'<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        u = canon(urljoin(url, href.strip()))
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:120]
        if u.startswith("http") and is_primary(u) and re.search(DOC_WORDS, (u + " " + t).lower()):
            out.append({"u": u, "t": t})
    return out


def find_docs(story, carrier):
    cands, seen = [], set()
    for sx in story.get("srcs") or [{"url": story.get("url")}]:
        u = sx.get("url")
        if not u:
            continue
        if is_primary(u) and u not in seen:
            cands.append({"u": u, "t": sx.get("src") or story["title"]}); seen.add(u)
        for l in page_links(u):
            if l["u"] not in seen:
                cands.append(l); seen.add(l["u"])
    cands = cands[:80]
    if not cands:
        return []
    picks = []
    try:
        listing = "\n".join(f"{i}. {c['t']} | {c['u']}" for i, c in enumerate(cands))
        reply = claude(MODEL_FAST, "You pick official carrier documents for a shipping-document library. Keep only documents a "
                       "shipper would file: rate guides, service guides, GRI or price-change notices, surcharge and fee tables, "
                       "peak notices, fuel tables, zone or DAS lists, terms and conditions, regulatory filings. Skip home pages, "
                       "login pages, tracking, news articles, careers, press-release lists and anything not from the carrier, USPS or a regulator. "
                       f"Return JSON: a list of at most 8 objects {{\"i\": index, \"t\": one of {json.dumps(DOC_TYPES)}, "
                       "\"n\": \"the document's own title, with year if known\", \"y\": year or null, \"eff\": \"YYYY-MM-DD\" or null}. [] if none.",
                       f"Story: {story['title']}\nCarrier: {carrier}\n\nLinks:\n{listing}", max_tokens=1200)
        for p in parse_json(reply) or []:
            if isinstance(p, dict) and isinstance(p.get("i"), int) and 0 <= p["i"] < len(cands):
                picks.append({**p, "u": cands[p["i"]]["u"]})
    except Exception as e:
        print("  doc picking fell back to simple rules:", e)
        picks = [{"u": c["u"], "t": "Special program", "n": c["t"] or story["title"]} for c in cands if c["u"].lower().endswith(".pdf")][:8]
    return picks


DOMAIN_CARRIER = {"ups.com": "UPS", "fedex.com": "FedEx", "usps.com": "USPS", "prc.gov": "USPS", "uspsoig.gov": "USPS",
                  "dhl.com": "DHL", "ontrac.com": "OnTrac", "amazon.com": "Amazon", "aboutamazon.com": "Amazon",
                  "lso.com": "LSO", "gls-us.com": "GLS US", "speedeedelivery.com": "Spee-Dee", "shipveho.com": "Veho",
                  "uniuni.com": "UniUni", "gofo.com": "GOFO", "bettertrucks.com": "Better Trucks", "jitsu.com": "Jitsu",
                  "cdldelivery.com": "CDL"}
HARVEST_PER_RUN = 6          # stories checked for documents each run (keeps runs quick)
BACKFILL_DAYS, BACKFILL_MAX = 45, 40


def carrier_of_url(u):
    host = re.sub(r"^https?://", "", u or "").split("/")[0].lower()
    for d, c in DOMAIN_CARRIER.items():
        if host == d or host.endswith("." + d):
            return c
    return None


def harvest(story, lib, carrier=None, editor=False):
    """Add the official documents linked from a story's sources to the library. Returns the new entries."""
    have = known_doc_urls(lib)
    fallback = carrier or next((c for c in story.get("c") or [] if c not in ("Industry", "Regional")), None)
    added = []
    for p in find_docs(story, carrier or fallback or "the carrier named in each link"):
        p["u"] = canon(p["u"])
        if p["u"] in have:
            continue
        c = carrier or carrier_of_url(p["u"]) or fallback
        if not c:
            continue
        d = {"c": c, "t": p.get("t") if p.get("t") in DOC_TYPES else "Special program", "n": short(p.get("n") or story["title"], 120),
             "y": p.get("y"), "eff": p.get("eff"), "u": p["u"], "d": f"Found with: {story['title']}",
             "cur": True, "added": now_et().date().isoformat(),
             "why": {"how": "editor" if editor else "story", "story": story.get("id"), "title": story.get("title"),
                     "when": now_et().date().isoformat()}}
        lib.append(d); have.add(p["u"]); added.append(d)
    return added


def worth_harvesting(st):
    return any(is_primary(x.get("url")) for x in st.get("srcs") or []) or st.get("cat") in PRICE_CATS | DOC_CATS


def auto_harvest(state):
    """Every new story with a carrier or regulator source gets its documents collected, plus a one-time sweep of recent ones."""
    news = load("news.json", [])
    lib = load("docs.json", [])
    done = set(state.setdefault("harvested", []))
    since = (now_et().date() - dt.timedelta(days=BACKFILL_DAYS if not state.get("backfilled") else FRESH_DAYS + 1)).isoformat()
    todo = [st for st in news if st.get("id") not in done and (st.get("date") or "") >= since and worth_harvesting(st)]
    todo.sort(key=lambda st: (st.get("date") or "", int(st.get("lvl") or 1)), reverse=True)   # newest first
    limit = BACKFILL_MAX if not state.get("backfilled") else HARVEST_PER_RUN
    total = 0
    for st in todo[:limit]:
        try:
            new = harvest(st, lib)
            total += len(new)
            for d in new:
                print(f"  doc added: [{d['c']}] {d['n']}")
        except Exception as e:
            print("  harvest failed for", st.get("id"), e, file=sys.stderr)
        done.add(st["id"])
    if not state.get("backfilled"):
        state["backfilled"] = True
    state["harvested"] = list(done)[-4000:]
    if total:
        save("docs.json", lib)
    print(f"docs: checked {min(len(todo), limit)} stories, added {total} documents")


def process_doc_requests():
    if not GH:
        return
    try:
        reqs = gh("GET", "/issues", params={"state": "all", "labels": "add-docs", "per_page": 20})
    except Exception as e:
        print("doc requests:", e); return
    if not reqs:
        return
    news = {s["id"]: s for s in load("news.json", [])}
    lib = load("docs.json", [])
    for it in reqs:
        n = it["number"]
        _, _, _, meta = parse_issue(it.get("body"))
        carrier = None
        for c in gh("GET", f"/issues/{n}/comments", params={"per_page": 100}):
            if c.get("author_association") == "OWNER" or (c.get("user") or {}).get("login") == OWNER:
                w = (c.get("body") or "").lower()
                if re.search(r"\b(docs?|documents?)\b", w):
                    carrier = doc_carrier(w) or carrier
        story = news.get(meta.get("story"))
        labels = [l["name"] for l in it.get("labels", []) if l["name"] != "add-docs"]
        if not story:
            body = "Couldn't add documents: that story isn't in the live news anymore."
        else:
            carrier = carrier or next((c for c in story.get("c") or [] if c not in ("Industry", "Regional")), None)
            if not carrier:
                body = "Which carrier should these go under? Reply `docs ups` (or another carrier) and I'll add them."
            else:
                added = harvest(story, lib, carrier, editor=True)
                body = (f"Added {len(added)} document{'s' if len(added) != 1 else ''} to Docs under **{carrier}** "
                        f"(live with this update):\n" + "\n".join(f"- [{d['n']}]({d['u']}) · {d['t']}" for d in added)) if added else \
                       f"Checked the story's sources but found no new {carrier} documents to add (anything there is already in Docs)."
                labels.append("docs-added")
        gh("POST", f"/issues/{n}/comments", json={"body": body})
        gh("PATCH", f"/issues/{n}", json={"labels": labels})
        print(f"#{n} docs: {body.splitlines()[0]}")
    save("docs.json", lib)

# ---------------------------------------------------------------- regular events
def fuel_value(v):
    if isinstance(v, dict):
        v = v.get("ground", next(iter(v.values()), None))
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    try:
        return float(v)
    except Exception:
        return None


def collect(state, today):
    """New events since the last run: (stories, clock reminders, fuel moves). Marks nothing; caller does."""
    news = load("news.json", [])
    fresh = (today - dt.timedelta(days=FRESH_DAYS)).isoformat()
    seen_t = set(state.get("titles") or [])
    stories = [s for s in news if s.get("id") and s["id"] not in state["stories"] and (s.get("date") or "") >= fresh
               and norm(s.get("title"))[:60] not in seen_t]
    # never alert twice on one event, even if it was written up again in different words
    recent = state.setdefault("recent", [])
    out = []
    for s in stories:
        if any(r.get("id") != s["id"] and same_event(s, r) for r in recent + out):
            state["stories"].append(s["id"]); continue
        out.append(s)
    stories = out
    have = {r.get("id") for r in recent}
    state["recent"] = (recent + [{k: s.get(k) for k in ("id", "title", "date", "c", "url", "srcs")} for s in stories if s["id"] not in have])[-150:]
    seed = load("seed.json", {})
    rem = []
    for e in seed.get("clock") or []:
        try:
            d = dt.date.fromisoformat(e["d"])
        except Exception:
            continue
        left = (d - today).days
        if left in (7, 1) and e.get("imp") == "up":
            key = f"{e.get('id')}:{left}"
            if key not in state["clock"]:
                rem.append((key, e, left))
    moves = []
    fuel = load("fuel.json", {})
    for c, hist in (fuel.get("hist") or {}).items():
        if c not in ("UPS", "FedEx", "OnTrac"):
            continue
        keys = sorted(hist)
        if len(keys) < 2 or state["fuel"].get(c) == keys[-1]:
            continue
        a, b = fuel_value(hist[keys[-2]]), fuel_value(hist[keys[-1]])
        if a is None or b is None:
            state["fuel"][c] = keys[-1]; continue
        moves.append((c, keys[-1], a, b))
    return stories, rem, moves


def count_today(state, n=1):
    d = now_et().date().isoformat()
    day = state.setdefault("day", {})
    if day.get("d") != d:
        day.clear(); day.update({"d": d, "n": 0})
    day["n"] += n
    return day["n"]


def union_mask(items):
    """Carriers across several items, as one reader mask; None (everyone) if any item is industry-wide."""
    m = 0
    for q in items:
        if q.get("mask") is None:
            return None
        m |= q["mask"]
    return m or None


def send_queued(state):
    """Separate pushes for the most important queued items: MAX_PER_RUN per run, SPACING_MIN apart, MAX_PER_DAY a day.
    Overnight they wait for morning. Returns how many pushes were sent or scheduled."""
    sent = 0
    fq = state.get("fuelq") or {}
    if quiet():
        return 0
    if fq:
        parts = [f"{c} {b:g}% ({'+' if b > a else '−'}{abs(b - a):g})" for c, (k, a, b) in sorted(fq.items())]
        mv = max(round(abs(b - a), 2) for k, a, b in fq.values())
        bits = 0
        for c in fq:
            bits |= BITS.get(c, 0)
        push("Ground fuel this week", ", ".join(parts), SITE + "#fuel",
             audience([{"field": "tag", "key": "ft", "relation": ">", "value": "0"},
                       {"field": "tag", "key": "ft", "relation": "<", "value": str(mv + 0.001)}], bits or None),
             key="fuel:" + ",".join(f"{c}:{v[0]}" for c, v in sorted(fq.items())))
        state["fuelq"] = {}
        sent += 1
    sent_times = []
    cutoff = now_et() - dt.timedelta(hours=QUEUE_HOURS)
    queue = [q for q in state.get("queue") or [] if q["key"] not in SENT
             and dt.datetime.fromisoformat(q.get("at") or now_et().isoformat()) >= cutoff]
    queue.sort(key=lambda q: (not q.get("big"), -int(q.get("lvl") or 0), q["kind"] != "story", q.get("at") or ""))
    room = max(0, min(MAX_PER_RUN, MAX_PER_DAY - count_today(state, 0)))
    # alerts.py runs hourly (watch) and every two hours (update): keep regular pushes about an hour apart across runs
    last = state.get("last_push")
    if last and queue and not queue[0].get("big") and now_et() < dt.datetime.fromisoformat(last) + dt.timedelta(minutes=MIN_GAP_MIN):
        state["queue"] = queue
        print(f"  last alert went out under {MIN_GAP_MIN} minutes ago; {len(queue)} wait for the next run")
        return sent
    if not room or not queue:
        pass
    elif len(queue) <= 2:
        # a quiet run: each item on its own, spaced out
        for n, q in enumerate(queue[:room]):
            after = now_et() + dt.timedelta(minutes=SPACING_MIN * n) if n else None
            if after and quiet(after):
                break                                # don't schedule into the night; it goes in the morning
            extra = [{"field": "tag", "key": TOPIC_TAG[q["topic"]], "relation": "=", "value": "1"}]
            r = push(q["t"], q["m"], q["url"], audience(extra, q.get("mask")), ttl=2 * 86400 if q.get("big") else 86400, key=q["key"], after=after)
            if r is not None:
                count_today(state); sent += 1; sent_times.append(after or now_et())
    else:
        # a busy run: the biggest story gets its own alert (if it's real news), everything else is one roll-up
        lead = queue[0] if (queue[0].get("big") or int(queue[0].get("lvl") or 0) >= 2) else None
        rest = queue[1:] if lead else queue
        if lead:
            extra = [{"field": "tag", "key": TOPIC_TAG[lead["topic"]], "relation": "=", "value": "1"}]
            r = push(lead["t"], lead["m"], lead["url"], audience(extra, lead.get("mask")), ttl=2 * 86400 if lead.get("big") else 86400, key=lead["key"])
            if r is not None:
                count_today(state); sent += 1; sent_times.append(now_et())
        if rest and count_today(state, 0) < MAX_PER_DAY and (not lead or room > 1):
            words = "stories" if all(q["kind"] == "story" for q in rest) else "updates"
            r = push(f"{len(rest)} {'more' if lead else 'new'} parcel {words}", " · ".join(q["t"] for q in rest[:3]) + (" …" if len(rest) > 3 else ""),
                     SITE + "#news", audience([], union_mask(rest)) or None, key="more:" + ",".join(sorted(q["key"] for q in rest)),
                     after=now_et() + dt.timedelta(minutes=SPACING_MIN) if lead and not quiet(now_et() + dt.timedelta(minutes=SPACING_MIN)) else None)
            if r is not None:
                SENT.extend(q["key"] for q in rest); count_today(state); sent += 1
                sent_times.append(now_et() + dt.timedelta(minutes=SPACING_MIN) if lead else now_et())
    state["queue"] = [q for q in queue if q["key"] not in SENT]
    if sent_times:
        state["last_push"] = max(sent_times).isoformat()
    if len(state["queue"]) > 0:
        print(f"  {len(state['queue'])} alert(s) wait for the next run")
    return sent


def run():
    global SENT
    try:
        import players                      # research new companies before alerting on them (3 per run keeps cost low)
        sys.argv = [sys.argv[0], "--max", "3"]
        players.main()
    except Exception as e:
        print("player research failed:", e, file=sys.stderr)
    try:
        import players as _pl
        _pl.backfill_sites(8)                # websites for companies already on the map, so their logos can be found
    except Exception as e:
        print("site lookup failed:", e, file=sys.stderr)
    try:
        process_doc_requests()
    except Exception as e:
        print("doc requests failed:", e, file=sys.stderr)
    state = load("alerts_state.json", None)
    today = now_et().date()
    if APP_ID:
        save("push.json", {"appId": APP_ID})
    first = state is None
    state = state or {}
    for k, d in (("stories", []), ("clock", []), ("fuel", {}), ("players", []), ("sent", []), ("titles", [])):
        state.setdefault(k, d)
    SENT = state["sent"]
    try:
        auto_harvest(state)
    except Exception as e:
        print("document harvest failed:", e, file=sys.stderr)
    stories, rem, moves = collect(state, today)
    if first:
        # first run: remember what's already there so readers don't get a backlog
        state["stories"] += [s["id"] for s in stories]
        state["clock"] += [k for k, _, _ in rem]
        for c, k, _, _ in moves:
            state["fuel"][c] = k
        state["players"] = [p["id"] for p in load("players.json", {}).get("players", [])]
        state["titles"] += [norm(s.get("title"))[:60] for s in stories]
        save("alerts_state.json", state)
        print("alerts: first run, recorded", len(stories), "stories as already seen"); return

    # major stories: review issue for the editor (any hour; the issue waits). Approved ones go out right away.
    majors = sorted([s for s in stories if is_major(s)], key=lambda s: -int(s.get("lvl") or 1))[:MAX_MAJOR_PER_RUN]
    approved = set(load("approved.json", []))
    copy = push_copy([s for s in stories][:MAX_REGULAR_SENDS + MAX_MAJOR_PER_RUN], state)
    queue = state.setdefault("queue", [])
    queued = {q.get("key") for q in queue}
    def enqueue(item):
        if item["key"] not in queued and item["key"] not in SENT:
            queue.append(item); queued.add(item["key"])
    def story_item(s, big=False):
        c = copy.get(s["id"]) or push_copy([s], state)[s["id"]]
        th = (load("threads.json", {}).get(s.get("thread") or "") or {}) if s.get("upd") else {}
        m = f"Update {s['upd']} · {th['n']}: {c['m']}" if th.get("n") else c["m"]
        return {"kind": "story", "key": "story:" + norm(s["title"]), "id": s["id"], "t": c["t"], "m": m, "big": big, "at": now_et().isoformat(),
                "lvl": int(s.get("lvl") or 1), "topic": topic_of(s), "mask": mask_of(s.get("c")), "url": story_link(s, big)}
    def seen(s):
        state["stories"].append(s["id"]); state["titles"].append(norm(s.get("title"))[:60])
    for s in majors:
        try:
            if s["id"] in approved:
                # you already OK'd this story with `run`, so it goes out now (or first thing in the morning)
                if quiet():
                    enqueue(story_item(s, big=True))
                else:
                    it = story_item(s, big=True)
                    push(it["t"], it["m"], it["url"], ttl=2 * 86400, key=it["key"]); count_today(state)
            else:
                open_review(s, copy=copy.get(s["id"]))
            seen(s)
        except Exception as e:
            print("review issue failed:", e, file=sys.stderr)
    major_ids = {s["id"] for s in majors}
    for s in stories:
        if s["id"] not in major_ids:
            enqueue(story_item(s)); seen(s)
    # rate clock reminders: 7 days and 1 day before a dated increase
    for key, e, left in rem:
        when = "tomorrow" if left == 1 else "in 7 days"
        enqueue({"kind": "clock", "key": "clock:" + key, "at": now_et().isoformat(), "t": f"{short(e.get('c') or 'Carrier', 24)}: starts {when}", "m": e.get("w", ""),
                 "lvl": 2, "topic": "rates", "mask": mask_of(carriers_in(e.get("c"))), "url": SITE + "#clock"})
        state["clock"].append(key)
    # fuel: keep the latest weekly move per carrier until it goes out (it waits through quiet hours)
    fq = state.setdefault("fuelq", {})
    for c, k, a, b in moves:
        state["fuel"][c] = k
        if round(abs(b - a), 2) > 0:
            fq[c] = [k, a, b]
    # new companies on the market map (researched and confirmed by players.py)
    newp = [p for p in load("players.json", {}).get("players", []) if p.get("enriched") and not p.get("pending")
            and p["id"] not in state["players"]]
    for p in newp:
        enqueue({"kind": "player", "key": "player:" + p["id"], "at": now_et().isoformat(), "t": f"New on the map: {p['n']}", "m": p.get("s") or "",
                 "lvl": 0, "topic": "deals", "mask": None, "url": SITE + "#mna"})
    state["players"] = (state["players"] + [p["id"] for p in newp])[-3000:]
    sends = send_queued(state)
    try:
        import media                        # company logos (monthly) and company photos for recent stories
        media.logos(40)
        media.photos(6)
    except Exception as e:
        print("media failed:", e, file=sys.stderr)
    try:
        import archive                      # saved copies of carrier PDFs and spreadsheets for one-tap download
        archive.main(6)
    except Exception as e:
        print("archive failed:", e, file=sys.stderr)
    try:
        import guides                       # refresh Coop's reference shelf (local, no API cost)
        guides.main()
    except Exception as e:
        print("guides failed:", e, file=sys.stderr)
    state["stories"] = state["stories"][-3000:]
    state["titles"] = state["titles"][-3000:]
    state["sent"] = SENT[-4000:]
    state["clock"] = state["clock"][-500:]
    save("alerts_state.json", state)
    print(f"alerts: {len(majors)} for review, {len(state.get('queue') or [])} waiting for the next run, {sends} pushes sent")


def test_alert():
    """Open a practice review issue. Approving it pushes to the editor's phone only."""
    open_review({"id": "demo", "title": "UPS adds a $1.25 test surcharge (practice alert)",
                 "plain": "This is a test of Parcel Pigeon's approval flow."}, test=True,
                copy={"t": "UPS adds $1.25 test surcharge", "m": "Practice alert. This is exactly how a story alert looks to readers."})


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_alert()
    elif "--review" in sys.argv:
        review()
    else:
        run()
