"""The robots' GitHub workflows: a failed step is recorded and turns the run red, but the data is still saved and the
site still deployed (B11); Doc watch has a cached Playwright browser and its page pictures reach the site (B35)."""
import json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def steps(name):
    wf = json.loads((WF / name).read_text())
    return next(iter(wf["jobs"].values()))["steps"]


def script(name):
    return next(s for s in steps(name) if s.get("working-directory") == "pipeline")["run"]


def test_no_robot_failure_is_hidden():
    for name in ("watch.yml", "update.yml"):
        run = script(name)
        for job in ("docwatch.py", "fuel.py", "publish.py", "audit.py", "markets.py", "themes.py", "export_seed.js",
                    "news.py", "alerts.py", "ratecal.py", "watch.py"):
            for line in run.splitlines():
                if job in line and not line.lstrip().startswith("#") and "due.py" not in line:
                    assert "|| true" not in line and "::warning::" not in line, f"{name}: {line}"
        assert 'echo "PP_FAILED=$FAILED" >> "$GITHUB_ENV"' in run.splitlines()[-1]
        st = steps(name)
        last = st[-1]
        assert last["if"] == "always()" and "exit 1" in last["run"] and "$PP_FAILED" in last["run"]
        # saving and deploying come before the red step and carry no condition that skips them after a robot failure
        names = [s.get("name") or s.get("uses") or s.get("id") for s in st]
        assert names.index("actions/deploy-pages@v4") < len(st) - 1
        for s in st[names.index(next(n for n in names if n and n.startswith("Save"))):-1]:
            assert "failure" not in (s.get("if") or "")


def test_step_records_the_failure_and_carries_on(tmp_path):
    """Run the workflow's own `step` helper: the failing command is named in an ::error line, the next one still runs,
    and the failure list reaches the final red step through GITHUB_ENV."""
    helper = "\n".join(l for l in script("watch.yml").splitlines() if l.startswith(("set +e", "FAILED=", "step() {")))
    env = tmp_path / "env"
    out = subprocess.run(["bash", "-e", "-c", helper + '\nstep broken.py false\nstep fine.py true\necho ran-after\n'
                          'echo "PP_FAILED=$FAILED" >> "$GITHUB_ENV"\n'],
                         capture_output=True, text=True, env={"GITHUB_ENV": str(env), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    assert "::error title=broken.py failed::" in out.stdout and "fine.py failed" not in out.stdout and "ran-after" in out.stdout
    assert env.read_text().strip() == "PP_FAILED= broken.py;"


def test_missing_optional_keys_are_warnings_not_failures():
    run = script("update.yml")
    for key in ("OILPRICE_API_KEY", "EIA_API_KEY"):
        line = next(l for l in run.splitlines() if key in l)
        assert line.startswith(f'[ -n "${key}" ] ||') and "::warning" in line and "exit" not in line


def test_audit_is_marked_done_only_when_it_worked():
    line = next(l for l in script("update.yml").splitlines() if "due.py audit 4" in l)
    assert "step audit.py python audit.py && python due.py --done audit" in line


def test_doc_watch_has_a_cached_browser_and_publishes_pictures():
    st = steps("watch.yml")
    runs = [s.get("run") or "" for s in st]
    cache = next(s for s in st if (s.get("uses") or "").startswith("actions/cache@"))
    assert cache["with"]["path"] == "~/.cache/ms-playwright" and "steps.pw.outputs.version" in cache["with"]["key"]
    i_cache, i_browser = st.index(cache), next(i for i, r in enumerate(runs) if "playwright install --with-deps chromium" in r)
    i_doc = next(i for i, r in enumerate(runs) if "docwatch.py" in r)
    assert i_cache < i_browser < i_doc
    assert "playwright" in (ROOT / "requirements.txt").read_text()
    for name in ("watch.yml", "update.yml"):
        rm = next(s for s in steps(name) if s.get("name") == "Leave raw page copies out of the public site")["run"]
        assert "rm -rf data/snapshots " not in rm and re.search(r"find data/snapshots .*! -name '\*\.jpg' -delete", rm)
