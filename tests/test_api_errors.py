"""When Claude's API refuses a call, the pipeline says why, and stops calling for the rest of the run if the account
itself is the problem (no credit, spend limit, bad key)."""
import pytest
import common


class R:
    def __init__(self, status, body):
        self.status_code, self._b, self.text = status, body, str(body)
    def json(self):
        return self._b


def test_account_problem_is_named_and_stops_the_run(monkeypatch, capsys):
    monkeypatch.setattr(common, "API_DOWN", {})
    with pytest.raises(RuntimeError, match="credit balance is too low"):
        common.api_check(R(400, {"type": "error", "error": {"type": "invalid_request_error",
                                 "message": "Your credit balance is too low to access the Anthropic API."}}))
    assert "credit balance" in common.API_DOWN["why"]
    assert "::error title=Claude API refused every call::" in capsys.readouterr().out
    monkeypatch.setattr(common, "API_KEY", "test")
    with pytest.raises(RuntimeError, match="unavailable this run"):
        common.claude("m", "s", "u")          # no further calls once the account is known to refuse


def test_ordinary_bad_request_names_the_reason_but_keeps_going(monkeypatch):
    monkeypatch.setattr(common, "API_DOWN", {})
    with pytest.raises(RuntimeError, match="max_tokens"):
        common.api_check(R(400, {"error": {"type": "invalid_request_error", "message": "max_tokens: too large"}}))
    assert not common.API_DOWN


def test_calls_leave_room_for_thinking(monkeypatch):
    """Sonnet 5.5 and Haiku 5.5 think by default and thinking counts against max_tokens; a short max_tokens once came
    back as an empty reply. Every call adds headroom on top of the reply's own limit."""
    import requests, common
    sent = {}

    class R:
        status_code = 200
        def json(self):
            return {"model": "claude-haiku-5-5", "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5}}
    monkeypatch.setattr(common, "API_KEY", "test-key")
    monkeypatch.setattr(requests, "post", lambda url, **k: sent.update(k["json"]) or R())
    assert common.claude("claude-haiku-5-5", "sys", "hi", max_tokens=200) == "ok"
    assert sent["max_tokens"] == 200 + common.THINK_ROOM
    assert "output_config" not in sent              # each model's own default effort: quality before cost
