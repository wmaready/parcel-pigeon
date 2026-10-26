"""Earnings history (B28, B29, B32, B34): the stored package and revenue figures, the stock reaction windows counted in
trading sessions, new quarters added only from a twice-read release, and how the figures read on the page.
No network: the price series are saved fixtures built from the Yahoo daily closes read on Oct 24, 2026."""
import datetime as dt, json, os, re
import pytest
import earnings as E
from conftest import ROOT

ROWS = json.loads((ROOT / "data" / "earnings.json").read_text())
row = lambda c, q: next(r for r in ROWS if r["company"] == c and r["q"] == q)
row_of = lambda rows, c, q: next(r for r in rows if r["company"] == c and r["q"] == q)

# NYSE holidays inside the fixture windows: Juneteenth (Fri Jun 19, 2026) and Independence Day observed (Fri Jul 3, 2026)
HOLIDAYS = {"2026-06-19", "2026-07-03"}


def sessions(start, end):
    d, out = dt.date.fromisoformat(start), []
    while d <= dt.date.fromisoformat(end):
        if d.weekday() < 5 and d.isoformat() not in HOLIDAYS:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def priced(base_d, base_c, moves, start, end):
    """A daily-close series: flat at the base close except on the dates in moves ({date: percent from base})."""
    out = []
    for d in sessions(start, end):
        c = round(base_c * (1 + moves[d] / 100), 2) if d in moves else base_c
        out.append((d, c))
    for d, p in moves.items():                     # the fixture reproduces the read figures exactly
        assert E.pct(dict(out)[d], base_c) == p, (d, p)
    return out


# Yahoo daily closes read Oct 24, 2026 (brief B28): base, 1, 5 and 21 sessions; the S&P 500 index level is a stand-in
FDX = priced("2026-06-23", 317.24, {"2026-06-24": -0.13, "2026-06-30": -1.30, "2026-07-23": -0.51}, "2026-06-08", "2026-08-07")
FDX_SPX = priced("2026-06-23", 6000.0, {"2026-06-24": -0.10, "2026-06-30": 1.82, "2026-07-23": 0.58}, "2026-06-08", "2026-08-07")
UPS = priced("2026-07-27", 112.95, {"2026-07-28": -6.57, "2026-08-03": -5.38, "2026-08-25": -6.91}, "2026-07-13", "2026-09-11")
UPS_SPX = priced("2026-07-27", 6300.0, {"2026-07-28": 0.21, "2026-08-03": 2.53, "2026-08-25": 3.56}, "2026-07-13", "2026-09-11")


def test_fedex_after_close_counts_trading_sessions():
    rx = E.reaction(FDX, FDX_SPX, "2026-06-23", "post", "2026-10-24")
    assert rx["base"] == {"d": "2026-06-23", "c": 317.24}
    assert rx["d1"] == {"d": "2026-06-24", "pct": -0.13, "spx": -0.10}
    assert rx["d5"] == {"d": "2026-06-30", "pct": -1.30, "spx": 1.82}
    assert rx["d21"] == {"d": "2026-07-23", "pct": -0.51, "spx": 0.58}      # skips the Jul 3 closure
    assert rx["final"] is True
    days = [x[0] for x in rx["series"]]
    assert days[0] == "2026-06-15" and "2026-06-19" not in days and days[5] == "2026-06-23"   # 5 sessions before, not Juneteenth


def test_ups_before_open_uses_the_previous_close():
    rx = E.reaction(UPS, UPS_SPX, "2026-07-28", "pre", "2026-10-24")
    assert rx["base"] == {"d": "2026-07-27", "c": 112.95}
    assert rx["d1"] == {"d": "2026-07-28", "pct": -6.57, "spx": 0.21}
    assert rx["d5"] == {"d": "2026-08-03", "pct": -5.38, "spx": 2.53}
    assert rx["d21"] == {"d": "2026-08-25", "pct": -6.91, "spx": 3.56}
    assert rx["final"] is True


def test_stored_reactions_match_the_fixtures():
    for (c, q), (px, sp, d, ses) in {("UPS", "Q2 2026"): (UPS, UPS_SPX, "2026-07-28", "pre"),
                                     ("FedEx", "FY26 Q4"): (FDX, FDX_SPX, "2026-06-23", "post")}.items():
        got, stored = E.reaction(px, sp, d, ses, "2026-10-24"), row(c, q)["rx"]
        for k in ("base", "d1", "d5", "d21", "final"):
            assert stored[k] == got[k], (c, k)
        assert E.session_of(row(c, q)) == ses


