"""The rate clock as a calendar feed (data/rates.ics) that Outlook, Teams, Google Calendar and Apple Calendar subscribe to.

It holds every price change on the rate clock that is in effect now or still to come: one all-day event on the date it
takes effect (spanning the days when carriers stagger it), and one on the date it was announced when a source states it.
Each links back to its story in the app. The entries are the same ones the app shows: the built-in clock (data/seed.json),
dates from live stories (data/news.json) and the auditor's additions (data/audit.json).
Usage: python ratecal.py [--today YYYY-MM-DD]"""
import datetime as dt, re, sys
import common
from common import load, clock_worthy

SITE = "https://wmaready.github.io/parcel-pigeon/"
FEED = "rates.ics"
COST = ("up", "down")            # the feed is for price changes; earnings calls and contract dates stay in the app


def _words(s):
    return set(re.findall(r"[a-z0-9.$%]+", str(s).lower()))


def _sim(a, b):
    A, B = _words(a), _words(b)
    return len(A & B) / max(1, min(len(A), len(B)))


def _cars(c):
    return {x.strip().lower() for x in re.split(r"\s*(?:·|,|/)\s*", str(c or "")) if x.strip()}


# A story's own companies, read the way the app reads them (index.html: mentions, storyCos, ownSet, cleanStory): a date
# line that only names other companies ("FedEx demand fees begin" in a GOFO story) is left off, as the app leaves it off.
LOGO_CAR = {"ups": "ups", "fedex": "fedex", "fdx": "fedex", "usps": "usps", "amazon": "amzship", "amazon shipping": "amzship",
            "amzn": "amazon", "ontrac": "ontrac", "dhl": "dhlexpress", "dhl express": "dhlexpress", "dhl ecommerce": "dhlecom",
            "dhl group": "dhl", "fdxf": "fdxfreight", "fedex freight": "fdxfreight", "dash": "doordash", "pbi": "pitneybowes"}
BIG_TAGS = {"UPS", "FedEx", "USPS", "Amazon", "OnTrac", "DHL"}


def _names(p):
    return [str(n) for n in [p.get("n"), *(p.get("al") or [])] if n]


class Companies:
    def __init__(self, seed):
        P = [p for p in seed.get("players") or [] if isinstance(p, dict) and p.get("id")]
        known = {n.lower() for p in P for n in _names(p)}
        for p in (load("players.json", {}) or {}).get("players") or []:
            if isinstance(p, dict) and p.get("id") and not p.get("pending") and not any(n.lower() in known for n in _names(p)):
                P.append(p)
        self.P = {p["id"]: p for p in P}
        self.pre = [(p["id"], re.compile(r"(^|[^A-Za-z0-9])(" + "|".join(map(re.escape, _names(p))) + r")(?![A-Za-z0-9])"))
                    for p in P if _names(p)]
        self.byname = {n.lower(): p["id"] for p in P for n in _names(p)}

    def mentions(self, t):
        return [i for i, rx in self.pre if rx.search(str(t or ""))]

    def logo_id(self, x):
        k = str(x or "").lower().strip()
        return LOGO_CAR.get(k) or (k if k in self.P else self.byname.get(k))

    def _kin(self, ids):
        roots = set(ids) | {self.P[i]["parent"] for i in ids if self.P.get(i, {}).get("parent")}
        return roots | {q for q, p in self.P.items() if p.get("parent") in roots}

    def own(self, story):
        hd = self.mentions(story.get("title"))
        fam = self._kin(hd) if hd else None
        tags = [c for c in story.get("c") or [] if c not in ("Industry", "Regional")]
        ids = {i for c, i in ((c, self.logo_id(c)) for c in tags) if i and (not fam or c not in BIG_TAGS or i in fam)} | set(hd)
        out = set(ids)
        for i in ids:
            if self.P.get(i, {}).get("parent"):
                out.add(self.P[i]["parent"])
            out |= {q for q, p in self.P.items() if p.get("parent") == i}
        return out

    def clean_dates(self, story):
        own = self.own(story)
        if not own:
            return list(story.get("dates") or [])
        out = []
        for d in story.get("dates") or []:
            if not isinstance(d, dict) or not d.get("w"):
                out.append(d); continue
            keep = [c for c in re.split(r"\s*;\s*", str(d["w"])) if not (self.mentions(c) and not set(self.mentions(c)) & own)]
            if keep:
                out.append({**d, "w": "; ".join(keep)})
        return out


