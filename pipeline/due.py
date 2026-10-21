"""Once-a-day jobs: exit 0 (run it) on the first run at or after the given UTC hour each day, and 1 otherwise.

Runs can wait a long time in GitHub's queue behind the hourly watch, so "only on the 04 UTC run" missed whole days: the
04:17 run started at 05:27 and the company research and full audit were skipped. This remembers the day each job last ran.
Usage: python due.py NAME HOUR      (e.g. `if python due.py brief 12; then python brief.py; fi`)
"""
import datetime as dt, sys
from common import load, save


def due(name, hour, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    st = load("due.json", {})
    if now.hour < hour or st.get(name) == now.date().isoformat():
        return False
    st[name] = now.date().isoformat()
    save("due.json", st)
    return True


if __name__ == "__main__":
    sys.exit(0 if due(sys.argv[1], int(sys.argv[2])) else 1)