def test_ten_sessions_in_is_not_final_and_has_no_month():
    short = [x for x in UPS if x[0] <= sessions("2026-07-28", "2026-09-11")[9]]
    rx = E.reaction(short, UPS_SPX, "2026-07-28", "pre", "2026-10-24")
    assert rx["final"] is False and "d21" not in rx and rx["d5"]["pct"] == -5.38


def test_todays_bar_waits_until_tomorrow():
    rx = E.reaction(UPS, UPS_SPX, "2026-07-28", "pre", "2026-07-28")
    assert rx is None                                # only today's (possibly unfinished) session after the base


def test_final_rows_are_never_rewritten_and_failures_keep_the_last_figures():
    rows = json.loads(json.dumps(ROWS))
    final = json.dumps(row("UPS", "Q2 2026")["rx"])
    calls = []

    def moved(sym, lo, hi):                          # a series that would give different numbers
        calls.append(sym)
        base = UPS if sym == "UPS" else FDX if sym == "FDX" else UPS_SPX
        return [(d, round(c * 1.5, 2)) for d, c in base]
    E.update_reactions(rows, "2026-10-24", fetch=moved)
    up = next(r for r in rows if r["company"] == "UPS" and r["q"] == "Q2 2026")
    assert json.dumps(up["rx"]) == final

    rows = json.loads(json.dumps(ROWS))
    rows.append({"company": "UPS", "q": "Q3 2026", "d": "2026-10-27", "rev": 21.0, "rx": {"src": "Yahoo daily close", "d1": {"d": "2026-10-27", "pct": 1.0, "spx": 0.5}, "final": False}})

    def broken(sym, lo, hi):
        raise RuntimeError("blocked")
    fails = E.update_reactions(rows, "2026-10-29", fetch=broken)
    assert fails and rows[-1]["rx"]["d1"]["pct"] == 1.0          # kept, never zeroed


def test_ups_q2_2026_package_and_revenue_fixture():
    r = row("UPS", "Q2 2026")
    assert (r["rev_m"], r["rev_prior_m"], r["revYoY"]) == (22834, 21221, 7.6)
    v = r["vol"]
    assert (v["adv_k"], v["adv_prior_k"], v["adv_yoy"], v["days"]) == (19006, 19741, -3.7, 64)
    assert (v["us_adv_k"], v["us_adv_prior_k"], v["rpp"], v["rpp_prior"]) == (16002, 16553, 15.96, 14.34)
    assert v["pieces_m"] == round(v["adv_k"] * v["days"] / 1000, 1) == 1216.4 and v["pieces_src"] == "calc"
    assert v["src"] == r["filing"] and v["checked"] == "2026-10-24"
    assert round((v["us_adv_k"] / v["us_adv_prior_k"] - 1) * 100, 1) == -3.3
    assert round((v["rpp"] / v["rpp_prior"] - 1) * 100, 1) == 11.3


def test_every_stored_figure_has_its_source_and_check_date():
    assert E.vol_problems(ROWS) == []
    for r in ROWS:
        assert r.get("period") and r.get("label"), r["q"]
        if r.get("rx"):
            assert r["rx"].get("src") and r["rx"].get("checked"), r["q"]
        if r["company"] == "FedEx Freight":
            assert r.get("vol") is None
        if r["company"] == "FedEx" and r["period"]["start"] < E.SPLIT:
            assert "include Freight" in r.get("note", "")
    assert row("FedEx", "FY26 Q4")["revYoY"] == 12.6 and row("FedEx", "FY26 Q4")["yoy_src"] == "calc"
    assert E.vol_problems([{"company": "UPS", "q": "x", "vol": {"adv_k": 1}}]) == ["UPS x"]


def test_fedex_fiscal_year_data_check(tmp_path):
    rows = [{"company": "FedEx", "q": f"FY26 Q{i}", "vol": {"adv_k": v}} for i, v in zip(range(1, 5), (17300, 17500, 17600, 17800))]
    review = []
    assert E.fedex_fy_check(rows, review) == [] and review == []            # averages 17,550: within 3% of 17,558
    rows[3]["vol"]["adv_k"] = 21000
    assert E.fedex_fy_check(rows, review) == ["FY26"] and review[0]["type"] == "earnings-check"
    rows[0]["vol"] = None
    assert E.fedex_fy_check(rows, []) == []                                 # not checkable until all four are in


