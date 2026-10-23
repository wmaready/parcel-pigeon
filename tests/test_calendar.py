"""The rate clock as a calendar feed (data/rates.ics): valid iCalendar, the same price changes the app shows, and the
"Add to calendar" button on the rate clock."""
import re
import pytest
from conftest import ROOT
from test_app import site, OVERFLOW  # noqa: F401  (the local web server fixture)
from test_polish import app


def _ics_check(text):
    """The parts of RFC 5545 calendar apps are strict about."""
    raw = text.encode("utf-8")
    assert b"\n" not in raw.replace(b"\r\n", b""), "every line ends in CRLF"
    assert all(len(l) <= 75 for l in raw.split(b"\r\n")), "lines are folded at 75 octets"
    lines = text.replace("\r\n ", "").split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert "VERSION:2.0" in lines and any(l.startswith("PRODID:") for l in lines)
    events, cur = [], None
    for l in lines:
        if l == "BEGIN:VEVENT":
            cur = {}
        elif l == "END:VEVENT":
            events.append(cur); cur = None
        elif cur is not None and ":" in l:
            k, v = l.split(":", 1)
            cur[k] = v
    uids = [e.get("UID") for e in events]
    assert all(uids) and len(set(uids)) == len(uids), "every event has its own UID"
    for e in events:
        assert re.match(r"^\d{8}T\d{6}Z$", e.get("DTSTAMP", "")), e
        assert re.match(r"^\d{8}$", e.get("DTSTART;VALUE=DATE", "")), e
        assert re.match(r"^\d{8}$", e.get("DTEND;VALUE=DATE", "")) and e["DTEND;VALUE=DATE"] > e["DTSTART;VALUE=DATE"], e
        assert e.get("SUMMARY") and e.get("URL", "").startswith("https://wmaready.github.io/parcel-pigeon/")
    return events


def test_calendar_feed_format_and_contents(data_dir):
    import common, ratecal
    news = common.load("news.json", [])
    news.insert(0, {"id": "zzcal1", "date": "2026-10-01", "c": ["FedEx"], "cat": "Pricing & GRI", "kind": "News", "lvl": 2, "imp": "up",
                    "title": "FedEx sets a test surcharge, with commas; and semicolons", "sum": "x", "plain": "x", "ann": "2026-10-01",
                    "url": "https://www.fedex.com/zz", "srcs": [{"src": "FedEx", "url": "https://www.fedex.com/zz"}],
                    "dates": [{"d": "2026-12-01", "w": "FedEx test surcharge, a very long description that has to be folded over more than one line", "imp": "up"},
                              {"d": "2026-09-01", "w": "FedEx test fee already past", "imp": "up"},
                              {"d": "2026-12-02", "w": "FedEx test webinar", "imp": "info"}]})
    common.save("news.json", news)
    text, n = ratecal.build(today="2026-10-23", stamp="20261023T120000Z")
    events = _ics_check(text)
    by = {e["UID"]: e for e in events}
    ev = by["xzzcal10@parcel-pigeon"]
    assert ev["DTSTART;VALUE=DATE"] == "20261201" and ev["URL"].endswith("#s=zzcal1")
    ann = by["xzzcal10-ann@parcel-pigeon"]                       # the announcement date the source states, as its own event
    assert ann["DTSTART;VALUE=DATE"] == "20261001" and ann["SUMMARY"].startswith("Announced: ")
    assert "Announced Oct 1\\, 2026." in text.replace("\r\n ", "")
    assert not any("already past" in e["SUMMARY"] or "webinar" in e["SUMMARY"] for e in events)    # past, and not a price change
    assert all(e["DTEND;VALUE=DATE"] > "20261023" for e in events if not e["UID"].endswith("-ann@parcel-pigeon"))
    # a run with nothing new leaves the file alone (no commit just for a new timestamp)
    ratecal.main()
    first = (data_dir / "rates.ics").read_bytes()
    ratecal.main()
    assert (data_dir / "rates.ics").read_bytes() == first


def test_story_date_naming_another_carrier_stays_off(data_dir):
    """As in the app: in a GOFO story, 'FedEx demand fees begin' is FedEx's news, not a GOFO date."""
    import common, ratecal
    common.save("news.json", [{"id": "zzgofo", "date": "2026-10-20", "c": ["Regional"], "cat": "Fuel", "kind": "News", "lvl": 2, "imp": "up",
                               "title": "GOFO adds a test surcharge", "sum": "x", "plain": "x", "url": "https://x.example/gofo",
                               "dates": [{"d": "2026-12-03", "w": "UPS begins a test fee", "imp": "up"},
                                         {"d": "2026-12-04", "w": "GOFO test surcharge takes effect; FedEx test fees begin", "imp": "up"}]}])
    text, _ = ratecal.build(today="2026-10-23")
    flat = text.replace("\r\n ", "")
    assert "UPS begins a test fee" not in flat and "FedEx test fees begin" not in flat
    assert "UID:xzzgofo0@parcel-pigeon" in flat and "SUMMARY:▲ GOFO test surcharge takes effect\r\n" in flat


def test_committed_feed_is_valid_and_deploy_keeps_it():
    import yaml
    _ics_check((ROOT / "data/rates.ics").read_bytes().decode("utf-8"))
    for f in ("update.yml", "watch.yml"):
        w = yaml.safe_load((ROOT / ".github/workflows" / f).read_text())
        runs = [s.get("run", "") for j in w["jobs"].values() for s in j["steps"]]
        assert any("python ratecal.py" in r for r in runs), f
        strip = [r for r in runs if r.startswith("rm ")]
        assert strip and not any(re.search(r"rates\.ics|fuel_events|\*\.ics|\sdata(\s|/?$)", r) for r in strip), strip


@pytest.mark.parametrize("width", [390, 1280])
def test_rate_clock_add_to_calendar(site, width):
    import ratecal
    with app(site, width) as pg:
        pg.click('nav.tabs [data-tab="clock"]')
        pg.wait_for_timeout(300)
        assert pg.get_attribute("#calWebcal", "href") == "webcal://wmaready.github.io/parcel-pigeon/data/rates.ics"
        assert pg.get_attribute("#calCopy", "data-cal") == "https://wmaready.github.io/parcel-pigeon/data/rates.ics"
        pg.click("#calSub > summary")
        txt = pg.inner_text("#calSub")
        assert "Subscribe from web" in txt and "From URL" in txt
        assert pg.evaluate(OVERFLOW) is None
        # the feed holds the same price changes the rate clock shows from today on
        today = pg.evaluate("() => TODAY")
        app_ids = pg.evaluate("() => DATES.filter(x => (x.imp === 'up' || x.imp === 'down') && !x.verify && (x.end || x.d) >= TODAY).map(x => x.id)")
    text, _ = ratecal.build(today=today)
    feed = [u.split("@")[0] for u in re.findall(r"^UID:(.*)$", text.replace("\r\n ", ""), re.M) if not u.endswith("-ann@parcel-pigeon")]
    assert sorted(feed) == sorted(app_ids)
