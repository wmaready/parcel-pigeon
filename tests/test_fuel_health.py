"""B8: UPS and FedEx weekly fuel never fail quietly. A missing OILPRICE_API_KEY or a failing service is logged as a GitHub
error annotation and recorded in data/fuel.json "health"; the free sources still run and the file is still saved."""
import json


def _no_page_reads(data_dir):
    """The live data may say FedEx was just read from its own page, which skips the key path these tests exercise."""
    f = json.loads((data_dir / "fuel.json").read_text())
    f.pop("health", None)
    (data_dir / "fuel.json").write_text(json.dumps(f))


def _offline(monkeypatch, fuel):
    for f in ("ontrac", "dhl_express", "eia_spot", "fred_diesel"):
        monkeypatch.setattr(fuel, f, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))


def test_missing_key_is_logged_loudly(data_dir, monkeypatch, capsys):
    import fuel
    _no_page_reads(data_dir)
    _offline(monkeypatch, fuel)
    monkeypatch.delenv("OILPRICE_API_KEY", raising=False)
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    fuel.main()
    err = capsys.readouterr().err
    assert err.count("::error title=Fuel surcharges::OILPRICE_API_KEY is not set") == 2
    saved = json.loads((data_dir / "fuel.json").read_text())
    assert saved["health"]["UPS"]["ok"] is False and saved["health"]["FedEx"]["why"] == "OILPRICE_API_KEY not set"


def test_failing_service_is_logged_and_recorded(data_dir, monkeypatch, capsys):
    import fuel
    _no_page_reads(data_dir)
    _offline(monkeypatch, fuel)
    monkeypatch.setenv("OILPRICE_API_KEY", "x")
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    calls = []

    def oil(f, c, key):
        calls.append(c)
        if c == "UPS":
            raise RuntimeError("401 Unauthorized")
        return 3
    monkeypatch.setattr(fuel, "oilprice", oil)
    fuel.main()
    err = capsys.readouterr().err
    assert calls == ["UPS", "FedEx"]
    assert "::error title=Fuel surcharges::UPS weekly fuel was NOT updated" in err and "401 Unauthorized" in err
    h = json.loads((data_dir / "fuel.json").read_text())["health"]
    assert h["UPS"]["ok"] is False and h["FedEx"]["ok"] is True and h["FedEx"]["last_ok"]


def test_empty_history_counts_as_a_failure(monkeypatch):
    import fuel, requests

    class R:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return {"data": self.data}
    seq = iter([R({"service_levels": []}), R({"history": []})])
    monkeypatch.setattr(requests, "get", lambda *a, **k: next(seq))
    try:
        fuel.oilprice({}, "UPS", "x")
    except RuntimeError as e:
        assert "no weekly history" in str(e)
    else:
        raise AssertionError("an empty answer must not pass as an update")