def test_yoy_fill_and_periods_that_are_not_comparable():
    rows = [{"company": "UPS", "q": "a", "revYoY": None, "rev_m": 22834, "rev_prior_m": 21221},
            {"company": "FedEx", "q": "b", "revYoY": 5.0, "yoy_src": "calc", "comparable": False}]
    E.fill_yoy(rows)
    assert rows[0]["revYoY"] == 7.6 and rows[0]["yoy_src"] == "calc"
    assert rows[1]["revYoY"] is None


RELEASE = """<html><head><title>UPS Releases 3Q 2026 Earnings</title></head><body><h1>UPS Releases 3Q 2026 Earnings</h1>
<p>Consolidated revenue of $21.9 billion. Adjusted diluted earnings per share of $1.81.</p></body></html>"""
LIST = '<a href="/news-events/press-releases/detail/2170/ups-releases-3q-2026-earnings">UPS Releases 3Q 2026</a>'
NXT = {"next": [{"c": "UPS", "q": "Q3 2026", "d": "2026-10-27", "match": "ups-releases-3q-2026-earnings", "label": "Q3 2026",
                 "period": {"start": "2026-07-01", "end": "2026-09-30", "months": 3}},
                {"c": "FedEx", "q": "Jun–Sep 2026 transition period", "d": "2026-10-28", "match": None, "label": "Transition period (Jun–Sep 2026)",
                 "period": {"start": "2026-06-01", "end": "2026-09-30", "months": 4}}],
       "ir": {"UPS": "https://investors.ups.com/news-events/press-releases"}}


def test_new_quarter_added_unchecked_after_two_matching_reads():
    pages = {"https://investors.ups.com/news-events/press-releases": LIST,
             "https://investors.ups.com/news-events/press-releases/detail/2170/ups-releases-3q-2026-earnings": RELEASE}
    rows, review = [], []
    added = E.add_new_quarters(rows, NXT, review, "2026-10-27", fetch=pages.__getitem__, pause=0)
    assert added == ["UPS Q3 2026"]
    r = rows[0]
    assert (r["rev"], r["eps"], r["checked"], r["vol"], r["comparable"]) == (21.9, 1.81, False, None, True)
    assert r["release"].endswith("ups-releases-3q-2026-earnings")
    assert any(x["type"] == "earnings-new" for x in review)
    assert E.add_new_quarters(rows, NXT, review, "2026-10-27", fetch=pages.__getitem__, pause=0) == []   # never twice


def test_release_reads_that_disagree_go_to_review():
    reads = iter([RELEASE, RELEASE.replace("$21.9", "$22.9")])
    def fetch(u):
        return LIST if u.endswith("press-releases") else next(reads)
    rows, review = [], []
    assert E.add_new_quarters(rows, NXT, review, "2026-10-28", fetch=fetch, pause=0) == []
    assert rows == [] and any(x["type"] == "earnings-unconfirmed" for x in review)
    assert any(x["type"] == "earnings-missing" and x["company"] == "FedEx" for x in review)   # no automatic source: by hand


def test_no_code_divides_revenue_by_packages():
    src = (ROOT / "pipeline" / "earnings.py").read_text() + (ROOT / "index.html").read_text()
    assert not re.search(r"rev(?:_m)?\s*/\s*\(?\s*(?:\w+\.)?(?:adv_k|pieces_m)", src)
    assert not re.search(r"(?:earnRev\(e\)|rev_m)\s*/\s*(?:v|e\.vol)\.(?:adv_k|pieces_m)", src)


