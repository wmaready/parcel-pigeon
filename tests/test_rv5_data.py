"""Outside review v5 data fixes (tools/review_v5_data.py): the facts it sets, and the rules that keep them true."""
import datetime as dt
import importlib.util
import json

from conftest import ROOT
from common import numbers_supported, same_event, deal_overlay

DATA = ROOT / "data"
SBR_URL = "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates"


def j(name):
    return json.loads((DATA / name).read_text())


def news():
    return {s["id"]: s for s in j("news.json")}


def pool():
    return {s["id"]: s for s in j("seed.json").get("news", []) + j("news.json") if s.get("id")}


def dropped():
    return {d if isinstance(d, str) else d.get("id") for d in j("drop.json")}


# ---------------------------------------------------------------- B14
def test_ups_2027_almanac_entry_is_announced_at_5_9_percent():
    e = next(e for e in j("almanac.json") if e.get("id") == "ups-2027-gri")
    assert e["kind"] == "gri" and e["carrier"] == "UPS" and e["year"] == 2027
    assert e["pct"] == 5.9 and e["effective"] == "2026-12-21"
    assert e["announced"] in ("2026-10-22", "2026-10-23")
    text = " ".join([e["headline"], e["note"], *e["details"]]).lower()
    assert "not yet announced" not in text and "do not show" not in text
    assert all(w in e["details"][0] for w in ("Ground", "Air", "International", "Daily Rates"))
    assert e["sources"] and e["sources"][0].startswith("https://www.ups.com/")


def test_no_gri_left_not_yet_announced_once_its_story_is_published():
    stories = [s for s in j("news.json") if s.get("cat") == "Pricing & GRI" and s.get("imp") == "up" and s.get("act")]
    for e in j("almanac.json"):
        if e.get("kind") != "gri" or "not yet announced" not in (e.get("headline") or "").lower():
            continue
        hit = [s for s in stories if e["carrier"] in s.get("c", []) and "rate increase" in s["title"].lower()
               and int(s["act"][:4]) in (e["year"] - 1, e["year"])]
        assert not hit, (e["id"], [s["id"] for s in hit])


def test_sbr_is_its_own_almanac_entry():
    e = next(e for e in j("almanac.json") if e.get("id") == "ups-2027-sbr-2026-12-21")
    assert e["carrier"] == "UPS" and e["pct"] == 4.5 and e["effective"] == "2026-12-21" and e["announced"] is None
    assert any("5% fuel surcharge" in d for d in e["details"]) and SBR_URL in e["sources"]
    assert e["kind"] != "gri"     # one GRI per carrier and year; SBR is a separate program


# ---------------------------------------------------------------- B2
def test_sbr_story_is_published_with_its_source():
    s = news()["rv5-ups-sbr-fuel"]
    assert s["cat"] == "Pricing & GRI" and s["imp"] == "up" and int(s["lvl"]) >= 2 and s["act"] == "2026-12-21"
    assert "ann" not in s                              # the SBR page states no announcement date
    assert s["srcs"][0]["url"] == SBR_URL and s["url"] == SBR_URL and s["srcs"][0].get("checked")
    text = " ".join([s["title"], s["sum"], s["plain"], s["why"]])
    for fig in ("4.5%", "5% fuel surcharge", "9.7%", "40 to 50 lb"):
        assert fig in text, fig
    assert round((1.045 * 1.05 - 1) * 100, 1) == 9.7
    assert s["why"].startswith("Removes a stated SBR benefit")
    assert [d["d"] for d in s["dates"]] == ["2026-12-21"] and all(d["imp"] == "up" for d in s["dates"])


def test_sbr_story_is_not_merged_into_the_ups_gri_story(data_dir):
    import common
    n = news()
    assert not same_event(n["rv5-ups-sbr-fuel"], n["w84705482dd2f"])
    out = {s["id"] for s in common.dedupe_live(j("news.json"))}
    assert {"rv5-ups-sbr-fuel", "w84705482dd2f", "rv5-fedex-freight-spin-done", "a0ee60aceb401"} <= out


