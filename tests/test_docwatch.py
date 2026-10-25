"""Doc watch: every document gets checked (B1), and a dated picture backs up each page change (B35).
No live internet: pictures are taken of saved pages served from this machine."""
import datetime as dt, functools, http.server, json, math, os, threading
import pytest
import docwatch as D
from common import load, save

TODAY = dt.date.today().isoformat()
PAGE_TEXT = ("UPS Small Business Rates. Effective December 21, 2026, a 5% fuel surcharge applies to all SBR shipments. " * 12)


# ---------------------------------------------------------------- B1: the rotation moves
def library(top=37, rest=85):
    docs = [{"c": "UPS", "t": "Rate guide", "n": f"guide {i}", "u": f"https://top.example/{i}"} for i in range(top)]
    docs += [{"c": "UPS", "t": ["Terms", "Fuel", "Zones & DAS", "Peak"][i % 4], "n": f"doc {i}", "u": f"https://rest.example/{i}"}
             for i in range(rest)]
    return docs


def test_every_document_is_checked_within_the_rotation():
    """37 priority documents and --batch 15 used to leave zero rotation slots: the cursor never moved."""
    docs, idx = library(), {"cursor": 0, "docs": {}}
    rotate = max(D.ROTATE_MIN, 15)
    runs = math.ceil(85 / rotate)
    checked = set()
    for _ in range(runs):
        picks = D.pick(docs, idx, 15)
        assert all(d["u"] in {p["u"] for p in picks} for d in docs[:37])     # priority documents every run
        for d in picks:
            idx["docs"].setdefault(d["u"], {"checked": TODAY})
            checked.add(d["u"])
    assert checked == {d["u"] for d in docs}, f"{len(docs) - len(checked)} documents never checked in {runs} runs"


def test_never_checked_documents_go_first():
    docs = library(top=2, rest=30)
    idx = {"cursor": 0, "docs": {d["u"]: {"checked": TODAY} for d in docs[2:22]}}     # 20 already seen, 10 never
    picks = D.pick(docs, idx, 15)[2:]
    assert {d["u"] for d in picks[:10]} == {d["u"] for d in docs[22:]}
    assert len(picks) == 15


def test_rotation_with_a_small_batch_still_gets_slots():
    docs, idx = library(top=37, rest=85), {"cursor": 0, "docs": {}}
    assert len(D.pick(docs, idx, 5)) == 37 + D.ROTATE_MIN
    assert idx["cursor"] == D.ROTATE_MIN


# ---------------------------------------------------------------- B35: dated page pictures
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def site(tmp_path):
    """Saved pages served on 127.0.0.1: page.html (a real rate page) and blocked.html (a bot wall)."""
    www = tmp_path / "www"
    www.mkdir()
    (www / "page.html").write_text(f"<html><body><h1>Small Business Rates</h1><p>{PAGE_TEXT}</p>"
                                   "<button>Accept All</button></body></html>")
    (www / "blocked.html").write_text("<html><body><h1>Access Denied</h1><p>You don't have permission to access this page. "
                                      + "Reference #18.abc. " * 40 + "</p></body></html>")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(www)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


@pytest.fixture
def pics(data_dir, monkeypatch):
    """Pictures go under the test's own data/ copy, never the real one."""
    monkeypatch.setattr(D, "ROOT", data_dir.parent)
    monkeypatch.setattr(D, "PICS", data_dir / "snapshots")
    monkeypatch.setattr(D, "SNAP", data_dir / "docwatch")
    save("review.json", [])
    return data_dir / "snapshots"


def need_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright is not installed")


def test_a_changed_page_gets_one_dated_picture_and_text(site, pics):
    need_browser()
    doc, rec = {"c": "UPS", "n": "Small Business Rates page", "u": site + "page.html"}, {"snap": {"d": "2026-09-30", "img": "x.jpg"}}
    assert D.picture(doc, rec, PAGE_TEXT, TODAY, changed=True, how={})
    folder = pics / D.doc_id(doc["u"])
    assert sorted(f.name for f in folder.iterdir()) == [f"{TODAY}.jpg", f"{TODAY}.txt"]
    assert (folder / f"{TODAY}.jpg").read_bytes()[:2] == b"\xff\xd8"           # a JPEG
    assert (folder / f"{TODAY}.txt").read_text() == PAGE_TEXT
    assert rec["snap"]["d"] == TODAY and rec["snap"]["img"] == f"data/snapshots/{D.doc_id(doc['u'])}/{TODAY}.jpg"
    assert "prev" not in rec["snap"]                                             # the old picture file isn't on disk


def test_the_same_text_twice_takes_no_new_picture(site, pics, monkeypatch):
    need_browser()
    doc, rec = {"c": "UPS", "n": "Small Business Rates page", "u": site + "page.html"}, {}
    assert D.picture(doc, rec, PAGE_TEXT, TODAY, changed=False, how={})        # no picture yet: take one
    calls = []
    monkeypatch.setattr(D, "capture", lambda *a, **k: calls.append(a) or (200, PAGE_TEXT))
    assert not D.picture(doc, rec, PAGE_TEXT, TODAY, changed=False, how={})    # unchanged and pictured: nothing
    assert calls == []
    assert not D.picture(doc, rec, PAGE_TEXT + " more", TODAY, changed=True, how={})   # one picture a document a day
    assert calls == []
    assert len(list((pics / D.doc_id(doc["u"])).glob("*.jpg"))) == 1


