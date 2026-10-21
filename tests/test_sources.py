"""Outlet tiers decide which source leads a story; sources.yaml must stay valid."""
import yaml
from conftest import ROOT
from common import tier, primary_first, canon


def test_tiers():
    assert tier("UPS", "https://about.ups.com/x") == 0
    assert tier("The Wall Street Journal", None, "https://www.wsj.com") == 1
    assert tier("Reuters") == 1
    assert tier("FreightWaves", "https://www.freightwaves.com/news/x") == 2
    assert tier("RiverheadLOCAL", None, "https://riverheadlocal.com") == 3


def test_best_source_leads():
    o = primary_first([{"src": "Page Six", "url": "https://pagesix.com/a"}, {"src": "FreightWaves", "url": "https://www.freightwaves.com/a"},
                       {"src": "CNBC", "url": "https://www.cnbc.com/a"}, {"src": "FedEx", "url": "https://newsroom.fedex.com/a"}])
    assert [x["src"] for x in o] == ["FedEx", "CNBC", "FreightWaves", "Page Six"]


def test_cache_stamps_ignored():
    assert canon("https://ontrac.sirv.com/pdf/2026-OnTrac-Rates.pdf?v=20261009174051") == "https://ontrac.sirv.com/pdf/2026-OnTrac-Rates.pdf"


def test_sources_yaml():
    cfg = yaml.safe_load((ROOT / "pipeline" / "sources.yaml").read_text())
    assert cfg["direct"] and cfg["discovery"] and cfg["watch"]
    assert len(cfg["discovery"]) == len(set(cfg["discovery"])), "duplicate search in sources.yaml"
    for w in cfg["watch"]:
        assert {"carrier", "kind", "name", "url"} <= set(w), w
        assert w["kind"] in ("page", "pdf"), w


def test_spam_sites_are_never_sources():
    from common import not_a_source
    assert not_a_source("EIN Presswire", "https://www.einpresswire.com/article/1")
    assert not_a_source("GuruFocus", None, "https://www.gurufocus.com")
    assert not not_a_source("FreightWaves", "https://www.freightwaves.com/news/x")
    assert not not_a_source("UPS", "https://about.ups.com/x")
