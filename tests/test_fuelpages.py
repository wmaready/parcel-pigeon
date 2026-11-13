"""UPS and FedEx weekly fuel from the carriers' own pages (pipeline/fuelpages.py), including international."""
import json
import pytest
import fuelpages as F
from common import load, save
from conftest import ROOT

CUR = (ROOT / "tests" / "fixtures" / "fedex_fuel_current.txt").read_text()       # FedEx's page as read on Oct 26, 2026
HIS = (ROOT / "tests" / "fixtures" / "fedex_fuel_history.txt").read_text()


def test_fedex_page_gives_every_week_with_international():
    w = F.fedex_weeks(CUR, HIS)
    assert len(w) == 14 and min(w) == "2026-07-27" and max(w) == "2026-10-26"
    assert w["2026-10-26"] == {"ground": 29.0, "air": 32.5, "intl": 45.0}              # next week, posted ahead
    assert w["2026-10-19"] == {"ground": 28.75, "air": 32.0, "intl": 44.5}
    assert w["2026-09-28"] == {"ground": 29.75, "air": 33.0, "intl": 45.5}             # a week with "Sept." in its dates
    # week-over-week, from real consecutive weeks: ground +0.25 on Oct 26, international +0.5
    assert round(w["2026-10-26"]["ground"] - w["2026-10-19"]["ground"], 2) == 0.25
    assert round(w["2026-10-26"]["intl"] - w["2026-10-19"]["intl"], 2) == 0.5


def test_a_row_that_doesnt_check_out_refuses_the_whole_read():
    bad = HIS.replace("Oct. 12, 2026–Oct. 18, 2026 | 28.75%", "Oct. 13, 2026–Oct. 18, 2026 | 28.75%")        # not a Monday
    with pytest.raises(ValueError):
        F.fedex_weeks(CUR, bad)
    with pytest.raises(ValueError):
        F.fedex_weeks(CUR, HIS.replace("| 29.25% |", "| 29.30% |"))                                       # not a 0.25 step
    gap = "\n".join(l for l in HIS.splitlines() if "Sept. 21, 2026–Sept. 27" not in l)
    with pytest.raises(ValueError):
        F.fedex_weeks(CUR, gap)                                                                          # a missing week


def ups_page(rows, heads=F.UPS_COLS):
    return "90-Day Fuel Surcharge History\nEffective Start Date | " + " | ".join(heads) + "\n" + "\n".join(rows)


def test_ups_history_table_five_columns():
    rows = [f"{d} | {a}% | {b}% | {c}% | {e}% | {g}%" for d, a, b, c, e, g in [
        ("Oct 26, 2026", 29.5, 32.75, 45.75, 48.75, 30.25), ("Oct 19, 2026", 29.25, 32.5, 45.5, 48.5, 30.25), ("Oct 12, 2026", 29.0, 32.25, 45.25, 48.25, 30.0),
        ("Oct 5, 2026", 29.5, 31.75, 45.0, 48.0, 30.25), ("Sep 28, 2026", 30.0, 33.0, 46.0, 49.0, 30.5), ("Sep 21, 2026", 29.25, 32.25, 45.25, 48.25, 30.25),
        ("Sep 14, 2026", 28.25, 30.5, 43.25, 46.25, 29.25), ("Sep 7, 2026", 27.25, 28.75, 41.0, 44.0, 28.25)]]
    w = F.ups_weeks(ups_page(rows))
    assert len(w) == 8 and w["2026-10-26"] == {"ground": 29.5, "air": 32.75, "intlExport": 45.75, "intlImport": 48.75, "intlGround": 30.25}
    with pytest.raises(ValueError):                                      # headings out of order: refuse rather than shift columns
        F.ups_weeks(ups_page(rows, heads=list(reversed(F.UPS_COLS))))
    with pytest.raises(ValueError):                                      # the page's script table never loaded: no rows
        F.ups_weeks(ups_page([]))


def test_merge_puts_every_service_into_the_weekly_history(data_dir):
    fuel = {}
    F.merge(fuel, "FedEx", F.fedex_weeks(CUR, HIS), F.FEDEX_MAP, "2026-10-26")
    assert fuel["hist2"]["FedEx"]["intlExport"]["2026-10-19"] == 44.5 and fuel["hist2"]["FedEx"]["intlGround"]["2026-10-19"] == 28.75
    assert fuel["current"]["FedEx"] == {"ground": 29.0, "air": 32.5, "intlExport": 45.0, "intlImport": 45.0, "intlGround": 29.0} and fuel["eff"]["FedEx"] == "2026-10-26"
    assert fuel["health"]["FedEx"]["ok"] and fuel["health"]["FedEx"]["via"] == "page" and fuel["health"]["FedEx"]["latest"] == "2026-10-26"


def test_a_failed_page_is_loud_and_keeps_what_is_on_file(data_dir, capsys):
    save("fuel.json", {"hist": {"UPS": {"2026-10-19": 29.25}}, "health": {"UPS": {"ok": True, "via": "page", "last_ok": "2026-10-20T01:00Z", "latest": "2026-10-19"}}})
    def boom(u):
        raise RuntimeError("blocked")
    F.main(fetch_text=lambda u: CUR if "historical" not in u else HIS, render_text=boom)
    f = load("fuel.json", {})
    assert f["health"]["FedEx"]["ok"] and not f["health"]["UPS"]["ok"] and f["health"]["UPS"]["last_ok"] == "2026-10-20T01:00Z"
    assert f["hist"]["UPS"] == {"2026-10-19": 29.25}                                   # nothing overwritten
    assert "::warning title=UPS fuel page::" in capsys.readouterr().out


def test_a_failed_page_never_hides_a_good_fuel_price_service_read(data_dir, capsys):
    """Oct 26, 2026: the hourly page read failed for UPS 40 minutes after the OilPriceAPI read had worked and marked UPS failed, though
    its numbers were fine. The page miss is noted next to the good read; the next update run still uses the service."""
    save("fuel.json", {"hist": {"UPS": {"2026-10-19": 29.25}}, "health": {"UPS": {"ok": True, "at": "2026-10-26T20:55Z", "last_ok": "2026-10-26T20:55Z"}}})
    def boom(u):
        raise RuntimeError("could not render the page: Page.goto: Download is starting")
    F.main(fetch_text=lambda u: CUR if "historical" not in u else HIS, render_text=boom)
    h = load("fuel.json", {})["health"]["UPS"]
    assert h["ok"] and h.get("via") != "page" and "Download is starting" in h["page_why"]
    assert F.UPS_URL.endswith("/fuel-surcharges")                       # the ".page" address makes a browser start a download
