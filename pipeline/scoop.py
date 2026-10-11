"""Find stories nobody else has reported yet, and notify.

is_covered(): searches Google News for the event over the last few days and returns the trade or business outlets
that already ran it. If none have, the story is a potential first-to-report ("scoop").
notify(): opens a GitHub issue (GitHub mobile push) and, if NTFY_TOPIC is set, sends a free phone push via ntfy.sh.
"""
import json, os, re, urllib.parse
import feedparser, requests
from common import get

# Outlets whose coverage means the story is no longer ours alone.
PRESS = ["freightwaves", "supply chain dive", "supplychaindive", "parcel industry", "dc velocity", "logistics management",
         "logisticsmgmt", "supplychain247", "transport topics", "post & parcel", "post and parcel", "modern retail",
         "reuters", "wall street journal", "wsj", "bloomberg", "cnbc", "associated press", "ap news", "business insider",
         "the loadstar", "journal of commerce", "joc", "retail dive", "trucking dive", "cep research", "practical ecommerce",
         "talking logistics", "inbound logistics", "material handling", "transportation insight"]
STOP = set("the a an and or of to for in on at by with from as is are was be its their new says say said will".split())


def keywords(title, n=6):
    words = [w for w in re.findall(r"[A-Za-z0-9$.%'-]+", title) if w.lower() not in STOP]
    named = [w for w in words if w[0].isupper() or any(c.isdigit() for c in w)]
    return (named + [w for w in words if w not in named])[:n]


def is_covered(title, days=4):
    """Return the list of press outlets that already covered this, or [] if none found."""
    q = " ".join(keywords(title)) + f" when:{days}d"
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(get(url).content)
    except Exception:
        return ["(search failed, treat as covered)"]
    hits = []
    for e in feed.entries[:25]:
        src = ((e.get("source") or {}).get("title") or "").lower()
        if any(p in src for p in PRESS):
            hits.append((e.get("source") or {}).get("title"))
    return sorted(set(hits))


def notify(title, body, labels=("draft", "first-to-report"), link=None):
    out = None
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if token and repo:
        r = requests.post(f"https://api.github.com/repos/{repo}/issues",
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                          json={"title": title, "body": body, "labels": list(labels)}, timeout=30)
        if r.ok:
            out = r.json().get("html_url")
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            requests.post(f"https://ntfy.sh/{topic}", data=title.encode("utf-8"),
                          headers={"Title": "Parcel Pigeon: first to report", "Priority": "high", "Tags": "rotating_light",
                                   **({"Click": out or link} if (out or link) else {})}, timeout=15)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- only ask the editor when it matters
def ask(story, reasons, srcs=None, extra=""):
    """Hold a story off the site and ask the editor: reply `run` to publish, `skip` to drop.
    Used only for big stories nobody else has confirmed, numbers that don't match the sources, or possible off-topic items."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    srcs = srcs or story.get("srcs") or [{"src": story.get("src"), "url": story.get("url")}]
    owner = (repo or "/").split("/")[0]
    body = (f"@{owner} **Worth running?** This one is held off the site until you say so.\n\n"
            + "".join(f"- {r}\n" for r in reasons) + (f"\n{extra}\n" if extra else "") +
            f"\n### Draft story (edit any line, then reply `run`)\nTITLE: {story['title']}\nSUMMARY: {story['sum']}\n"
            f"EFFECT: {story['plain']}\n\nSources: " + ", ".join(x.get("url") or "" for x in srcs) +
            "\n\n- Reply **`run`** to publish it (live on the next hourly update).\n- Reply **`skip`** to drop it.\n"
            "If you don't reply, it stays off the site.\n\n"
            f"<!-- parcelwatch-data\n{json.dumps(story)}\n-->")
    out = None
    if token and repo:
        hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            requests.post(f"https://api.github.com/repos/{repo}/labels", headers=hdr, timeout=15,
                          json={"name": "needs-ok", "color": "FBCA04", "description": "Held story: reply run or skip"})
        except Exception:
            pass
        r = requests.post(f"https://api.github.com/repos/{repo}/issues", headers=hdr, timeout=30,
                          json={"title": f"Worth running? {story['title']}", "body": body, "labels": ["draft", "needs-ok"]})
        if r.ok:
            out = r.json().get("html_url")
    try:
        from alerts import push, ADMIN_IDS
        if ADMIN_IDS and out:
            push("Worth running? " + story["title"], reasons[0], out, ids=ADMIN_IDS, ttl=12 * 3600)
    except Exception as e:
        print("  editor push failed:", e)
    print(f"  ASKING: {story['title']} ({'; '.join(reasons)})")
    return out


def big(story):
    try:
        from alerts import is_major
        return is_major(story)
    except Exception:
        return int(story.get("lvl") or 1) >= 3
