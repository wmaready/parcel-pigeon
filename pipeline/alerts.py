"""Phone alerts for Parcel Pigeon (web push through OneSignal).

Two lanes:
  Regular  sent live after each run, filtered by each reader's own settings in the app
           (carriers, topics, fuel threshold). Held overnight (9 p.m. to 7 a.m. Eastern) and sent in the morning.
  Major    goes to the editor first: a GitHub issue (GitHub emails it) plus a push to the editor's own phone.
           Reply "send" on the issue to push it to everyone, "hold" to stop it. With no reply it goes out
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
from zoneinfo import ZoneInfo

import requests

from common import load, save

ET = ZoneInfo("America/New_York")
AUTO_SEND_HOURS = float(os.environ.get("PP_AUTO_SEND_HOURS") or 2)
QUIET_START, QUIET_END = 21, 7          # Eastern; regular and automatic alerts wait for morning
MAX_REGULAR_SENDS = 6                    # per run, across all topics
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


def push(heading, body, url, filters=None, ids=None, ttl=86400):
    if not (APP_ID and API_KEY):
        print(f"  (push skipped, OneSignal keys not set) {heading}: {body}")
        return None
    msg = {"app_id": APP_ID, "isAnyWeb": True, "headings": {"en": short(heading, 64)}, "contents": {"en": short(body, 180)},
           "url": url, "chrome_web_icon": ICON, "firefox_icon": ICON, "ttl": ttl}
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


def story_link(s):
    return f"{SITE}#alert={s['id']}"


# ---------------------------------------------------------------- what counts as major
def is_major(s):
    cs = set(s.get("c") or [])
    lvl = int(s.get("lvl") or 1)
    if lvl >= 3:
        return True
    if s.get("cat") in PRICE_CATS and s.get("imp") == "up" and lvl >= 2 and cs & BIG4:
        return True
    if s.get("cat") in DEAL_CATS and lvl >= 2 and cs & BIG4:
        return True
    return False


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
def open_review(s, test=False):
    auto = now_et() + dt.timedelta(hours=AUTO_SEND_HOURS)
    if quiet(auto) and not test:
        auto = next_morning(auto)
    title, msg, url = short(s["title"], 64), short(s.get("plain") or s.get("sum") or "", 180), story_link(s)
    body = ((f"@{OWNER} **TEST ALERT.** This is a practice run of the approval flow. Replying `send` pushes it to "
             f"**your phone only**, never to readers.\n\n") if test else "") + (f"@{OWNER} a major alert is ready. **Nothing has gone to readers yet.**\n\n"
            f"### Title\n{title}\n\n### Message\n{msg}\n\n### Link\n{url}\n\n---\n"
            f"- Reply **`send`** to push it to everyone now.\n"
            f"- Reply **`hold`** to stop it (closing the issue does the same).\n"
            f"- Want different wording? Edit the Title and Message above (··· menu > Edit), then reply `send`.\n\n"
            f"If you don't reply, it goes out automatically at **{auto.strftime('%-I:%M %p ET, %a %b %-d')}**.\n\n"
            f"<!-- pp-alert {json.dumps({'auto_at': auto.isoformat(), 'story': s['id'], 'test': test})} -->")
    issue = gh("POST", "/issues", json={"title": f"{'TEST ' if test else ''}Major alert: {title}", "body": body, "labels": ["alert-review"]})
    link = issue.get("html_url", f"https://github.com/{REPO}/issues")
    if ADMIN_IDS:
        push(("[Test] " if test else "") + "Approve alert? " + title,
             "Tap to review. Test only: approving sends it to your phone, not readers." if test else
             f"Tap to review. Sends to everyone automatically in {AUTO_SEND_HOURS:g} h unless you hold it.",
             link, ids=ADMIN_IDS, ttl=6 * 3600)
    ntfy("Parcel Pigeon: approve alert?", title, link)
    print("  review issue:", link)


def parse_issue(body):
    def sec(name):
        m = re.search(r"###\s*" + name + r"\s*\n(.*?)(?=\n###|\n---|\Z)", body or "", re.S | re.I)
        return m.group(1).strip() if m else ""
    meta = re.search(r"<!-- pp-alert (\{.*?\}) -->", body or "", re.S)
    return sec("Title"), sec("Message"), sec("Link").split()[0] if sec("Link") else SITE, json.loads(meta.group(1)) if meta else {}


def review():
    if not GH:
        print("GITHUB_TOKEN not set"); return
    issues = gh("GET", "/issues", params={"state": "open", "labels": "alert-review", "per_page": 30})
    for it in issues:
        if it.get("pull_request") or (it.get("user") or {}).get("login") not in ("github-actions[bot]", OWNER):
            continue
        n = it["number"]
        title, msg, url, meta = parse_issue(it.get("body"))
        decision = None
        for c in gh("GET", f"/issues/{n}/comments", params={"per_page": 100}):
            if c.get("author_association") != "OWNER" and (c.get("user") or {}).get("login") != OWNER:
                continue                 # public repo: only the owner's replies count
            w = (c.get("body") or "").strip().lower()
            if re.match(r"^(send|approve|approved|yes|go)\b", w):
                decision = "send"
            elif re.match(r"^(hold|no|stop|skip|cancel)\b", w):
                decision = "hold"
        auto = dt.datetime.fromisoformat(meta["auto_at"]) if meta.get("auto_at") else None
        if decision is None and auto and now_et() >= auto and not quiet():
            decision = "auto"
        if decision is None:
            print(f"#{n} waiting" + (f" (auto at {auto:%-I:%M %p ET})" if auto else ""))
            continue
        if decision == "hold":
            gh("POST", f"/issues/{n}/comments", json={"body": "Held. Nothing was sent to readers."})
            gh("PATCH", f"/issues/{n}", json={"state": "closed", "labels": ["alert-held"]})
            print(f"#{n} held"); continue
        test = bool(meta.get("test"))
        if test and not ADMIN_IDS:
            gh("POST", f"/issues/{n}/comments", json={"body": "Test not sent: add your Device ID as the PP_ADMIN_IDS secret first."})
            continue
        r = push(("[Test] " if test else "") + title, msg, url, ids=ADMIN_IDS if test else None, ttl=2 * 86400)
        if r is None:
            gh("POST", f"/issues/{n}/comments", json={"body": "Couldn't send: the OneSignal keys aren't set in GitHub Secrets yet. "
                                                              "Add them and reply `send` again."})
            continue
        ok = bool(r.get("id"))
        note = ("Test sent to your phone only. The approval flow works." if test and ok else
                "Sent to everyone with alerts on." if decision == "send" else
                f"Sent automatically (no reply within {AUTO_SEND_HOURS:g} hours).") if ok else \
               f"OneSignal didn't send it: `{json.dumps(r.get('errors') or r)[:300]}`"
        gh("POST", f"/issues/{n}/comments", json={"body": note})
        if ok:
            gh("PATCH", f"/issues/{n}", json={"state": "closed", "labels": ["alert-sent"]})
        print(f"#{n} {decision}: {note}")


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
    stories = [s for s in news if s.get("id") and s["id"] not in state["stories"] and (s.get("date") or "") >= fresh]
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


def run():
    state = load("alerts_state.json", None)
    today = now_et().date()
    if APP_ID:
        save("push.json", {"appId": APP_ID})
    first = state is None
    state = state or {}
    for k, d in (("stories", []), ("clock", []), ("fuel", {})):
        state.setdefault(k, d)
    stories, rem, moves = collect(state, today)
    if first:
        # first run: remember what's already there so readers don't get a backlog
        state["stories"] += [s["id"] for s in stories]
        state["clock"] += [k for k, _, _ in rem]
        for c, k, _, _ in moves:
            state["fuel"][c] = k
        save("alerts_state.json", state)
        print("alerts: first run, recorded", len(stories), "stories as already seen"); return

    # major stories: review issue for the editor (any hour; the issue waits)
    majors = sorted([s for s in stories if is_major(s)], key=lambda s: -int(s.get("lvl") or 1))[:MAX_MAJOR_PER_RUN]
    for s in majors:
        try:
            open_review(s)
            state["stories"].append(s["id"])
        except Exception as e:
            print("review issue failed:", e, file=sys.stderr)
    major_ids = {s["id"] for s in majors}

    if quiet():
        save("alerts_state.json", state)
        print(f"alerts: quiet hours, {len(stories) - len(majors)} regular stories wait for morning"); return

    sends = 0
    # stories, grouped by topic and carriers so each reader gets one push per group
    groups = {}
    for s in stories:
        if s["id"] in major_ids:
            continue
        groups.setdefault((topic_of(s), mask_of(s.get("c"))), []).append(s)
    for (topic, mask), ss in sorted(groups.items(), key=lambda kv: -max(int(x.get("lvl") or 1) for x in kv[1])):
        if sends >= MAX_REGULAR_SENDS:
            break
        ss.sort(key=lambda x: -int(x.get("lvl") or 1))
        who = "/".join(c for c in (ss[0].get("c") or []) if c != "Industry") or "Parcel"
        if len(ss) == 1:
            head, body, url = ss[0]["title"], ss[0].get("plain") or ss[0].get("sum") or "", story_link(ss[0])
        else:
            head = f"{len(ss)} new {who} {TOPIC_WORDS[topic]}"
            body, url = f"{ss[0]['title']} + {len(ss) - 1} more", SITE + "#news"
        push(head, body, url, audience([{"field": "tag", "key": TOPIC_TAG[topic], "relation": "=", "value": "1"}], mask))
        sends += 1
    state["stories"] += [s["id"] for s in stories if s["id"] not in major_ids]

    # rate clock reminders: 7 days and 1 day before a dated increase
    for key, e, left in rem:
        if sends >= MAX_REGULAR_SENDS:
            break
        when = "tomorrow" if left == 1 else "in 7 days"
        push(f"Takes effect {when}: {short(e.get('c') or 'Carrier', 30)}", e.get("w", ""), SITE + "#clock",
             audience([{"field": "tag", "key": "t_rates", "relation": "=", "value": "1"}], mask_of(carriers_in(e.get("c")))))
        state["clock"].append(key); sends += 1

    # fuel: each reader picks a threshold (tag "ft"; 0 = off)
    for c, k, a, b in moves:
        mv = round(abs(b - a), 2)
        state["fuel"][c] = k
        if mv <= 0:
            continue
        push(f"{c} ground fuel {'up' if b > a else 'down'} {mv:g} pts",
             f"{b:g}% for the week of {dt.date.fromisoformat(k[:10]).strftime('%b %-d')} (was {a:g}%).", SITE + "#fuel",
             audience([{"field": "tag", "key": "ft", "relation": ">", "value": "0"},
                       {"field": "tag", "key": "ft", "relation": "<", "value": str(mv + 0.001)}], BITS.get(c)))
        sends += 1

    state["stories"] = state["stories"][-3000:]
    state["clock"] = state["clock"][-500:]
    save("alerts_state.json", state)
    print(f"alerts: {len(majors)} for review, {sends} regular pushes")


def test_alert():
    """Open a practice review issue. Approving it pushes to the editor's phone only."""
    open_review({"id": "demo", "title": "UPS adds a $1.25 test surcharge (practice alert)",
                 "plain": "This is a test of Parcel Pigeon's approval flow. Reply send on the GitHub issue to get it on your phone."}, test=True)


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_alert()
    elif "--review" in sys.argv:
        review()
    else:
        run()
