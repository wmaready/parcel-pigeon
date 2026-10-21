"""Read carrier pages and files even when the carrier's site turns away scripts.

UPS and FedEx sit behind bot protection (Akamai). A plain Python request from a GitHub runner gets an
"Access Denied" or "we can't process your request" page back with a 200 or 403. Saving that page as if it were the
rate guide hides every real change and makes noise when the block page's incident number changes.

fetch(url) tries, in order, and stops at the first real copy:
  1. a normal request with full browser headers
  2. the same request with a Chrome TLS fingerprint (curl_cffi, when installed)
  3. a real Chromium browser (Playwright, when installed; web pages only)
  4. an unblocking proxy, when the PP_FETCH_PROXY secret holds one, e.g.
     "https://api.scraperapi.com/?api_key=KEY&url={url}" ({url} is filled in, URL-encoded)
  5. the latest Internet Archive copy (marked with its capture date, so a stale copy is never mistaken for today's)
If every route returns a block page it raises Blocked, so callers can record it as a failure instead of a reading.
"""
import json, os, re, sys, urllib.parse
import requests

BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}

# Text that only appears on bot-protection and error pages (Akamai, Imperva, Cloudflare, FedEx's and UPS's own wording)
BLOCK_RE = re.compile(r"access denied|you don't have permission to (access|view)|we're sorry, we can't process your request|"
                      r"incident number:|reference #\d+\.|request unsuccessful\. incapsula|_incapsula_resource|"
                      r"pardon our interruption|checking your browser|just a moment\.\.\.|attention required! \| cloudflare|"
                      r"cf-chl-|enable javascript and cookies to continue|bot or not|are you a robot|unusual traffic", re.I)


class Blocked(Exception):
    pass


class Page:
    """Just enough of a requests.Response for the pipeline: content, text, headers, url, plus how it was read."""
    def __init__(self, content, headers, url, via, when=None):
        self.content, self.headers, self.url, self.via, self.when = content, {k.lower(): v for k, v in (headers or {}).items()}, url, via, when

    @property
    def text(self):
        return self.content.decode("utf-8", "replace") if isinstance(self.content, bytes) else (self.content or "")


def is_pdf(url, page=None):
    ctype = (page.headers.get("content-type", "") if page else "").lower()
    return "pdf" in ctype or urllib.parse.urlsplit(url).path.lower().endswith(".pdf")


def visible(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def is_blocked(text, status=200, expect_pdf=False, content=b""):
    """A bot wall or error page, not the document. Short pages only: a long page that merely mentions
    'access denied' in its own content is real."""
    if status in (401, 403, 429, 503):
        return True
    if expect_pdf and content[:5] == b"%PDF-":
        return False
    if expect_pdf and content and content[:5] != b"%PDF-":
        return True          # asked for a PDF, got an HTML page back
    t = visible(text) if "<" in (text or "") else (text or "")
    return len(t) < 4000 and bool(BLOCK_RE.search(t))


def _ok(page, url):
    return page is not None and not is_blocked(page.text if not is_pdf(url) else "", 200, is_pdf(url), page.content)


def _plain(url, timeout):
    r = requests.get(url, headers=BROWSER, timeout=timeout, allow_redirects=True)
    if r.status_code == 404:
        r.raise_for_status()
    if r.status_code >= 400 and r.status_code not in (401, 403, 429, 503):
        r.raise_for_status()
    if r.status_code in (401, 403, 429, 503):
        return None
    return Page(r.content, r.headers, r.url, "direct")


def _impersonate(url, timeout):
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return None
    r = creq.get(url, impersonate="chrome", timeout=timeout, allow_redirects=True, headers={"Accept-Language": BROWSER["Accept-Language"]})
    if r.status_code >= 400:
        return None
    return Page(r.content, dict(r.headers), str(r.url), "chrome-tls")


def render(url, timeout=45):
    """Open the page in a real Chromium, open every drop-down, and return the HTML (None if Playwright isn't installed)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            ctx = b.new_context(user_agent=BROWSER["User-Agent"], locale="en-US", viewport={"width": 1366, "height": 900})
            pg = ctx.new_page()
            pg.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            pg.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            # carriers (FedEx especially) tuck notices under drop-downs; open every one so the text is in the page we read
            pg.evaluate("""() => { document.querySelectorAll('details').forEach(d => d.open = true);
                [...document.querySelectorAll('[aria-expanded="false"]')].slice(0, 80).forEach(b => { try { b.click(); } catch (e) {} }); }""")
            pg.wait_for_timeout(1500)
            html = pg.content()
            b.close()
            return html
    except Exception as e:
        print(f"  render failed {url}: {e}", file=sys.stderr)
        return None


def _browser(url, timeout):
    if is_pdf(url):
        return None
    html = render(url, timeout)
    return Page(html.encode(), {"content-type": "text/html"}, url, "browser") if html else None


def _proxy(url, timeout):
    tpl = os.environ.get("PP_FETCH_PROXY", "").strip()
    if not tpl or "{url}" not in tpl:
        return None
    r = requests.get(tpl.replace("{url}", urllib.parse.quote(url, safe="")), timeout=max(timeout, 60))
    if r.status_code >= 400:
        return None
    return Page(r.content, r.headers, url, "proxy")


def _archive(url, timeout):
    """Latest Internet Archive capture. 'id_' asks for the original bytes without the archive's toolbar."""
    r = requests.get("https://archive.org/wayback/available", params={"url": url}, timeout=timeout)
    snap = ((r.json().get("archived_snapshots") or {}).get("closest") or {}) if r.ok else {}
    if not snap.get("available") or str(snap.get("status")) != "200":
        return None
    ts = snap["timestamp"]
    raw = f"https://web.archive.org/web/{ts}id_/{url}"
    a = requests.get(raw, headers=BROWSER, timeout=max(timeout, 60))
    if a.status_code >= 400:
        return None
    return Page(a.content, a.headers, url, "archive", when=f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}")


ROUTES = [_plain, _impersonate, _browser, _proxy, _archive]


def fetch_late(url, timeout=40):
    """The routes after the browser (an unblocking proxy, then the Internet Archive), for pages that only reveal their bot
    wall once a browser runs them: the plain read looks fine, the rendered page is blocked. None if neither works."""
    for route in (_proxy, _archive):
        try:
            page = route(url, timeout)
        except Exception:
            continue
        if page is not None and _ok(page, url):
            return page
    return None


def fetch(url, timeout=40, archive=True):
    """First route that returns the real page or file. Raises Blocked when every route hits a bot wall,
    and the underlying error when the address itself is broken (404 and the like)."""
    errors = []
    for route in ROUTES:
        if route is _archive and not archive:
            continue
        try:
            page = route(url, timeout)
        except requests.HTTPError as e:
            if route is _plain and e.response is not None and e.response.status_code in (404, 410):
                raise
            errors.append(f"{route.__name__.strip('_')}: {e}"); continue
        except Exception as e:
            errors.append(f"{route.__name__.strip('_')}: {type(e).__name__}"); continue
        if page is None:
            errors.append(f"{route.__name__.strip('_')}: refused"); continue
        if _ok(page, url):
            return page
        errors.append(f"{route.__name__.strip('_')}: block page")
    raise Blocked("blocked by the carrier's site (" + "; ".join(errors)[:200] + ")")
