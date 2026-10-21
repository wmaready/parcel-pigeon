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
