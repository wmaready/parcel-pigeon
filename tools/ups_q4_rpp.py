#!/usr/bin/env python3
"""UPS doesn't print a fourth quarter, so its revenue per piece for Q4 is calculated: the 10-K's full-year figure less the
first three quarters (pipeline/filings.py q4_rpp). One-off backfill for Q4 2024 and Q4 2025; from now on pipeline/earnings.py
does it when the 10-K is filed. The full-year figures below are the "Average Revenue Per Piece" line of each 10-K
(FY2024 $13.60 vs $13.62, 253 days, 22,418k a day; FY2025 $14.50 vs $13.60, 252 days, 20,847k a day).
Idempotent. Run: python3 tools/ups_q4_rpp.py"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import earnings  # noqa: E402
import filings  # noqa: E402

YEARS = {2024: {"days": 253, "adv": 22418, "rpp": 13.60}, 2025: {"days": 252, "adv": 20847, "rpp": 14.50}}
NOTE = "Calculated: UPS's full-year revenue per piece less its first three quarters (UPS doesn't print Q4 on its own); good to a few cents"


def apply(rows):
    by = {(r["company"], r["q"]): r for r in rows}
    changed = 0
    for y in sorted(YEARS):
        r = by.get(("UPS", f"Q4 {y}"))
        qs = [(by.get(("UPS", f"Q{i} {y}")) or {}).get("vol") or {} for i in (1, 2, 3)]
        if not r or not r.get("vol"):
            continue
        v = r["vol"]
        rpp = filings.q4_rpp(YEARS[y], qs)
        if rpp is None:
            continue
        prior = ((by.get(("UPS", f"Q4 {y - 1}")) or {}).get("vol") or {}).get("rpp")
        new = {"rpp": rpp, "rpp_prior": prior, "rpp_src": "calc", "rpp_note": NOTE}
        if any(v.get(k) != x for k, x in new.items()):
            v.update(new)
            changed += 1
    before = json.dumps(rows)
    earnings.fill_usps_rpp(rows)                                  # USPS: segment revenue over pieces
    return changed + (json.dumps(rows) != before)


def main():
    p = ROOT / "data" / "earnings.json"
    rows = json.loads(p.read_text())
    n = apply(rows)
    p.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    html = ROOT / "index.html"
    s = html.read_text()
    m = re.search(r"const EARN=(\[.*?\]);\n", s, re.S)
    if m and json.loads(m.group(1)) != rows:                      # keep the built-in copy in step with the data file
        seed = json.loads(m.group(1))
        apply(seed)
        s = s[:m.start(1)] + json.dumps(seed, separators=(",", ":"), ensure_ascii=False) + s[m.end(1):]
        html.write_text(s)
    print("updated", n, "quarters")


if __name__ == "__main__":
    main()
