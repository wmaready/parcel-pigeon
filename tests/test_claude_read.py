"""When our reader is turned away, the page is read through Claude's web fetch tool, and the text used is the tool's
copy of the page, never the model's own words."""
import common
import news as N

PAGE = "FedEx said Tuesday it will raise Ground rates by an average of 5.9 percent effective Jan. 4, 2027. " * 12
BLOCK = "<html><body>Access Denied. You don't have permission to access this page. Reference #18.abc</body></html>"


class Resp:
    def __init__(self, text="", status=200, url="https://www.example-news.com/fedex-rates", js=None):
        self.text, self.status_code, self.url, self._js = text, status, url, js
    def json(self):
        return self._js
    def raise_for_status(self):
        pass


def tool_reply(data):
    return {"content": [
        {"type": "server_tool_use", "id": "t1", "name": "web_fetch", "input": {"url": "https://www.example-news.com/fedex-rates"}},
        {"type": "web_fetch_tool_result", "tool_use_id": "t1", "content": {"type": "web_fetch_result", "url": "https://www.example-news.com/fedex-rates",
            "content": {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": data}}}},
        {"type": "text", "text": "OK. FedEx will raise rates 9.9 percent."}],          # the model's words: never used
        "usage": {"input_tokens": 10, "output_tokens": 2}}


def test_blocked_page_is_read_through_web_fetch(monkeypatch):
    monkeypatch.setattr(common, "API_KEY", "test")
    monkeypatch.setitem(N.READS, "n", 0)
    monkeypatch.setattr(N.requests, "get", lambda *a, **k: Resp(BLOCK, 403))
    monkeypatch.setattr(N.requests, "post", lambda *a, **k: Resp(js=tool_reply(PAGE)))
    text, url = N.article_text("https://www.example-news.com/fedex-rates")
    assert "5.9 percent" in text and "9.9" not in text


def test_tool_returning_a_block_page_gives_nothing(monkeypatch):
    monkeypatch.setattr(common, "API_KEY", "test")
    monkeypatch.setitem(N.READS, "n", 0)
    monkeypatch.setattr(N.requests, "get", lambda *a, **k: Resp(BLOCK, 403))
    monkeypatch.setattr(N.requests, "post", lambda *a, **k: Resp(js=tool_reply(BLOCK)))
    text, _ = N.article_text("https://www.example-news.com/fedex-rates")
    assert text is None


def test_reads_are_capped(monkeypatch):
    monkeypatch.setattr(common, "API_KEY", "test")
    monkeypatch.setitem(N.READS, "n", N.CLAUDE_READS)
    monkeypatch.setattr(N.requests, "get", lambda *a, **k: Resp(BLOCK, 403))
    monkeypatch.setattr(N.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("over the cap")))
    assert N.article_text("https://www.example-news.com/fedex-rates")[0] is None
