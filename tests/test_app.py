"""The app itself: its code parses, and it loads and opens every tab in a real browser with no errors."""
import functools, http.server, os, re, shutil, subprocess, threading
import pytest
from conftest import ROOT


def test_app_javascript_parses(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    html = (ROOT / "index.html").read_text()
    blocks = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)
    js = tmp_path / "app.js"
    js.write_text("\n;\n".join(b for b in blocks if not b.strip().startswith("{")))
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


# elements that stick out past the right edge of the screen (the innermost ones, so the report names the real culprit)
OVERFLOW = """() => { const W = document.documentElement.clientWidth; if (document.documentElement.scrollWidth <= W) return null;
  const out = []; for (const el of document.querySelectorAll('body *')) { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    let clipped = false;      // inside a box that hides its overflow (a ticker, a scrolling table): it can't widen the page
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) { const ox = getComputedStyle(a).overflowX;
      if (ox !== 'visible' && a.getBoundingClientRect().right <= W + 1) { clipped = true; break } }
    if (!clipped && r.width > 0 && r.right > W + 1 && cs.position !== 'fixed' && cs.visibility !== 'hidden'
        && ![...el.children].some(c => c.getBoundingClientRect().right > W + 1))
      out.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '') + ' right=' + Math.round(r.right) + ' "' + (el.textContent || '').trim().slice(0, 40) + '"'); }
  return [document.documentElement.scrollWidth, W, out.slice(0, 6)] }"""