@pytest.fixture
def page_at():
    """The app in a real browser at a given width, served from this folder, with every outside request blocked."""
    pw = pytest.importorskip("playwright.sync_api")
    import functools, http.server, threading
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    handler = functools.partial(Quiet, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = pw.sync_playwright().start()
    b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)

    def open_(width):
        pg = b.new_page(viewport={"width": width, "height": 860})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.add_init_script("try { localStorage.setItem('pw-tour', 'done') } catch (e) {}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html", wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && EARN_NEXT.length && EARN.some(e => e.vol)", timeout=60000)
        return pg
    yield open_
    b.close(); p.stop(); srv.shutdown()


def test_page_shows_the_figures_as_printed(page_at):
    pg = page_at(390)
    pg.evaluate("() => goTo('docs','earnings','UPS','Q2 2026')")
    pg.wait_for_timeout(500)
    det = pg.text_content('.eglance[data-eco="UPS"] .egdet')
    # three figures with their change, then the take and one row of links: no paragraphs of small print
    for want in ("Q2 2026", "Reported Jul 28, 2026", "Revenue", "$22.83B", "+7.6%", "Packages a day", "19.0M", "−3.7%", "U.S. 16.0M",
                 "Revenue per package", "$15.96", "+11.3%", "Release", "10-Q / 10-K"):
        assert want in det, (want, det)
    assert "checked" not in det and "calculated" not in det and "billion in the quarter" not in det
    about = pg.text_content('.eglance[data-eco="UPS"] .egabout')                # how figures are counted: one fold
    assert "operating day" in about and "never estimated" in about and "last checked" in about
    # the earnings page carries no stock lines or stock chart
    assert "Stock" not in det and not pg.query_selector('.eglance .egrx, .eglance .egstock')
    got = pg.evaluate("""() => {
      // a FedEx quarter with packages a day but no stated day count, a FedEx Freight quarter, a transition period and a bare row
      EARN.push({company:'FedEx', q:'T1', d:'2026-10-28', rev:21.5, period:{start:'2026-06-01', end:'2026-09-30', months:4}, comparable:false, revYoY:4.0,
                 vol:{adv_k:16000, adv_prior_k:15500, days:null, pieces_m:null, us_adv_k:13000, rpp:null, src:'https://example.com/x', checked:'2026-10-30'}},
                {company:'FedEx Freight', q:'F1', d:'2026-10-29', rev:2.1},
                {company:'UPS', q:'Bare 1', d:'2026-10-27', rev:21.0});
      goTo('docs','earnings','FedEx','T1');
      const fx = document.querySelector('.eglance[data-eco="FedEx"] .egdet').textContent;
      const ff = document.querySelector('.eglance[data-eco="FedEx Freight"]');
      earnSelect('UPS', 'Bare 1');
      const bare = document.querySelector('.eglance[data-eco="UPS"] .egdet').textContent;
      earnView('adv');
      const charts = [...document.querySelectorAll('.eglance')].map(g => [g.dataset.eco, g.querySelectorAll('.egbar').length,
        [...g.querySelectorAll('.egbar')].map(b => b.dataset.eco).every(c => c === g.dataset.eco)]);
      const hatched = !!document.querySelector('.eglance[data-eco="FedEx"] .egbar[data-ebar="T1"] .eghat') || null;
      earnView('rev');
      return {fx, ff: ff && {views: ff.querySelectorAll('[data-eview]').length, text: ff.innerText}, bare, charts,
              hatched: !!document.querySelector('.eglance[data-eco="FedEx"] .egbar[data-ebar="T1"] .eghat'),
              divider: !!document.querySelector('.eglance[data-eco="FedEx"] .egdiv')}
    }""")
    assert "16.0M" in got["fx"] and "U.S. 13.0M" in got["fx"]
    assert "not comparable" in got["fx"] and "+4.0%" not in got["fx"]                      # a 4-month period: no year-over-year
    assert got["ff"]["views"] == 0 and "Packages" not in got["ff"]["text"]                 # FedEx Freight: no package view
    assert "$21.0B" in got["bare"] and "Packages" in got["bare"] and "—" in got["bare"]   # a bare row still renders
    assert all(same for _, _, same in got["charts"]) and len({c for c, _, _ in got["charts"]}) == len(got["charts"])
    assert got["hatched"] and got["divider"]
    assert pg.errors == []


def test_package_backfill_from_the_carriers_own_reports():
    """Oct 25, 2026 backfill (tools/backfill_volumes.py): figures as printed by each carrier, calculated ones marked."""
    f = row("FedEx", "FY26 Q4")["vol"]                       # Q4 FY26 stat book, Federal Express segment
    assert (f["adv_k"], f["adv_prior_k"], f["us_adv_k"], f["us_adv_prior_k"], f["rpp"], f["rpp_prior"]) == (17083, 16794, 14225, 13826, 17.9, 16.14)
    assert "Stat-Book" in f["src"] and "adv_src" not in f
    u = row("UPS", "Q1 2024")["vol"]                         # the Q1 2024 10-Q
    assert (u["adv_k"], u["adv_prior_k"], u["days"], u["us_adv_k"], u["rpp"]) == (21199, 21989, 63, 18075, 13.73)
    q4 = row("UPS", "Q4 2025")["vol"]                        # not printed on its own: calculated, and says so
    assert q4["adv_src"] == "calc" and q4["adv_note"].startswith("Calculated") and q4["rpp"] == 14.61 and q4["rpp_src"] == "calc"
    assert q4["us_adv_k"] == 19970 and q4["us_adv_prior_k"] == row("UPS", "Q4 2024")["vol"]["us_adv_k"] == 22382   # UPS's own Q4 figures
    s = row("USPS", "FY26 Q3")                               # USPS Q3 FY26 results release
    assert (s["rev_m"], s["rev_prior_m"], s["vol"]["pieces_m"], s["vol"]["pieces_prior_m"], s["vol"]["adv_yoy"]) == (19940, 18797, 1554, 1609, -3.4)
    assert s["vol"]["adv_src"] == "calc" and s["vol"]["days"] == 91 and s["vol"]["rpp"] == 5.31 and s["vol"]["rpp_src"] == "calc"
    assert all((r.get("vol") or {}).get("src") and r["vol"].get("checked") for r in ROWS if r["company"] in ("UPS", "FedEx", "USPS"))


def _ups_10q(adv="18,500", adv_prior="19,419", adv_yoy="(4.7)"):
    """A UPS 10-Q's operating statistics as SEC serves them (tables), for a made-up Q3 2026."""
    tr = lambda *c: "<tr>" + "".join(f"<td>{x}</td>" for x in c) + "</tr>"
    return ("<html><body><table>" + tr("Operating Days", "64", "64", "190", "190")
            + tr("Average Daily Package Volume (in thousands)", adv, adv_prior, adv_yoy, "%")
            + tr("Average Revenue Per Piece", "$", "16.10", "$", "14.82", "$", "1.28", "8.6", "%")
            + "</table><table>" + tr("Total Average Daily Package Volume", "15,500", "16,150", "(4.0)", "%") + "</table></body></html>")


def _sec(doc):
    subs = {"filings": {"recent": {"form": ["8-K", "10-Q"], "reportDate": ["2026-10-27", "2026-09-30"],
                                   "accessionNumber": ["0001-26-1", "0001-26-2"], "primaryDocument": ["x.htm", "ups-20260930.htm"]}}}
    return lambda url: json.dumps(subs) if "submissions" in url else doc


def _q3_rows():
    rows = json.loads(json.dumps(ROWS))
    rows.append({"company": "UPS", "q": "Q3 2026", "d": "2026-10-27", "rev": 21.9, "period": {"start": "2026-07-01", "end": "2026-09-30", "months": 3},
                 "vol": None, "checked": False})
    return rows


def test_new_ups_quarter_takes_packages_from_its_10q():
    rows, review = _q3_rows(), []
    done = E.fill_packages(rows, review, "2026-10-28", fetch=_sec(_ups_10q()), fedex_page="")
    v = row_of(rows, "UPS", "Q3 2026")["vol"]
    assert done == ["UPS Q3 2026"] and not review
    assert (v["adv_k"], v["adv_prior_k"], v["adv_yoy"], v["days"], v["us_adv_k"], v["rpp"]) == (18500, 19419, -4.7, 64, 15500, 16.1)
    assert v["src"] == "https://www.sec.gov/Archives/edgar/data/1090727/0001262/ups-20260930.htm" and v["checked"] == "2026-10-28" and v["auto"] is True


def test_a_10q_that_doesnt_check_out_goes_to_review():
    rows, review = _q3_rows(), []
    # last year's figure in the filing differs from the one on file: nothing is entered
    assert E.fill_packages(rows, review, "2026-10-28", fetch=_sec(_ups_10q(adv_prior="19,500", adv_yoy="(5.1)")), fedex_page="") == []
    assert row_of(rows, "UPS", "Q3 2026")["vol"] is None and review and review[0]["type"] == "earnings-check"
    # a printed change that doesn't match its own figures: nothing is entered either
    rows, review = _q3_rows(), []
    assert E.fill_packages(rows, review, "2026-10-28", fetch=_sec(_ups_10q(adv_yoy="(2.0)")), fedex_page="") == []
    assert row_of(rows, "UPS", "Q3 2026")["vol"] is None and review


def test_a_10q_not_filed_yet_waits_quietly():
    rows, review = _q3_rows(), []
    subs = {"filings": {"recent": {"form": ["8-K"], "reportDate": ["2026-10-27"], "accessionNumber": ["1"], "primaryDocument": ["x.htm"]}}}
    assert E.fill_packages(rows, review, "2026-10-27", fetch=lambda u: json.dumps(subs), fedex_page="") == [] and not review


def test_fedex_statbook_goes_to_review_with_its_link():
    rows, review = json.loads(json.dumps(ROWS)), []
    rows.append({"company": "FedEx", "q": "Jun–Sep 2026 transition period", "d": "2026-10-28", "vol": None, "checked": False,
                 "period": {"start": "2026-06-01", "end": "2026-09-30", "months": 4}})
    page = '<a href="https://s21.q4cdn.com/665674268/files/doc_financials/2026/tp/FedEx-Transition-Stat-Book.pdf">Stat Book</a>'
    E.fill_packages(rows, review, "2026-10-29", fetch=lambda u: (_ for _ in ()).throw(AssertionError("no SEC read for FedEx")), fedex_page=page)
    assert review and review[0]["url"].endswith("FedEx-Transition-Stat-Book.pdf") and row_of(rows, "FedEx", "Jun–Sep 2026 transition period")["vol"] is None


def test_fedex_package_views_say_freight_is_not_in_them():
    """Oct 26, 2026: FedEx Freight separated on June 1, 2026; the package figures were always the Federal Express segment."""
    import re as _re
    assert 'egfrt' in (ROOT / "index.html").read_text() and "reports shipments, not packages" in (ROOT / "index.html").read_text()


def test_usps_expected_date_is_never_read_from_a_page_and_asks_a_person_when_late():
    rows, review = [], []
    nxt = {"next": [{"c": "USPS", "q": "FY26 Q4", "d": "2026-11-14", "est": True, "match": None}], "ir": {"USPS": "https://about.usps.com/newsroom/national-releases/"}}
    def boom(url):
        raise AssertionError("no page is read for an expected date")
    assert E.add_new_quarters(rows, nxt, review, "2026-11-20", fetch=boom, pause=0) == [] and not review      # a few days late: wait
    assert E.add_new_quarters(rows, nxt, review, "2026-11-25", fetch=boom, pause=0) == []
    assert [r["type"] for r in review] == ["earnings-missing"] and "USPS" in review[0]["note"]
    d = json.loads((ROOT / "data" / "earnings_next.json").read_text())
    u = next(x for x in d["next"] if x["c"] == "USPS")
    assert u["est"] is True and "doesn't announce" in u["t"]


def test_ups_q4_and_usps_revenue_per_package_are_calculated_and_labeled():
    """UPS prints no Q4 revenue per piece; it is the 10-K's full year less the first three quarters. USPS reports segment
    revenue and pieces, so its figure is revenue over pieces. Both are marked as calculated."""
    import json
    from conftest import ROOT
    rows = {(r["company"], r["q"]): r["vol"] for r in json.loads((ROOT / "data/earnings.json").read_text())}
    assert rows[("UPS", "Q4 2024")]["rpp"] == 13.44 and rows[("UPS", "Q4 2025")]["rpp"] == 14.61
    assert rows[("UPS", "Q4 2025")]["rpp_prior"] == 13.44 and rows[("UPS", "Q4 2025")]["rpp_src"] == "calc"
    assert rows[("USPS", "FY26 Q3")]["rpp"] == round(8250 / 1554, 2) and rows[("USPS", "FY26 Q3")]["rpp_src"] == "calc"
    assert "isn't comparable" in rows[("USPS", "FY26 Q3")]["rpp_note"]
    import filings
    year = {"days": 253, "adv": 22418, "rpp": 13.60}
    qs = [rows[("UPS", f"Q{i} 2024")] for i in (1, 2, 3)]
    assert filings.q4_rpp(year, qs) == 13.44 and filings.q4_rpp({"days": 253, "adv": 22418}, qs) is None
