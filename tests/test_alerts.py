"""Phone alerts: what a push says and where it lands. No network: pushes are captured, not sent."""
import datetime as dt
import alerts as A


def story(**kw):
    s = {"id": "s1", "date": "2026-10-21", "title": "FedEx adds $2 surcharge", "sum": "FedEx adds a $2 surcharge.", "plain": "",
         "c": ["FedEx"], "cat": "Fees & rules", "lvl": 3, "srcs": [{"src": "Some Blog", "url": "https://blog.example/x"}]}
    s.update(kw)
    return s


def test_unconfirmed_never_pushes_as_major():
    assert A.is_major(story())
    weak = story(unconf=True)
    assert not A.is_major(weak)                     # no review issue, no auto-send as big news
    assert A.push_level(weak) == 1                  # ranked like a small story in the queue
    assert not A.notable(weak)                      # only readers who chose "Every new story"
    assert A.flags(weak) == ["Unconfirmed"]
    assert A.flags(story(offc=True)) == ["Off-cycle"]


def test_unconfirmed_never_leads_a_busy_run(monkeypatch):
    sent = []
    monkeypatch.setattr(A, "push", lambda h, b, u, *a, **k: sent.append((h, b, u, k)) or {"id": "x"})
    monkeypatch.setattr(A, "SENT", [])
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 21, 10, 0, tzinfo=A.ET))
    at = A.now_et().isoformat()
    q = [{"kind": "story", "key": f"story:{i}", "t": f"Story {i}", "m": "m", "at": at, "lvl": 1, "topic": "news", "mask": None,
          "url": "u"} for i in range(4)]
    q.insert(0, {"kind": "story", "key": "story:weak", "t": "Big claim", "m": "Unconfirmed: m", "at": at, "lvl": 3, "unconf": True,
                 "big": False, "topic": "news", "mask": None, "url": "u"})
    A.send_queued({"queue": q})
    assert len(sent) == 1, sent                     # one roll-up, no stand-alone alert for the unconfirmed story
    heading, body, url, kw = sent[0]
    assert heading == "5 new parcel stories" and kw.get("lines")
    assert len(body.split("\n")) <= 4 and body.endswith("+2 more in the app")
    assert "Unconfirmed: Big claim" in body


def test_rollup_and_text_limits():
    long = "• " + "word " * 30
    assert A.fit_lines("\n".join([long.strip()] * 6)).count("\n") < 4
    assert A.fit_lines("a\nb\nc\nd\ne") == "a\nb\nc\nd"
    assert len(A.short("x " * 100, A.TITLE_MAX)) <= A.TITLE_MAX


def test_clock_reminder_names_the_date_and_expires(monkeypatch):
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 21, 10, 0, tzinfo=A.ET))
    it = A.clock_item("e1:1", {"id": "e1", "d": "2026-10-22", "c": "UPS", "w": "UPS peak surcharge takes effect", "imp": "up"}, 1)
    assert it["t"] == "UPS: takes effect Thu Oct 22" and len(it["t"]) <= A.TITLE_MAX
    assert it["topic_id"] == "pp-clock-e1"          # the 1-day reminder replaces the 7-day one on the phone
    sent = []
    monkeypatch.setattr(A, "push", lambda *a, **k: sent.append(a) or {"id": "x"})
    monkeypatch.setattr(A, "SENT", [])
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 23, 10, 0, tzinfo=A.ET))
    A.send_queued({"queue": [it]})
    assert sent == []                               # the date has passed: it never goes out late


def test_links_and_effective_date_copy(monkeypatch):
    monkeypatch.setattr(A, "SITE", "https://x.github.io/parcel-pigeon/")
    assert A.company_link("ontrac") == "https://x.github.io/parcel-pigeon/#c=ontrac"
    assert A.story_link({"id": "abc"}).endswith("#story=abc")
    s = story(act="2027-01-04", sum="FedEx adds a $2 surcharge in January.")
    assert A.nice_date(s["act"]) == "Jan 4, 2027"
    assert A.numbers_ok("Takes effect Jan 4", s)    # the effective date counts as a fact from the story
    assert not A.numbers_ok("Takes effect Jan 5", s)
