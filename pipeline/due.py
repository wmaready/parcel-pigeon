"""Once-a-day jobs: run on the first run at or after a given hour each day, and again on later runs until one succeeds.

Runs can wait a long time in GitHub's queue behind the hourly watch, so "only on the 04 UTC run" missed whole days: the
04:17 run started at 05:27 and the company research and full audit were skipped. This remembers the day each job last
finished. Hours are UTC, or U.S. Eastern with --et (so the morning brief stays at 8 a.m. through daylight saving changes).
Usage:  if python due.py brief 8 --et; then python brief.py && python due.py --done brief --et; fi
"""
import datetime as dt, sys
from zoneinfo import ZoneInfo
from common import load, save


def now(et=False):
    return dt.datetime.now(ZoneInfo("America/New_York") if et else dt.timezone.utc)


def due(name, hour, t=None):
    """True if the job hasn't finished today and it's at or past the hour."""
    t = t or now()
    return t.hour >= hour and load("due.json", {}).get(name) != t.date().isoformat()


def done(name, t=None):
    t = t or now()
    st = load("due.json", {})
    st[name] = t.date().isoformat()
    save("due.json", st)


if __name__ == "__main__":
    et = "--et" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--et"]
    if args[0] == "--done":
        done(args[1], now(et)); sys.exit(0)
    sys.exit(0 if due(args[0], int(args[1]), now(et)) else 1)
