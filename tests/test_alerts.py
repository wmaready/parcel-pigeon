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


# ---------------------------------------------------------------- Oct 2026 outage: no pushes after Oct 20
class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def onesignal(monkeypatch, status=200, body=None):
    """OneSignal keys set and every push captured; replies with `status` and `body`."""
    import requests
    calls = []
    def post(url, json=None, **kw):
        if "onesignal" not in url:
            raise RuntimeError("tests must not use the network")
        calls.append(json)
        return FakeResponse(status, body if body is not None else {"id": f"n{len(calls)}"})
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(A, "APP_ID", "app")
    monkeypatch.setattr(A, "API_KEY", "key")
    monkeypatch.setattr(A, "GH", "")
    monkeypatch.setattr(A, "PUSH_ERRORS", [], raising=False)
    monkeypatch.setattr(A, "COPY_DOWN", {}, raising=False)
    return calls


def quiet_side_jobs(monkeypatch):
    """Everything around the alerts that would reach the network does nothing."""
    import sys, types, players
    monkeypatch.setattr(A, "process_doc_requests", lambda: None)
    monkeypatch.setattr(A, "auto_harvest", lambda state: None)
    monkeypatch.setattr(players, "backfill_sites", lambda n: None)
    monkeypatch.setattr(players, "family_check", lambda n: None)
    for name in ("media", "archive", "guides"):
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(main=lambda *a: None, logos=lambda n: None,
                                                                     photos=lambda n: None))


def test_paused_extras_no_longer_kill_the_alerts_run(data_dir, monkeypatch):
    """The bug: once the day's Claude extras were paused, players.main() called sys.exit(1) inside alerts.run().
    SystemExit isn't an Exception, so every daytime run died before sending or saving (log: 'players: waiting,
    extras pause at half of today's allowance' then '::warning::alerts.py failed'). Pushes stopped on Oct 20."""
    import common, players
    from common import load, save
    quiet_side_jobs(monkeypatch)
    calls = onesignal(monkeypatch)
    # The test's own starting state, not the live one copied from data/: the live alerts_state.json carries the real
    # last push time (e.g. Oct 25), which is after this test's clock (Oct 22), so the 50-minute spacing held every push.
    # Everything already on file counts as seen; one story waits in the queue, so the run has exactly one thing to send.
    fuel = load("fuel.json", {}).get("hist") or {}
    save("alerts_state.json", {
        "stories": [s["id"] for s in load("news.json", []) if s.get("id")],
        "titles": [], "sent": [], "recent": [],
        "clock": [f"{e.get('id')}:{n}" for e in load("seed.json", {}).get("clock") or [] for n in (7, 1)],
        "fuel": {c: sorted(h)[-1] for c, h in fuel.items() if h},
        "players": [p["id"] for p in load("players.json", {}).get("players", [])],
        "queue": [{"kind": "story", "key": "story:test queued story", "id": "t1", "t": "Test story", "m": "m",
                   "at": "2026-10-22T09:30:00-04:00", "lvl": 1, "topic": "news", "mask": None, "url": "u"}]})
    monkeypatch.setattr(players, "API_KEY", "test-key")
    monkeypatch.setattr(common, "paused", lambda extra=False: "Claude calls paused: $1.20 spent today")
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 22, 10, 0, tzinfo=A.ET))
    assert players.main() is False                   # paused research reports it; it no longer exits the process
    A.run()                                          # before the fix: SystemExit(1) here
    st = load("alerts_state.json", {})
    assert calls, "nothing was pushed"
    assert st["last_push"].startswith("2026-10-22T10:00")
    assert st["day"] == {"d": "2026-10-22", "n": len(calls)}


def test_side_job_survives_sys_exit():
    import sys
    assert A.side_job("x", lambda: sys.exit(1)) is None
    assert A.side_job("y", lambda: 1 / 0) is None
    assert A.side_job("z", lambda: 5) == 5


