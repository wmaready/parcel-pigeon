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
        assert "a418fdd3e6f05" not in usps     # Amazon's own delivery service: USPS only named as a rival
        assert "05" not in usps                # Amazon's backup plan, tagged USPS in the built-in data
        assert "h512" not in usps              # Amazon's rural network, which names USPS in passing
        assert {"a418fdd3e6f05", "05"} <= amazon and "g09" in usps
        # a big-carrier tag stays when the headline names that carrier's family (Blue Dart is DHL's)
        assert pg.evaluate("() => storyCos(NEWS.find(n => n.id === 'a5e5d0db945cf'), true).includes('dhlexpress')")
        # pins: the place a story names first, then the company it is about; never a company it only mentions
        home = lambda sid: pg.evaluate(f"() => {{const h = storyHome(NEWS.find(n => n.id === '{sid}')); return h && [h.id, h.city]}}")
        assert home("accf814d7d663") == ["uniuni", "Tacoma, WA"]
        assert home("ab73d424a5c41")[1] == "Tallahassee, FL"
        assert home("a418fdd3e6f05")[0] in ("amazon", "amzship")
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