def test_a_blocked_page_is_never_kept_as_proof(site, pics):
    need_browser()
    doc = {"c": "UPS", "n": "Small Business Rates page", "u": site + "blocked.html"}
    rec = {"snap": {"d": "2026-09-30", "img": "data/snapshots/old.jpg"}}
    assert not D.picture(doc, rec, PAGE_TEXT, TODAY, changed=True, how={})
    assert not list((pics / D.doc_id(doc["u"])).glob("*.jpg"))
    assert rec["snap"] == {"d": "2026-09-30", "img": "data/snapshots/old.jpg"}   # previous good picture kept
    rv = [x for x in load("review.json", []) if x.get("type") == "page-picture"]
    assert len(rv) == 1 and rv[0]["url"] == doc["u"] and "access denied" in rv[0]["note"].lower()
    D.picture(doc, rec, PAGE_TEXT, TODAY, changed=True, how={})
    assert len([x for x in load("review.json", []) if x.get("type") == "page-picture"]) == 1   # once a day per page


def test_ok_picture_rules():
    assert D.ok_picture(200, PAGE_TEXT) == (True, "")
    assert not D.ok_picture(403, PAGE_TEXT)[0]
    assert not D.ok_picture(200, "short page")[0]
    assert not D.ok_picture(200, PAGE_TEXT + " Please complete the CAPTCHA")[0]


def test_a_seventh_picture_removes_the_oldest(pics, monkeypatch):
    doc = {"c": "UPS", "n": "Small Business Rates page", "u": "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates"}
    folder = pics / D.doc_id(doc["u"])
    folder.mkdir(parents=True)
    days = [f"2026-0{m}-01" for m in range(3, 9)]                                # six older pictures
    for d in days:
        (folder / f"{d}.jpg").write_bytes(b"\xff\xd8old")
        (folder / f"{d}.txt").write_text("old")
    def fake_capture(url, out, timeout=30):
        out.write_bytes(b"\xff\xd8new")
        return 200, PAGE_TEXT
    monkeypatch.setattr(D, "capture", fake_capture)
    rec = {"snap": {"d": days[-1], "img": f"data/snapshots/{D.doc_id(doc['u'])}/{days[-1]}.jpg"}}
    assert D.picture(doc, rec, PAGE_TEXT, TODAY, changed=True, how={})
    jpgs = sorted(f.stem for f in folder.glob("*.jpg"))
    assert len(jpgs) == 6 and days[0] not in jpgs and TODAY in jpgs
    assert not (folder / f"{days[0]}.txt").exists()
    assert rec["snap"]["prev"] == f"data/snapshots/{D.doc_id(doc['u'])}/{days[-1]}.jpg"


def test_pdf_documents_are_not_photographed(pics, monkeypatch):
    monkeypatch.setattr(D, "capture", lambda *a, **k: pytest.fail("a PDF must not be photographed"))
    doc = {"c": "UPS", "n": "SBR rate guide", "u": "https://www.ups.com/assets/resources/webcontent/en_US/sbr.pdf"}
    rec = {}
    assert D.picture(doc, rec, "pdf text", TODAY, changed=True, how={"pdf": doc["u"]})
    assert rec["snap"]["d"] == TODAY and rec["snap"]["pdf"] == doc["u"] and "img" not in rec["snap"]


def test_a_playwright_error_still_publishes_the_text_result(pics, monkeypatch):
    """The picture is extra proof. A browser failure is logged; the story still publishes and the old snap stays."""
    u = "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates"
    save("docs.json", [{"c": "UPS", "t": "Special program", "n": "Small Business Rates page", "u": u}])
    save("seed.json", {"docs": []})
    D.SNAP.mkdir(parents=True, exist_ok=True)
    import gzip
    old = "UPS Small Business Rates are inclusive of Fuel Surcharge.\n" * 20
    D.snap_path(u).write_bytes(gzip.compress(D.norm(old).encode()))
    before = {"d": "2026-09-30", "img": "data/snapshots/x/2026-09-30.jpg"}
    save("docwatch.json", {"cursor": 0, "docs": {u: {"hash": D.h(D.norm(old)), "first": "2026-09-01", "checked": "2026-10-01",
                                                    "n": "Small Business Rates page", "snap": dict(before)}}})
    new = old + "Effective December 21, 2026, a 5% fuel surcharge applies to all SBR shipments.\n"
    monkeypatch.setattr(D, "text_of", lambda url, name="": new)
    monkeypatch.setattr(D, "is_covered", lambda *a, **k: [])
    monkeypatch.setattr(D, "audit", lambda *a, **k: {
        "material": True, "verdict": "price change", "title": "UPS adds 5% fuel surcharge to Small Business Rates",
        "summary": "s", "effect": "e", "imp": "up", "lvl": 3, "category": "Pricing & GRI", "act": "2026-12-21",
        "changes": [{"what": "Fuel surcharge on SBR", "before": None, "after": "5%", "effective": "2026-12-21", "who": "SBR"}]})
    def broken(*a, **k):
        raise RuntimeError("Executable doesn't exist at /ms-playwright/chromium")
    monkeypatch.setattr(D, "capture", broken)
    monkeypatch.setattr("sys.argv", ["docwatch.py", "--batch", "15"])
    D.main()
    assert any(s.get("url") == u and "5% fuel" in s["title"] for s in load("news.json", []))
    rec = load("docwatch.json", {})["docs"][u]
    assert rec["snap"] == before and rec["changed"] == TODAY
