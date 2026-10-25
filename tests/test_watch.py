"""The hourly page watcher: one story per material audit (B9), a partly failed check is retried (B10), the "already told"
fingerprint keeps changes with another date or service apart (B10), and similar headlines about different dates or
services are not merged (B10). No network: pages, files and the auditor's replies are given."""
import types
import pytest
import watch as W
from common import load, save, same_event, h

PAGE = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates"
FILE = "https://www.ups.com/assets/fuel-tables-nov-2026.pdf"
OLD = "UPS Important Updates\nSeptember notice about peak surcharges\n"
NEW = OLD + "Effective December 21, 2026, Daily Rates rise an average net 5.9%.\n"


def change(what, after, eff="2026-12-21", who="UPS shippers"):
    return {"what": what, "before": None, "after": after, "effective": eff, "who": who, "impact": None}


def result(title, *changes, file=None):
    return {"verdict": "price change", "material": True, "title": title, "summary": title + ".", "effect": "Shippers pay more.",
            "imp": "up", "lvl": 3, "category": "Pricing & GRI", "act": changes[0]["effective"], "changes": list(changes),
            "unknowns": [], **({"file": file} if file else {})}


@pytest.fixture
def page(data_dir, tmp_path, monkeypatch):
    """One watched UPS page whose text changed (seen once already) and which now links one new file."""
    root = tmp_path / "root"
    (root / "pipeline").mkdir(parents=True)
    (root / "pipeline" / "sources.yaml").write_text(f'watch:\n  - {{carrier: UPS, kind: page, name: Rate and Service Guides, url: "{PAGE}"}}\n')
    monkeypatch.setattr(W, "ROOT", root)
    monkeypatch.setattr(W, "SNAP", data_dir / "snapshots")
    (data_dir / "snapshots").mkdir(exist_ok=True)
    (data_dir / "snapshots" / f"{h(PAGE)}.txt").write_text("\n".join(W.norm(OLD)))
    sig = h("\n".join(W.norm(NEW)) + "|" + FILE)
    save("watch_state.json", {PAGE: {"checked": "2026-10-20", "pdfs": [], "lines": 2, "told": [], "pend": sig}})
    save("news.json", [])
    pg = types.SimpleNamespace(via="direct", when=None)
    monkeypatch.setattr(W, "page_text", lambda url, full=False: (NEW, [FILE], pg))
    monkeypatch.setattr(W, "catalog", lambda *a, **k: 0)
    monkeypatch.setattr(W, "file_text", lambda url, max_pages=None: "UPS fuel surcharge tables effective November 2, 2026. 28.50%")
    monkeypatch.setattr(W, "remember", lambda *a, **k: None)
    monkeypatch.setattr(W, "is_covered", lambda *a, **k: [])
    monkeypatch.setattr(W, "ask", lambda *a, **k: None)
    return data_dir


def test_one_story_per_material_audit(page, monkeypatch):
    replies = {FILE: result("UPS posts new Ground fuel surcharge table effective Nov 2",
                            change("Ground fuel surcharge table", "New table from 28.50%", "2026-11-02"), file=FILE),
               PAGE: result("UPS sets 5.9% average Daily Rates increase effective Dec 21",
                            change("Daily Rates increase", "Average net increase of 5.9%"))}
    monkeypatch.setattr(W, "audit", lambda carrier, name, url, old, new, note="": dict(replies[url]))
    W.main()
    live = load("news.json", [])
    assert len(live) == 2, [s["title"] for s in live]                     # two stories, not one with "Also: ..."
    assert not any("Also:" in s["sum"] for s in live)
    fuel = next(s for s in live if "fuel" in s["title"])
    assert fuel["url"] == FILE and [x["url"] for x in fuel["srcs"]] == [PAGE, FILE]