def entries():
    """The rate clock, assembled the way the app assembles it: built-in entries, then story dates (a story date within
    three days of an entry about the same company, with a similar description, joins that entry instead of adding one)."""
    seed = load("seed.json", {}) or {}
    clock = [dict(x) for x in seed.get("clock") or [] if isinstance(x, dict) and x.get("d")]
    stories = {s["id"]: s for s in seed.get("news") or [] if isinstance(s, dict) and s.get("id")}
    dropped = {d if isinstance(d, str) else (d or {}).get("id") for d in load("drop.json", []) or []}
    live = [s for s in load("news.json", []) or [] if isinstance(s, dict) and s.get("id") and s["id"] not in dropped]
    stories.update({s["id"]: s for s in live})
    day = lambda d: dt.date.fromisoformat(d[:10])
    cos = Companies(seed)
    seen = {s.get("url") for s in seed.get("news") or [] if isinstance(s, dict)}
    for s in live:
        if s.get("url") in seen:          # a story the app already carries built in: the app skips its live copy
            continue
        seen |= {x.get("url") for x in s.get("srcs") or [{"url": s.get("url")}] if isinstance(x, dict)}
        for i, d in enumerate(cos.clean_dates(s)):
            if not isinstance(d, dict) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d.get("d") or "")) or not clock_worthy(s, d):
                continue
            cars = {c.lower() for c in s.get("c") or [] if c not in ("Industry", "Regional")}
            near = next((x for x in clock if abs((day(x["d"]) - day(d["d"])).days) <= 3 and (not cars or cars & _cars(x.get("c")))
                         and _sim(x.get("w"), d.get("w")) >= .3), None)
            if near:
                near.setdefault("news", [])
                if s["id"] not in near["news"]:
                    near["news"].append(s["id"])
            else:
                clock.append({"id": f"x{s['id']}{i}", "d": d["d"], "w": d.get("w") or s.get("title"), "imp": d.get("imp") or "up",
                              "c": " · ".join(c for c in s.get("c") or [] if c != "Industry") or "Industry", "news": [s["id"]]})
    audit = load("audit.json", {}) or {}
    for x in audit.get("clock_add") or []:
        if isinstance(x, dict) and x.get("d") and x.get("id") and not any(y["id"] == x["id"] for y in clock):
            clock.append(dict(x))
    for l in audit.get("clock_link") or []:
        y = next((y for y in clock if y["id"] == l.get("clock")), None)
        if y and l.get("story") and l["story"] not in y.setdefault("news", []):
            y["news"].append(l["story"])
    for l in audit.get("clock_unlink") or []:
        y = next((y for y in clock if y["id"] == l.get("clock")), None)
        if y:
            y["news"] = [s for s in y.get("news") or [] if s not in (l.get("stories") or [])]
    for x in clock:
        x["_stories"] = [stories[i] for i in x.get("news") or [] if i in stories]
    return sorted(clock, key=lambda x: x["d"])


def announced(x):
    """The announcement date a source states (the entry's own, or its stories'), only when it came before the change."""
    anns = sorted(a for a in [x.get("ann")] + [s.get("ann") for s in x["_stories"]] if a and re.match(r"^\d{4}-\d{2}-\d{2}$", str(a)))
    return anns[0] if anns and anns[0] < x["d"] else None


def esc(t):
    return str(t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def fold(line):
    """RFC 5545: lines of at most 75 octets, continued on the next line after a single space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8")); cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def nice(d):
    x = dt.date.fromisoformat(d)
    return f"{x.strftime('%b')} {x.day}, {x.year}"


def build(today=None, stamp=None):
    today = today or dt.date.today().isoformat()
    stamp = stamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ev = []
    for x in entries():
        end = x.get("end") or x["d"]
        if x.get("imp") not in COST or x.get("verify") or end < today:
            continue
        link = SITE + (f"#s={x['_stories'][0]['id']}" if x["_stories"] else "")
        ann = announced(x)
        who = str(x.get("c") or "").strip()
        desc = [x.get("note") or "", f"Carriers: {who}" if who else "",
                (f"Takes effect between {nice(x['d'])} and {nice(x['end'])}, depending on the carrier." if x.get("end") else f"Takes effect {nice(x['d'])}."),
                f"Announced {nice(ann)}." if ann else "",
                *[f"{f[0]}: {f[1]} {f[2]}".strip() for f in x.get("fees") or [] if isinstance(f, list) and len(f) >= 3],
                f"Story: {x['_stories'][0]['title']}" if x["_stories"] else "", f"On Parcel Pigeon: {link}"]
        nxt = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
        summary = ("▲ " if x["imp"] == "up" else "▼ ") + str(x["w"])
        ev.append([f"UID:{x['id']}@parcel-pigeon", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{x['d'].replace('-', '')}",
                   f"DTEND;VALUE=DATE:{nxt.replace('-', '')}", f"SUMMARY:{esc(summary)}",
                   "DESCRIPTION:" + esc("\n".join(t for t in desc if t)), f"URL:{link}", "TRANSP:TRANSPARENT",
                   f"CATEGORIES:{esc('Rate change')}"])
        if ann:
            nxa = (dt.date.fromisoformat(ann) + dt.timedelta(days=1)).isoformat()
            ev.append([f"UID:{x['id']}-ann@parcel-pigeon", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{ann.replace('-', '')}",
                       f"DTEND;VALUE=DATE:{nxa.replace('-', '')}", f"SUMMARY:{esc('Announced: ' + x['w'])}",
                       "DESCRIPTION:" + esc(f"Takes effect {nice(x['d'])}.\nOn Parcel Pigeon: {link}"),
                       f"URL:{link}", "TRANSP:TRANSPARENT", f"CATEGORIES:{esc('Announcement')}"])
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Parcel Pigeon//Rate clock//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:Parcel Pigeon rate clock", f"X-WR-CALDESC:{esc('Parcel price changes in effect now and coming up, from the Parcel Pigeon rate clock.')}",
             "X-WR-TIMEZONE:America/New_York", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for e in ev:
        lines += ["BEGIN:VEVENT", *e, "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(l) + "\r\n" for l in lines), len(ev)


def main():
    today = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else None
    text, n = build(today)
    path = common.DATA / FEED   # read at run time, so tests write to their own copy of data/
    old = path.read_bytes().decode("utf-8") if path.exists() else ""
    same = lambda t: re.sub(r"DTSTAMP:\d{8}T\d{6}Z", "", t)
    if same(old) == same(text):
        print(f"calendar: {n} events, unchanged"); return     # no new commit just for a fresh timestamp
    path.write_bytes(text.encode("utf-8"))
    print(f"calendar: {n} events written to data/{FEED}")


if __name__ == "__main__":
    main()
