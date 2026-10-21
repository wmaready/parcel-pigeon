"""Shared test setup. Tests never touch the network or the Claude API, and never write to the real data/ folder:
each test that saves data gets its own copy of data/ in a temporary folder."""
import shutil, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A private copy of data/ (without the large page and file copies) that load()/save() read and write."""
    import common
    dst = tmp_path / "data"
    shutil.copytree(ROOT / "data", dst, ignore=shutil.ignore_patterns("logos", "docwatch", "snapshots", "files"))
    monkeypatch.setattr(common, "DATA", dst)
    return dst


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any test that reaches for the network or the API fails loudly instead of quietly calling out."""
    import requests
    def blocked(*a, **k):
        raise RuntimeError("tests must not use the network")
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests, "post", blocked)


@pytest.fixture(autouse=True)
def fresh_meter(monkeypatch, request):
    """Each test counts its own Claude spend, so nothing a test 'spends' reaches the real ledger when pytest exits, and
    the real ledger's spend never pauses a test. Tests with their own data/ copy keep the ledgers in it."""
    import common
    if "data_dir" not in request.fixturenames:
        monkeypatch.setattr(common, "LEDGERS", ())
    monkeypatch.setattr(common, "USAGE", {"calls": 0, "in": 0, "cached": 0, "written": 0, "out": 0, "usd": 0.0})
    monkeypatch.setattr(common, "PACE", {})