# ---------------------------------------------------------------- B5 / B7
def test_ups_2027_clock_is_one_line_with_5_9_percent():
    s = news()["w84705482dd2f"]
    assert "minimum billable weight" in s["title"] and "threshold" not in s["title"]
    dec = [d for d in s["dates"] if d["d"] == "2026-12-21"]
    assert len(dec) == 1
    d = dec[0]
    assert d["w"] == "UPS 2027 rate increase: 5.9% average (Ground, Air, International)" and d["imp"] == "up"
    assert d["fx"] == {"t": "gri", "car": "UPS", "pct": 5.9, "src": s["url"]}
    assert all(len(f) == 3 for f in d["fees"]) and any("minimum billable weight" in f[1] for f in d["fees"])
    assert ";" not in d["w"]     # the app splits clock labels on ';'


def test_no_clock_label_is_cut_mid_word():
    for s in j("news.json"):
        whole = {f"{c}: {ch.get('what')}" for ch in s.get("changes") or [] for c in s.get("c") or [] if ch.get("what")}
        for d in s.get("dates") or []:
            w = d.get("w") or ""
            assert not any(len(f) > len(w) and f.startswith(w) for f in whole), (s["id"], w)


# ---------------------------------------------------------------- B12
def test_oct_13_index_study_is_one_story_with_all_sources():
    n = news()
    keep = n["a0ee60aceb401"]
    urls = " ".join(x["url"] for x in keep["srcs"])
    for host in ("prnewswire.com", "finance.yahoo.com", "freightwaves.com", "ajot.com"):
        assert host in urls, host
    assert len({x["url"] for x in keep["srcs"]}) == len(keep["srcs"])
    for d in ("a25504a8149d3", "a6a52b69d2dfc"):
        assert d not in n and d in dropped()


def test_deal_corrections():
    dl = j("deals.json")
    chr_ = next(x for x in dl if (x["buyer"], x["target"]) == ("C.H. Robinson", "RXO"))
    seed = next(x for x in j("seed.json")["deals"] if (x["buyer"], x["target"]) == ("C.H. Robinson", "RXO"))
    assert deal_overlay(seed, chr_)["value"] == "$5.8 billion implied transaction value"   # the overlay reaches the card
    ven = next(x for x in dl if "Venipak" in x["target"])
    assert ven["ann"] == "2026-07-27" and any("dhl.com" in x["url"] for x in ven["srcs"])
    tb = next(x for x in dl if (x["buyer"], x["target"]) == ("Thoma Bravo", "WWEX Group (combined with Auctane)"))
    tbs = next(x for x in j("seed.json")["deals"] if (x["buyer"], x["target"]) == ("Thoma Bravo", "WWEX Group (combined with Auctane)"))
    assert "ShipStation Global" in deal_overlay(tbs, tb)["latest"]


# ---------------------------------------------------------------- B16 / B17 / B19: the feed
def test_no_dropped_story_in_the_feed_or_a_storyline():
    gone = dropped()
    assert not gone & set(news())
    for k, t in j("threads.json").items():
        assert not gone & set(t.get("ids", [])), k
    assert "a418fdd3e6f05" in gone and "a418fdd3e6f05" not in news()


def test_no_feed_story_dated_long_after_its_announcement():
    for s in j("news.json"):
        if not s.get("ann"):
            continue
        late = (dt.date.fromisoformat(s["date"][:10]) - dt.date.fromisoformat(s["ann"][:10])).days
        assert late <= 30 or s.get("kind") in ("Reminder", "Background"), (s["id"], late)


def test_larsen_story_no_longer_links_the_germany_page():
    s = news().get("aba40a11b6946")
    if s is None:                 # held until a real interview link turns up
        assert "aba40a11b6946" in dropped(); return
    urls = [x["url"] for x in s["srcs"]] + [s["url"]]
    assert not any("germany" in u for u in urls)
    assert s["url"] == s["srcs"][0]["url"] and "supplychain247.com" in s["url"]


