"""Change audits: program promises (B3), rate clock lines (B5), no robot notes in reader text (B9),
and events that only look alike stay apart (B10). No network, no Claude: the auditor's reply is given."""
import json
import changeaudit as C
import common

SBR_URL = "https://www.ups.com/us/en/shipping/zones-and-rates/small-business-rates"
SBR_OLD = ("UPS Small Business Rates. Our Small Business Rates are inclusive of Delivery Area Surcharge, Fuel Surcharge "
           "and other value-added services. No Address Correction, Shipping Charge Correction Audit or Missing PLD fees.\n") * 3
SBR_NEW = SBR_OLD + ("Effective December 21, 2026, Small Business Rates will increase 4.5%. A 5% fuel surcharge will apply to all "
                     "SBR shipments, domestic and international.\n")


def sbr_reply(**over):
    r = {"verdict": "price change", "material": True, "title": "UPS raises Small Business Rates 4.5% and adds a 5% fuel surcharge",
         "summary": "Effective December 21, 2026, Small Business Rates increase 4.5% and a 5% fuel surcharge applies to all SBR shipments.",
         "effect": "SBR shippers pay more from December 21, 2026.", "imp": "info", "lvl": 1, "category": "Pricing & GRI",
         "act": "2026-12-21",
         "changes": [{"what": "SBR fuel surcharge", "before": None, "after": "A 5% fuel surcharge will apply to all SBR shipments, domestic and international",
                      "effective": "2026-12-21", "who": "SBR shippers", "impact": None,
                      "quote_old": None, "quote_new": "A 5% fuel surcharge will apply to all SBR shipments, domestic and international"},
                     {"what": "Small Business Rates increase", "before": None, "after": "Small Business Rates will increase 4.5%",
                      "effective": "2026-12-21", "who": "SBR shippers", "impact": None,
                      "quote_old": None, "quote_new": "Small Business Rates will increase 4.5%"}],
         "unknowns": []}
    r.update(over)
    return r


# ---------------------------------------------------------------- B3
def test_programs_file_has_the_sourced_sbr_record():
    progs = json.loads((common.ROOT / "data" / "programs.json").read_text())["programs"]
    sbr = next(p for p in progs if p["id"] == "ups-sbr")
    assert sbr["stated"] == "inclusive of Delivery Area Surcharge, Fuel Surcharge and other value-added services"
    assert [i["what"] for i in sbr["no_fees"]] == ["Address Correction", "Shipping Charge Correction Audit", "Missing PLD"]
    for p in progs:
        for i in p["includes"] + p["no_fees"]:
            assert i["src"].startswith("https://") and len(i["checked"]) == 10, i     # every promise is sourced and dated


def test_sbr_fuel_surcharge_is_a_removed_benefit(monkeypatch):
    sent = []
    monkeypatch.setattr(C, "claude", lambda model, system, user, max_tokens=0: sent.append(user) or json.dumps(sbr_reply()))
    res = C.audit("UPS", "Small Business Rates page", SBR_URL, SBR_OLD, SBR_NEW)
    assert "PROGRAM PROMISES" in sent[0] and "inclusive of Delivery Area Surcharge, Fuel Surcharge" in sent[0]
    assert "Removes a stated <program> benefit" in sent[0]
    assert res["imp"] == "up" and res["lvl"] >= 2                         # the model said info / 1; the rule wins
    assert res["why"].startswith("Removes a stated SBR benefit: Fuel Surcharge")
    f = C.story_fields(res, "UPS")
    assert f["why"] == res["why"] and f["imp"] == "up" and f["benefit"]["program"] == "ups-sbr"
    assert f["benefit"]["src"] == SBR_URL and f["benefit"]["checked"] == "2026-10-24"


def test_programs_only_where_named(monkeypatch):
    sent = []
    reply = sbr_reply(title="UPS changes Daily Rates", changes=[], material=False)
    monkeypatch.setattr(C, "claude", lambda model, system, user, max_tokens=0: sent.append(user) or json.dumps(reply))
    C.audit("UPS", "Daily Rate and Service Guide", "https://www.ups.com/daily.pdf", "a", "b")
    assert "PROGRAM PROMISES" not in sent[0]
    assert common.programs_for("FedEx", "UPS Small Business Rates") == []    # another carrier's program never applies


def test_news_text_needs_program_and_charge_in_one_sentence():
    progs = common.programs_for("UPS", "SBR")
    s = {"imp": "info", "lvl": 1, "why": "UPS sets 2027 rates."}
    # a GRI article that mentions SBR and, elsewhere, the fuel surcharge isn't an SBR benefit change
    assert not common.apply_benefit_rule(s, progs, text="UPS raises Daily Rates 5.9% and changes its fuel surcharge table. "
                                                       "Small Business Rates details come later.")
    assert s == {"imp": "info", "lvl": 1, "why": "UPS sets 2027 rates."}
    assert common.apply_benefit_rule(s, progs, text="UPS adds a 5% fuel surcharge to all Small Business Rates shipments from Dec 21.")
    assert s["why"].startswith("Removes a stated SBR benefit: ") and s["imp"] == "up" and s["lvl"] == 2
    removal = {"imp": "down", "lvl": 1}
    assert not common.apply_benefit_rule(removal, progs, text="UPS waives the fuel surcharge on Small Business Rates.")


