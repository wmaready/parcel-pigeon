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