def test_usps_holiday_story_is_a_dated_reminder():
    s = news()["a6cc2420ad66e"]
    assert s["title"] == "USPS recommends Dec. 17 Ground Advantage send-by date for the lower 48"
    assert s["ann"] == "2026-09-22" and s["kind"] == "Reminder"
    assert s["srcs"][0]["url"].startswith("https://about.usps.com/") and s["url"] == s["srcs"][0]["url"]
    assert any(d["d"] == "2026-12-16" and "AK, HI" in d["w"] for d in s["dates"])   # Alaska and Hawaii kept
    assert "Alaska, Hawaii" in s["sum"]


# ---------------------------------------------------------------- B18: storylines
def test_storyline_lines_rest_on_member_stories():
    P = pool()
    for k, t in j("threads.json").items():
        S = [P[i] for i in t.get("ids", []) if i in P]
        src = " ".join(" ".join(str(s.get(f) or "") for f in ("title", "sum", "plain", "tie", "new", "why", "date", "act", "ann"))
                       for s in S)
        cx = t.get("cx") or {}
        for line in (t.get("s"), cx.get("now"), cx.get("intro")):
            if line:
                assert not numbers_supported(line, src), (k, line)


def test_named_storyline_fixes():
    th = j("threads.json")
    fx = th["fedex-freight-spin"]
    assert "rv5-fedex-freight-spin-done" in fx["ids"]
    assert fx["cx"]["now"] == ("FedEx completed the FedEx Freight spin-off on June 1, 2026. FedEx Freight is an independent "
                               "public company (NYSE: FDXF). FedEx kept 19.9% at separation.")
    assert "nothing here confirms" not in json.dumps(fx) and "CMA CGM" not in json.dumps(fx)
    assert "5.9" not in th["fedex-network-2"]["cx"]["now"]
    assert "peak" not in th["usps-big-shipper-deals"]["cx"]["now"].lower()
    assert "a418fdd3e6f05" not in th["amazon-network-buildout"]["ids"]
    assert "a418fdd3e6f05" not in th["amazon-network-buildout"]["cx"]["beats"]
    assert "not yet announced" not in th["carrier-gri"]["s"] and "w84705482dd2f" in th["carrier-gri"]["ids"]
    st = news()["rv5-fedex-freight-spin-done"]
    assert st["date"] == "2026-06-01" and st["lvl"] == 2 and st["srcs"][0]["url"].startswith("https://newsroom.fedex.com/")


def test_storyline_narration_is_marked_current_for_its_stories():
    """The robots re-narrate a storyline whose stories changed; the hand-checked lines must not be overwritten at once."""
    from common import h
    P = pool()
    for k in ("fedex-freight-spin", "amazon-network-buildout", "carrier-gri"):
        t = j("threads.json")[k]
        assert t["cx"]["sig"] == h(",".join(i for i in t["ids"] if i in P)), k
        assert t["rv"] == h(",".join(t["ids"])), k


# ---------------------------------------------------------------- B21
def test_docs_that_land_on_a_homepage_are_marked_retired():
    names = {("UPS", "2025 UPS Hundredweight rates preview"), ("Veho", "Veho service guide: last-mile delivery"),
             ("GLS US", "GLS US fuel surcharge matrix, effective Dec 15, 2025"), ("GLS US", "GLS US fuel surcharge, Jul 2025"),
             ("GLS US", "GLS US fuel surcharge, ground and priority, Sep 2024"), ("GLS US", "2023 GLS priority rates"),
             ("GLS US", "GLS US 2024 peak season surcharge")}
    docs = {(d["c"], d["n"]): d for d in j("docs.json")}
    for key in names:
        d = docs[key]
        assert d["cur"] is False and d["d"].startswith("Retired by the carrier, last seen"), key


# ---------------------------------------------------------------- the script
def test_script_is_idempotent(data_dir):
    spec = importlib.util.spec_from_file_location("review_v5_data", ROOT / "tools" / "review_v5_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(dry=True) == []