def test_partly_failed_check_is_retried(page, monkeypatch):
    calls = []

    def audit(carrier, name, url, old, new, note=""):
        calls.append(url)
        if url == FILE:
            return None                                                    # the file's audit fails this run
        return result("UPS sets 5.9% average Daily Rates increase effective Dec 21", change("Daily Rates increase", "Average net increase of 5.9%"))
    monkeypatch.setattr(W, "audit", audit)
    W.main()
    assert load("news.json", []) == [], "nothing is published from half a check"
    st = load("watch_state.json", {})[PAGE]
    assert st["fail_runs"] == 1 and st.get("pend")                         # the page is checked again next run
    assert (page / "snapshots" / f"{h(PAGE)}.txt").read_text() == "\n".join(W.norm(OLD))   # the snapshot didn't move
    W.main(); W.main()                                                     # after 3 failed runs the part that worked goes ahead
    assert [s["title"] for s in load("news.json", [])] == ["UPS sets 5.9% average Daily Rates increase effective Dec 21"]


def test_fingerprint_includes_before_effective_and_who():
    a = change("Fuel surcharge table", "New table", "2026-11-02", "UPS Ground")
    assert W.fingerprint(a) != W.fingerprint(dict(a, effective="2026-11-09"))
    assert W.fingerprint(a) != W.fingerprint(dict(a, who="UPS Air"))
    assert W.fingerprint(a) != W.fingerprint(dict(a, before="Old table"))
    assert W.fingerprint(a) == W.fingerprint(dict(a, after="New  TABLE"))  # spacing and case don't make a new change
    assert W.old_fingerprint(a) == W.old_fingerprint(dict(a, effective="2026-11-09"))   # the old one couldn't tell them apart


def test_told_change_for_another_date_is_still_reported(page, monkeypatch):
    told = change("Ground fuel surcharge table", "New table from 28.50%", "2026-11-02")
    st = load("watch_state.json", {})
    st[PAGE]["told2"] = [W.fingerprint(told)]
    save("watch_state.json", st)
    replies = {FILE: result("UPS posts Ground fuel surcharge table effective Nov 2", told, file=FILE),
               PAGE: result("UPS posts Ground fuel surcharge table effective Nov 9", dict(told, effective="2026-11-09"))}
    monkeypatch.setattr(W, "audit", lambda carrier, name, url, old, new, note="": dict(replies[url]))
    W.main()
    assert [s["title"] for s in load("news.json", [])] == ["UPS posts Ground fuel surcharge table effective Nov 9"]


def story(title, act=None, url="https://www.ups.com/fuel"):
    return {"c": ["UPS"], "date": "2026-10-23", "title": title, "url": url, "srcs": [{"url": url}], **({"act": act} if act else {})}


def test_same_event_keeps_different_dates_and_services_apart():
    ground = story("UPS raises Ground fuel surcharge Nov 2")
    assert not same_event(ground, story("UPS raises Air fuel surcharge Nov 9"))
    assert not same_event(ground, story("UPS raises Air fuel surcharge Nov 2"))            # other service
    assert not same_event(story("UPS raises fuel surcharge", "2026-11-02"), story("UPS raises fuel surcharge", "2026-11-09"))
    assert same_event(ground, story("UPS raises Ground fuel surcharge Nov 2, per new table"))   # one event, reworded
    assert same_event(story("UPS raises Ground fuel surcharge", "2026-11-02"), story("UPS raises Ground fuel surcharges Nov 2"))


def test_robot_notes_hold_the_story(page, monkeypatch):
    bad = result("Not in the supplied text", change("Daily Rates increase", "Average net increase of 5.9%"))
    replies = {FILE: dict(bad, file=FILE, material=False), PAGE: bad}
    asked = []
    monkeypatch.setattr(W, "ask", lambda story, reasons, srcs, **k: asked.append(reasons) or "https://github.com/x/issues/1")
    monkeypatch.setattr(W, "audit", lambda carrier, name, url, old, new, note="": dict(replies[url]))
    W.main()
    assert load("news.json", []) == [] and asked and "robot notes" in asked[0][-1]