def test_push_copy_never_waits_on_the_budget(monkeypatch):
    """Alert copy is a tenth of a cent: it runs unpaced. If Claude fails anyway, the headline goes out."""
    import common
    monkeypatch.setattr(A, "COPY_DOWN", {}, raising=False)
    monkeypatch.setattr(common, "paused", lambda extra=False: "paused")
    seen = {}
    def fake_claude(model, system, user, max_tokens=1500, paced=True):
        seen["paced"] = paced
        return '{"s1": {"t": "FedEx adds $2 surcharge", "m": "A $2 surcharge on FedEx shipments."}}'
    monkeypatch.setattr(A, "claude", fake_claude)
    out = A.push_copy([story()], {})
    assert seen["paced"] is False and out["s1"]["t"] == "FedEx adds $2 surcharge"
    # Claude down: the headline and first sentence, no exception, and no second try this run
    def down(*a, **k):
        raise RuntimeError("Claude calls paused")
    monkeypatch.setattr(A, "claude", down)
    out = A.push_copy([story(id="s2", title="UPS adds fee")], {})
    assert out["s2"] == {"t": "UPS adds fee", "m": "FedEx adds a $2 surcharge."}
    assert A.COPY_DOWN


def test_onesignal_error_is_not_counted_as_sent_and_opens_one_issue(data_dir, monkeypatch):
    import scoop
    issues = []
    monkeypatch.setattr(scoop, "notify", lambda title, body, **k: issues.append(title))
    calls = onesignal(monkeypatch, 400, {"errors": ["Unknown field web_push_topic"]})
    monkeypatch.setattr(A, "SENT", [])
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 22, 10, 0, tzinfo=A.ET))
    at = A.now_et().isoformat()
    st = {"queue": [{"kind": "story", "key": "story:a", "t": "A", "m": "m", "at": at, "lvl": 2, "topic": "news",
                     "mask": None, "url": "u"}], "last_push": "2026-10-21T09:00:00-04:00"}
    assert A.send_queued(st) == 0 and len(calls) == 1
    assert st["last_push"] == "2026-10-21T09:00:00-04:00"   # a refused push is not a sent push
    assert [q["key"] for q in st["queue"]] == ["story:a"] and A.SENT == []
    assert A.PUSH_ERRORS and A.PUSH_ERRORS[0]["status"] == 400
    A.check_health(st)
    A.check_health(st)
    assert issues == ["Parcel Pigeon: OneSignal rejected a phone alert"]   # one issue a day, not one a run


def test_stalled_queue_opens_one_issue_a_day(data_dir, monkeypatch):
    """The real state on Oct 23: 14 waiting, last push Oct 20 12:54 ET."""
    import scoop
    from common import load
    issues = []
    monkeypatch.setattr(scoop, "notify", lambda title, body, **k: issues.append((title, body)))
    monkeypatch.setattr(A, "PUSH_ERRORS", [], raising=False)
    monkeypatch.setattr(A, "GH", "")
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 23, 10, 0, tzinfo=A.ET))
    st = {"queue": [{"at": "2026-10-20T22:51:02-04:00"}, {"at": "2026-10-22T01:41:29-04:00"}],
          "last_push": "2026-10-20T12:54:07-04:00"}
    assert A.stalled(st) > 24
    A.check_health(st)
    A.check_health(st)
    assert len(issues) == 1 and issues[0][0] == "Parcel Pigeon: phone alerts have stopped"
    assert load("alerts_alarm.json", {})["push-stalled"] == "2026-10-23"
    # the next day it speaks up again if still stuck
    monkeypatch.setattr(A, "now_et", lambda: dt.datetime(2026, 10, 24, 10, 0, tzinfo=A.ET))
    A.check_health(st)
    assert len(issues) == 2
    # not stalled: a fresh item after a quiet week, an empty queue, or a recent push
    now = dt.datetime(2026, 10, 23, 10, 0, tzinfo=A.ET)
    assert A.stalled({"queue": [{"at": "2026-10-23T09:00:00-04:00"}], "last_push": "2026-10-15T09:00:00-04:00"}, now) is None
    assert A.stalled({"queue": [], "last_push": "2026-10-15T09:00:00-04:00"}, now) is None
    assert A.stalled({"queue": [{"at": "2026-10-21T09:00:00-04:00"}], "last_push": "2026-10-23T08:00:00-04:00"}, now) is None
