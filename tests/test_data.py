"""The published data files the app reads must stay valid and consistent."""
import json
from conftest import ROOT
from common import canon

DATA = ROOT / "data"


def test_every_json_file_parses():
    for p in DATA.glob("*.json"):
        json.loads(p.read_text())


def test_docs_have_no_duplicate_files():
    urls = [canon(d["u"]) for d in json.loads((DATA / "docs.json").read_text()) if d.get("u")]
    dup = {u for u in urls if urls.count(u) > 1}
    assert not dup, dup


def test_almanac_shape():
    alm = json.loads((DATA / "almanac.json").read_text())
    ids = [e["id"] for e in alm]
    assert len(ids) == len(set(ids))
    for e in alm:
        assert e["carrier"] and isinstance(e["year"], int) and e.get("kind") and e.get("headline"), e
        assert e.get("conf") in ("confirmed", "partial"), e


def test_patterns_figures_come_from_almanac():
    from themes import compact
    from common import numbers_supported
    src = compact(json.loads((DATA / "almanac.json").read_text()))
    for it in json.loads((DATA / "patterns.json").read_text()).get("items", []):
        assert not numbers_supported(it["t"] + " " + it["body"], src), it["t"]


def test_market_map_facts():
    mp = json.loads((DATA / "players.json").read_text())
    for pid, f in (mp.get("facts") or {}).items():
        assert f.get("vf"), pid
        if "geo" in f:
            lon, lat = f["geo"]
            assert -180 <= lon <= 180 and -90 <= lat <= 90, pid
    for m in mp.get("moves") or []:
        assert m.get("id") and m.get("k") and m.get("url"), m


def test_no_company_gets_a_parent_from_an_empty_name():
    """A non-Latin alias (メルカリ株式会社) normalizes to "" and once matched every missing parent: 28 companies were
    shown as owned by Mercari or Belposhta."""
    import players as P
    byname = P.Names()
    byname[P.norm("メルカリ株式会社")] = "mercari"
    byname[P.norm("UPS")] = "ups"
    assert byname.get(P.norm(None)) is None and "" not in byname and byname.get("ups") == "ups"
    import json
    from pathlib import Path
    pl = json.loads((Path(__file__).resolve().parent.parent / "data" / "players.json").read_text())
    assert not [p["id"] for p in pl["players"] if p.get("parent") in ("mercari", "belposhta")]
