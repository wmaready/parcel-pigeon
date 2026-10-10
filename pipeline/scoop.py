"""Find stories nobody else has reported yet, and notify.

is_covered(): searches Google News for the event over the last few days and returns the trade or business outlets
that already ran it. If none have, the story is a potential first-to-report ("scoop").
notify(): opens a GitHub issue (GitHub mobile push) and, if NTFY_TOPIC is set, sends a free phone push via ntfy.sh.
"""
import os, re, urllib.parse
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
