"""Earnings history (B28, B29, B32, B34): the stored package and revenue figures, the stock reaction windows counted in
trading sessions, new quarters added only from a twice-read release, and how the figures read on the page.
No network: the price series are saved fixtures built from the Yahoo daily closes read on Oct 24, 2026."""
import datetime as dt, json, os, re
import pytest
import earnings as E
from conftest import ROOT

ROWS = json.loads((ROOT / "data" / "earnings.json").read_text())
row = lambda c, q: next(r for r in ROWS if r["company"] == c and r["q"] == q)

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
    det = pg.inner_text('.eglance[data-eco="UPS"] .egdet')
    for want in ("$22.83B · +7.6% vs a year earlier", "19.0 million a day", "−3.7%", "U.S. domestic 16.0 million",
                 "about 1.22 billion in the quarter (calculated: 64 operating days)", "$15.96 · +11.3%",
                 "Stock, first trading day after the report: −6.6% (S&P 500 +0.2%)", "about a month −6.9% (S&P 500 +3.6%)", "Not investment advice"):
        assert want in det, (want, det)
    got = pg.evaluate("""() => {
      // a FedEx quarter with packages a day but no stated day count, a FedEx Freight quarter, a transition period and a bare row
      EARN.push({company:'FedEx', q:'T1', d:'2026-10-28', rev:21.5, period:{start:'2026-06-01', end:'2026-09-30', months:4}, comparable:false, revYoY:4.0,
                 vol:{adv_k:16000, adv_prior_k:15500, days:null, pieces_m:null, us_adv_k:13000, rpp:null, src:'https://example.com/x', checked:'2026-10-30'}},
                {company:'FedEx Freight', q:'F1', d:'2026-10-29', rev:2.1},
                {company:'UPS', q:'Bare 1', d:'2026-10-27', rev:21.0});
      goTo('docs','earnings','FedEx','T1');
      const fx = document.querySelector('.eglance[data-eco="FedEx"] .egdet').innerText;
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
    assert "16.0 million a day" in got["fx"] and "in the quarter" not in got["fx"]          # no stated days: no total
    assert "4-month period; not compared with a year earlier" in got["fx"] and "+4.0%" not in got["fx"]
    assert got["ff"]["views"] == 0 and "Packages" not in got["ff"]["text"]                 # FedEx Freight: no package view
    assert "$21.0B" in got["bare"] and "Packages" in got["bare"] and "—" in got["bare"]   # a bare row still renders
    assert all(same for _, _, same in got["charts"]) and len({c for c, _, _ in got["charts"]}) == len(got["charts"])
    assert got["hatched"] and got["divider"]
    assert pg.errors == []