@pytest.mark.parametrize("width", [390, 1280])
def test_app_loads_every_tab(site, width):
    pw = pytest.importorskip("playwright.sync_api")
    exe = os.environ.get("PP_CHROMIUM") or None
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe)
        pg = b.new_page(viewport={"width": width, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())     # the test never leaves this machine
        pg.goto(site, wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100", timeout=60000)
        wide = {}
        for tab in ("today", "news", "mna", "clock", "fuel", "docs", "years"):
            if tab == "years":
                pg.evaluate("() => setView.clock && setView.clock('years')")
                pg.wait_for_function("() => document.querySelector('#clockYears .ayt')", timeout=20000)
            else:
                pg.click(f'nav.tabs [data-tab="{tab}"]')
                pg.wait_for_timeout(400)
            over = pg.evaluate(OVERFLOW)
            if over:
                wide[tab] = over
        b.close()
    assert not errors, errors[:5]
    assert not wide, f"the page scrolls sideways (tab: elements past the right edge): {wide}"


def test_company_page(site):
    """A shared company link opens the full page with its timeline; a story opens on top and Back returns to the company."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page(viewport={"width": 390, "height": 860})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.goto(site + "#c=ups", wait_until="load", timeout=60000)
        pg.wait_for_function("() => document.querySelector('#coSheet.open .cpage .coyr li')", timeout=60000)
        assert pg.evaluate("() => CO_OPEN") == "ups"
        pg.evaluate("() => document.querySelector('#coSheet .coyr li[data-open]').click()")
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => STORY_OPEN != null && CO_OPEN === 'ups'")
        pg.go_back()
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => STORY_OPEN == null && CO_OPEN === 'ups' && !$('coSheet').hidden")
        pg.evaluate("() => [...document.querySelectorAll('#coSheet [data-pl]')].find(x => x.dataset.pl !== 'ups').click()")
        pg.wait_for_timeout(400)
        assert pg.evaluate("() => CO_OPEN") not in (None, "ups")
        wide = pg.evaluate(OVERFLOW)
        b.close()
    assert not errors, errors[:5]
    assert not wide, wide


def test_story_ties_and_storylines(site):
    """A story sits on the profiles of the companies it is about, not every company it mentions; its map pin goes to the
    place it names; and UniUni's saga is one storyline on the main list."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page(viewport={"width": 390, "height": 860})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.goto(site, wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && NEWS.some(n => n.id === 'afb6fa67940a7')"
                             " && THREADS.uniuni && typeof window.storyHome === 'function'", timeout=60000)
        ids = lambda co: set(pg.evaluate(f"() => pStories('{co}').map(n => n.id)"))
        amazon, usps = ids("amazon"), ids("usps")
        assert "g09" not in amazon             # DHL eCommerce and USPS deal: a USPS story, Amazon only mentioned
        # the Feb 2018 "Shipping With Amazon" article (review v5, B16) is off the site through data/drop.json
        assert pg.evaluate("() => !NEWS.some(n => n.id === 'a418fdd3e6f05')")
        assert "05" not in usps                # Amazon's backup plan, tagged USPS in the built-in data
        assert "h512" not in usps              # Amazon's rural network, which names USPS in passing
        assert {"17", "05"} <= amazon and "g09" in usps
        # a big-carrier tag stays when the headline names that carrier's family (Blue Dart is DHL's)
        assert pg.evaluate("() => storyCos(NEWS.find(n => n.id === 'a5e5d0db945cf'), true).includes('dhlexpress')")
        # pins: the place a story names first, then the company it is about; never a company it only mentions
        home = lambda sid: pg.evaluate(f"() => {{const h = storyHome(NEWS.find(n => n.id === '{sid}')); return h && [h.id, h.city]}}")
        assert home("accf814d7d663") == ["uniuni", "Tacoma, WA"]
        # the Tallahassee drone story (its id changes when a newer report of it replaces the older one)
        talla = pg.evaluate("() => (NEWS.find(n => /Tallahassee/.test(n.title) && /drone/i.test(n.title)) || {}).id")
        assert talla and home(talla)[1] == "Tallahassee, FL"
        assert home("17")[0] in ("amazon", "amzship")
        # one UniUni storyline, on the main list, and on UniUni's company page
        assert pg.evaluate("() => Object.keys(THREADS).filter(k => /uniuni/i.test(k + ' ' + THREADS[k].n))") == ["uniuni"]
        assert pg.evaluate("() => thrStories('uniuni').length") >= 4
        assert pg.evaluate("() => coThreads(PL.uniuni).map(x => x.k)") == ["uniuni"]
        pg.click('nav.tabs [data-tab="news"]')
        pg.evaluate("() => renderStorylines()")
        main = pg.evaluate("() => [...document.querySelectorAll('#nStory > .stl h3')].map(h => h.textContent)")
        assert any("UniUni" in t for t in main), main
        b.close()
    assert not errors, errors[:5]


# records every time Coop's own pop-up note appears, with its first words (and skips the first-visit tour offer)
COOP_SAID = """window.__said = []; new MutationObserver(ms => { for (const m of ms) { const t = m.target;
  if (t.classList && t.classList.contains('cbub') && t.closest('#coop') && !t.hidden) window.__said.push(t.textContent.slice(0, 50)) } })
  .observe(document, {subtree: true, attributes: true, attributeFilter: ['hidden']});
  try { localStorage.setItem('pw-tour', 'done') } catch (e) {}"""


@pytest.mark.parametrize("case", ["normal", "muted", "story_open"])
def test_coop_speaks_up_at_most_once(site, case):
    """Coop's unprompted notes: none in the first minute, at most one a visit, none while muted or while a story is open.
    Tapping him still gets an answer."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page(viewport={"width": 390, "height": 860})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.add_init_script(COOP_SAID + ("; try { localStorage.setItem('pw-coop-quiet', '1') } catch (e) {}" if case == "muted" else ""))
        pg.clock.install()
        pg.goto(site, wait_until="load", timeout=60000)
        pg.clock.run_for(3000)
        pg.wait_for_function("() => document.querySelector('#coop .cbird')", timeout=60000)

        def wait(ms):                                             # jump ahead in 30-second steps (timers fire, frames don't)
            for _ in range(ms // 30000):
                pg.clock.fast_forward(30000)
                pg.clock.run_for(1600)

        def visit(*tabs):
            for t in tabs:
                pg.evaluate(f"() => showTab('{t}')")
                pg.mouse.move(200, 300)
                pg.clock.run_for(4000)

        visit("news", "clock", "fuel", "docs", "today")           # the first minute: nothing
        assert pg.evaluate("() => __said") == [], "Coop spoke up within the first minute"
        wait(60000)
        if case == "story_open":
            pg.evaluate("() => openStory(NEWS[0].id)")
            wait(390000)
            assert pg.evaluate("() => __said") == [], "Coop spoke up over an open story"
            pg.evaluate("() => history.back()")
            pg.clock.run_for(2000)
        visit("news", "mna", "clock", "fuel", "docs", "today")
        wait(390000)                                              # several fun-fact chances too
        said = pg.evaluate("() => __said")
        if case == "muted":
            assert said == [], said
        else:
            assert len(said) == 1, said
        # asking him for something always works
        pg.evaluate("() => document.querySelector('#coop .cbird').click()")
        pg.clock.run_for(300)
        pg.evaluate("() => document.querySelector('#coop [data-cfact]').click()")
        pg.clock.run_for(300)
        assert len(pg.evaluate("() => __said")) == len(said) + 1
        b.close()
    assert not errors, errors[:5]


def test_feed_files_late_finds_under_the_day_found(site):
    """A story found a day or two after the news broke files under the day we found it while that find is recent (so it
    isn't buried below news that broke after it), says both dates on its card, and settles back to its own date later."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
        pg = b.new_page(viewport={"width": 390, "height": 860})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())
        pg.goto(site, wait_until="load", timeout=60000)
        pg.wait_for_function("() => typeof feedCmp === 'function' && typeof NEWS !== 'undefined' && NEWS.length > 10", timeout=60000)
        got = pg.evaluate("""() => {
          const at = (d, h) => new Date(addDays(TODAY, d) + 'T' + String(h).padStart(2, '0') + ':00:00').toISOString();
          const base = NEWS[0];
          const mk = (id, date, added) => Object.assign({}, base, {id, date: addDays(TODAY, date), added, dl: null});
          const S = [
            mk('zz-today-am', 0, at(0, 9)),        // broke this morning, found this morning
            mk('zz-late', -1, at(0, 15)),          // broke yesterday, found this afternoon: a late find
            mk('zz-yday', -1, at(-1, 10)),         // broke and found yesterday
            mk('zz-old-late', -6, at(-4, 10)),     // found 4 days ago, 2 days late: settled back to its own date
            mk('zz-very-late', -12, at(0, 8)),     // a report of an event 12 days old: files under the event's date
          ];
          const order = S.slice().sort(feedCmp).map(s => s.id);
          return {order, label: reportedFound(S[1]), none: reportedFound(S[0]), veryLate: reportedFound(S[4]),
                  card: card(S[1], false).includes('Reported ' + fmtD(S[1].date) + ' · found ' + fmtD(TODAY))};
        }""")
        b.close()
    assert not errors, errors[:5]
    assert got["order"] == ["zz-late", "zz-today-am", "zz-yday", "zz-old-late", "zz-very-late"], got
    assert got["label"].startswith("Reported ") and " · found " in got["label"]
    assert got["none"] == "" and got["veryLate"] == ""
    assert got["card"], "the card shows both dates"


def _open(p, site, width, hash_=""):
    b = p.chromium.launch(executable_path=os.environ.get("PP_CHROMIUM") or None)
    pg = b.new_page(viewport={"width": width, "height": 860})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route(re.compile(r"^https?://(?!127\.0\.0\.1)"), lambda r: r.abort())       # prices and quotes: local fixtures only
    pg.add_init_script("try { localStorage.setItem('pw-tour', 'done'); localStorage.setItem('pw-mk-mode', 'pick') } catch (e) {}")
    pg.goto(site + hash_, wait_until="load", timeout=60000)
    pg.wait_for_function("() => typeof PL !== 'undefined' && Object.keys(PL).length > 100 && EARN_NEXT.length && EARN.some(e => e.vol)", timeout=60000)
    return b, pg, errors


@pytest.mark.parametrize("width", [390, 1280])
def test_earnings_chart_and_stock_watch(site, width):
    """B29/B34: the earnings chart for UPS and FedEx in all three views, with keyboard-reachable bars, the FedEx spin-off
    divider and nothing wider than the screen. Today ends with the latest UPS and FedEx earnings (no stock cards), and
    each card shows the company's share price beside its logo."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b, pg, errors = _open(p, site, width)
        assert pg.evaluate("() => !document.querySelector('.mkc, .mkwatch')")
        cards = pg.evaluate("""() => [...document.querySelectorAll('#earnToday .etc')].map(x => [x.dataset.goto || null, x.textContent.replace(/\\s+/g, ' ')])""")
        uq = pg.evaluate("() => EARN.filter(e => e.company === 'UPS' && e.d <= TODAY).sort((a, b) => b.d.localeCompare(a.d))[0].q")      # the newest reported UPS quarter
        # a company whose report is out but not yet in the history shows "Being added", not its previous quarter
        fdx_due = pg.evaluate("() => EARN_NEXT.some(x => x.c === 'FedEx' && x.d <= TODAY && !x.est && !earnDone(x))")
        fdx_goto = "docs:earnings:FedEx" if fdx_due else "docs:earnings:FedEx:FY26 Q4"
        assert [c[0] for c in cards] == [f"docs:earnings:UPS:{uq}", fdx_goto, "docs:earnings:USPS:FY26 Q3", None], cards
        assert "Next report expected mid-Nov" in cards[2][1], cards
        assert "Next report Oct 27" not in cards[0][1], cards                     # a call that has happened is never shown as next
        assert pg.evaluate("() => !!document.querySelector('#earnToday .etc:last-child.etshare')")
        assert pg.evaluate("() => document.querySelector('#earnToday h2').textContent === 'Earnings and market'")
        # the volume box points to our market report first, then to Pitney Bowes
        links = pg.evaluate("""() => [...document.querySelectorAll('#earnToday .etshare .etlinks > *')].map(x => [x.textContent.trim(), x.dataset.open || x.href || ''])""")
        assert links[0] == ["Market report ›", "r03"] and links[1][0].startswith("Pitney Bowes") and "pitneybowes.com" in links[1][1], links
        want = {0: (uq, "Revenue", "Packages a day", "Revenue per package"),
                1: ("Being added", "FY26 Q4") if fdx_due else ("FY26 Q4", "$25.0B", "+12.6%", "17.1M", "+1.7%", "$17.90", "+10.9%"),
                2: ("FY26 Q3", "$19.9B", "+6.1%", "≈17.1M", "−3.4%", "≈$5.31"),      # USPS: pieces over calendar days, marked ≈; revenue per package = segment revenue over pieces, marked ≈
                3: ("U.S. parcel volume", "2025", "23.1 billion parcels (+3.3%)", "Amazon", "6.9B", "30%", "+9%", "USPS", "6.2B", "27%", "−8.8%",
                    "UPS", "4.3B", "19%", "−8.7%", "FedEx", "3.9B", "17%", "+5.1%", "Others", "1.8B", "8%", "+127%", "Pitney Bowes")}
        for i, ws in want.items():
            for w in ws:
                assert w in cards[i][1], (w, cards[i][1])
        assert pg.evaluate("() => [...document.querySelectorAll('#earnToday .etc')].every(x => x.scrollWidth <= x.clientWidth + 1)")
        assert pg.evaluate("() => [...document.querySelectorAll('#earnToday button.etc')].every(x => !x.querySelector('a, button'))")
        # the bottom of Today doesn't move: nothing rotates
        h0 = pg.evaluate("() => document.getElementById('earnToday').offsetHeight")
        pg.wait_for_timeout(6500)
        assert pg.evaluate("() => document.getElementById('earnToday').offsetHeight") == h0
        # the share price sits beside the logo on Today's UPS, FedEx and Amazon cards (USPS has no stock), and not in Docs
        stk = pg.evaluate("""() => [...document.querySelectorAll('#earnToday .etc')].map(c => (c.querySelector('.eth .etstk') || {}).textContent || null)""")
        assert stk[0].startswith("UPS $") and stk[1].startswith("FDX $") and stk[2] is None and stk[3] is None, stk
        pg.evaluate("() => goTo('docs')")
        pg.wait_for_timeout(300)
        assert pg.evaluate("() => !document.querySelector('#lib .dstk, #lib .etstk')")
        # FedEx: packages and revenue per package are the Federal Express segment only (not the revenue view)
        pg.evaluate("() => goTo('docs','earnings','FedEx')")
        pg.wait_for_timeout(200)
        notes = {}
        for v in ("rev", "adv", "rpp"):
            pg.evaluate(f"() => document.querySelector('.eglance[data-eco=\"FedEx\"] [data-eview=\"{v}\"]').click()")
            notes[v] = pg.evaluate("() => !!document.querySelector('.eglance[data-eco=\"FedEx\"] .egfrt')")
        assert notes == {"rev": False, "adv": True, "rpp": True}, notes
        wide = {}
        for co in ("UPS", "FedEx"):
            pg.evaluate(f"() => goTo('docs','earnings','{co}')")
            pg.wait_for_timeout(300)
            for v in ("rev", "adv", "rpp"):
                pg.evaluate(f"() => document.querySelector('.eglance[data-eco=\"{co}\"] [data-eview=\"{v}\"]').click()")
                st = pg.evaluate(f"""() => {{ const g = document.querySelector('.eglance[data-eco="{co}"]');
                  return {{bars: g.querySelectorAll('button.egbar').length, label: g.querySelector('.egbars').getAttribute('aria-label'),
                          pressed: g.querySelector('[data-eview="{v}"]').getAttribute('aria-pressed'), div: !!g.querySelector('.egdiv'),
                          sel: g.querySelectorAll('.egbar[aria-pressed="true"]').length}} }}""")
                assert st["bars"] >= 8 and st["pressed"] == "true" and st["sel"] == 1 and st["label"], (co, v, st)
                assert st["div"] == (co == "FedEx" and v == "rev"), (co, v)
                over = pg.evaluate(OVERFLOW)
                if over:
                    wide[f"{co}:{v}"] = over
        if width == 390:   # the latest quarters are on screen; older ones scroll inside the chart, not the page
            vis = pg.evaluate("""() => { const sc = document.querySelector('.eglance[data-eco="FedEx"] .egscroll'), r = sc.getBoundingClientRect();
              return [...sc.querySelectorAll('.egbar')].filter(x => { const q = x.getBoundingClientRect(); return q.left >= r.left - 1 && q.right <= r.right + 1 }).length }""")
            assert vis >= 7, vis
        # keyboard: the bars are buttons, and the arrow keys move the selection
        pg.evaluate("() => earnView('rev')")
        pg.focus('.eglance[data-eco="FedEx"] .egbar[aria-pressed="true"]')
        pg.keyboard.press("ArrowLeft")
        assert pg.evaluate("() => document.activeElement.dataset.ebar") == "FY26 Q3"
        assert pg.evaluate("() => document.querySelector('.eglance[data-eco=\"FedEx\"] .egdet').textContent.includes('Fiscal Q3 2026 (Dec 2025–Feb 2026)')")
        b.close()
    assert not errors, errors[:5]
    assert not wide, wide


@pytest.mark.parametrize("width", [390, 1280])
def test_earnings_navigation_and_back(site, width):
    """B31/B33: from FedEx's company page, Earnings opens the FedEx panel with its Earnings folder open on screen, and
    "Back to FedEx" returns to the company page, which Escape then closes. Today's latest-earnings card lands on its
    quarter, and the phone's back button returns to Today where it was. Story → company → Back → Back → the feed.
    Back never leaves the site."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b, pg, errors = _open(p, site, width, "#c=fedex")
        uq = pg.evaluate("() => EARN.filter(e => e.company === 'UPS' && e.d <= TODAY).sort((a, b) => b.d.localeCompare(a.d))[0].q")      # the newest reported UPS quarter
        pg.wait_for_function("() => CO_OPEN === 'fedex' && document.querySelector('#coSheet.open [data-goto^=\"docs:earnings\"]')", timeout=30000)
        assert pg.get_attribute('#coSheet [data-goto^="docs:earnings"]', "data-goto") == "docs:earnings:FedEx"
        pg.click('#coSheet [data-goto^="docs:earnings"]')
        pg.wait_for_function("() => curTab() === 'docs' && document.activeElement && document.activeElement.matches('.dcarp[data-car=\"FedEx\"] details.dearn > summary')", timeout=15000)
        st = pg.evaluate("""() => { const p = document.querySelector('.dcarp[data-car="FedEx"]'), f = p && p.querySelector('details.dearn'),
            r = f && f.querySelector('summary').getBoundingClientRect();
          return {tab: curTab(), co: CO_OPEN, panel: p && p.open, folder: f && f.open, onscreen: !!r && r.top >= 0 && r.bottom <= innerHeight,
                  ups: document.querySelector('.dcarp[data-car="UPS"]').open, focus: document.activeElement === (f && f.querySelector('summary')),
                  back: document.getElementById('navBack').textContent, padded: document.body.classList.contains('nb-on')} }""")
        assert st == {"tab": "docs", "co": None, "panel": True, "folder": True, "onscreen": True, "ups": False, "focus": True,
                      "back": "Back to “FedEx”", "padded": True}, st
        pg.go_back()                                             # the phone's back button
        pg.wait_for_function("() => CO_OPEN === 'fedex' && !document.getElementById('coSheet').hidden", timeout=10000)
        pg.keyboard.press("Escape")
        pg.wait_for_function("() => CO_OPEN == null && document.getElementById('coSheet').hidden", timeout=15000)
        assert pg.evaluate("() => CO_OPEN == null && document.getElementById('coSheet').hidden && NAVBACK.length === 0")
        assert pg.url.startswith(site)

        # Today → latest-earnings card → the phone's back button returns to Today, where it was
        pg.click('nav.tabs [data-tab="today"]')
        pg.evaluate("() => document.getElementById('earnToday').scrollIntoView({block: 'center', behavior: 'instant'})")
        # the phone header collapses once the page scrolls, and scroll anchoring then moves the page: wait until it settles
        pg.wait_for_function("""() => new Promise(r => { const a = scrollY; setTimeout(() => r(scrollY === a), 250) })""", timeout=5000)
        # Playwright scrolls a button into its own view before clicking; do that first, so the position read here is the
        # one the reader tapped from
        pg.locator('#earnToday .etc[data-goto="docs:earnings:UPS:' + uq + '"]').scroll_into_view_if_needed()
        pg.wait_for_function("""() => new Promise(r => { const a = scrollY; setTimeout(() => r(scrollY === a), 250) })""", timeout=5000)
        y0 = pg.evaluate("() => scrollY")
        pg.click('#earnToday .etc[data-goto="docs:earnings:UPS:' + uq + '"]')
        assert pg.evaluate("() => NAVBACK.length && NAVBACK[NAVBACK.length - 1].y") == y0
        pg.wait_for_function("() => curTab() === 'docs' && document.activeElement && document.activeElement.matches('.dcarp[data-car=\"UPS\"] details.dearn > summary')", timeout=15000)
        assert pg.evaluate("""() => curTab() === 'docs' && document.querySelector('.dcarp[data-car="UPS"] details.dearn').open
          && document.querySelector('.eglance[data-eco="UPS"] .egbar[aria-pressed="true"]').dataset.ebar === '""" + uq + """'""")
        pg.go_back()
        pg.wait_for_function("() => curTab() === 'today'", timeout=15000)
        pg.wait_for_timeout(300)
        assert pg.evaluate("() => curTab()") == "today"
        assert abs(pg.evaluate("() => scrollY") - y0) <= 4
        assert pg.url.startswith(site) and pg.evaluate("() => !!document.querySelector('nav.tabs')")

        # a story → its company page → Back (the story again) → Back (the feed)
        sid = pg.evaluate("() => (NEWS.find(n => storyCoLinks(n)) || {}).id || null")
        assert sid
        pg.evaluate(f"() => openStory('{sid}')")
        pg.wait_for_function("() => !!document.querySelector('#storySheet.open [data-sco]')", timeout=15000)
        pg.click('#storySheet [data-sco]')
        pg.wait_for_function("() => CO_OPEN != null && STORY_OPEN == null", timeout=10000)
        pg.go_back()
        pg.wait_for_function("() => CO_OPEN == null && STORY_OPEN != null", timeout=15000)
        assert pg.evaluate(f"() => CO_OPEN == null && STORY_OPEN === '{sid}'")
        pg.go_back()
        pg.wait_for_function("() => STORY_OPEN == null", timeout=15000)
        pg.wait_for_timeout(300)
        assert pg.evaluate("() => CO_OPEN == null && STORY_OPEN == null && !!document.querySelector('nav.tabs')")
        assert pg.url.startswith(site)
        wide = pg.evaluate(OVERFLOW)
        b.close()
    assert not errors, errors[:5]
    assert not wide, wide