# ---------------------------------------------------------------- B5
UPS_DEC21 = [
    {"what": "Average Daily Rate increase for UPS Ground, UPS Air and International services", "before": None,
     "after": "Average net increase of 5.9%; detailed rate previews to follow at a later date", "effective": "2026-12-21",
     "who": "Shippers using UPS Ground, UPS Air and International services", "impact": "+5.9% average net"},
    {"what": "Additional Handling minimum billable weight", "before": None, "after": "Increases from 40 lbs. to 50 lbs.",
     "effective": "2026-12-21", "who": "Packages subject to Additional Handling", "impact": "Minimum billable weight +10 lbs. (40 -> 50 lbs.)"},
    {"what": "Area Surcharge ZIP code list", "before": None, "after": "The list of ZIP codes to which Area Surcharges apply will change",
     "effective": "2026-12-21", "who": "Shipments to affected ZIP codes", "impact": None},
]


def test_one_clock_line_per_event_led_by_the_figure():
    lines = C.clock_lines(UPS_DEC21, "UPS", "up")
    assert len(lines) == 1, lines                                          # three Dec 21 lines collapse into one
    assert lines[0]["w"] == "UPS rate increase: 5.9% average (Ground, Air, International)"
    assert [f[1] for f in lines[0]["fees"]] == ["Additional Handling minimum billable weight", "Area Surcharge ZIP code list"]
    assert lines[0]["fees"][0] == ["UPS", "Additional Handling minimum billable weight", "Minimum billable weight +10 lbs. (40 -> 50 lbs.)"]


def test_labels_are_never_cut_and_years_only_when_stated():
    long = {"what": "New per-package surcharge on domestic Ground and Ground Saver shipments from certain origin ZIP codes",
            "after": "Additional surcharge per package for Qualified customers", "effective": "2026-12-21"}
    w = C.clock_lines([long], "UPS", "up")[0]["w"]
    assert w == "UPS: " + long["what"]                                     # no 70-character cut mid-word
    stated = dict(UPS_DEC21[0], what="2027 general rate increase for UPS Ground, UPS Air and International services")
    assert C.gri_label("UPS", stated) == "UPS 2027 rate increase: 5.9% average (Ground, Air, International)"
    assert C.gri_label("UPS", UPS_DEC21[1]) is None                       # not a rate increase
    assert C.gri_label("UPS", dict(UPS_DEC21[0], after="Rates increase; figures later", impact=None)) is None   # no figure, no label


# ---------------------------------------------------------------- B9
def test_robot_notes_are_removed_and_older_version_goes_to_unknowns():
    res = {"title": "UPS raises Additional Handling minimum billable weight",
           "summary": "UPS raises the minimum billable weight to 50 lbs. The OLD excerpt did not contain this item.",
           "effect": "Heavier packages cost more.", "imp": "up", "lvl": 2, "unknowns": ["Fuel table size; not in the supplied text."],
           "changes": [{"what": "Additional Handling minimum billable weight", "before": None,
                        "after": "Increases from 40 lbs. to 50 lbs. (the 40 lb. figure comes from the NEW text; the OLD excerpt did not contain this item)",
                        "effective": "2026-12-21", "who": "Packages subject to Additional Handling",
                        "impact": "Percentages in the old table are not in the text provided, so the size of the move is unknown"}]}
    f = C.story_fields(res, "UPS")
    text = json.dumps(f)
    for bad in ("NEW text", "OLD excerpt", "supplied text", "text provided"):
        assert bad not in text, bad
    assert f["changes"][0]["after"] == "Increases from 40 lbs. to 50 lbs."
    assert f["sum"] == "UPS raises the minimum billable weight to 50 lbs."
    assert f["unknowns"][-1] == "Older version not on file" and "Older version not on file" not in f["plain"]
    assert C.robot_leaks(f) == []


def test_final_pass_catches_stitching_and_what_it_cannot_clean():
    assert C.robot_leaks({"title": "UPS posts tables", "sum": "UPS posted tables. Also: UPS announces changes."})
    f = C.story_fields({"title": "Not in the supplied text.", "summary": "s", "effect": "e", "changes": [], "unknowns": []}, "UPS")
    assert C.robot_leaks(f), "a title that was only robot notes is held, not published as 'UPS change'"


def test_ordinary_words_are_not_robot_notes():
    clean = {"title": "UPS posts new version of its rate guide", "sum": "The previous version of the guide did not include a residential fee.",
             "plain": "Shippers see the new fee.", "changes": [{"what": "Residential fee", "after": "$6.10 per package"}]}
    assert C.robot_leaks(clean) == []


def test_earnings_sync_flags_every_missing_surface():
    import audit
    nxt = {"next": [{"c": "UPS", "q": "Q3 2026", "d": "2026-10-27"}, {"c": "FedEx", "q": "Transition", "d": "2026-10-28"}]}
    rows = [{"company": "UPS", "q": "Q3 2026", "release": "https://r", "vol": None}]
    stories = {"a": {"c": ["UPS"], "cat": "Earnings & markets", "date": "2026-10-27"}}
    got = audit.earnings_sync_issues(rows, nxt, [{"u": "https://r"}], stories, "2026-10-30")
    assert [m.split(":")[0].split(" reported")[0] for _, m, _ in got] == ["UPS Q3 2026", "FedEx"]     # UPS: no volume yet; FedEx: no row
    assert audit.earnings_sync_issues(rows, nxt, [], {}, "2026-10-30")[0][1].startswith("UPS Q3 2026: the release is not filed")
