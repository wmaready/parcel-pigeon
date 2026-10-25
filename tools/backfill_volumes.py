"""Package volumes for Docs › Earnings and Today, read from the carriers' own reports (saved as text by the one-off
fetch_filings job on branch claude/fetch-filings). Usage: python tools/backfill_volumes.py <filings dir>. Idempotent.

- UPS: 10-Q "Average Daily Package Volume", U.S. Domestic "Total Average Daily Package Volume", "Average Revenue Per
  Piece" and "Operating Days" (Q1-Q3). Q4 isn't printed on its own: its packages a day are calculated as the 10-K's
  full year less the three 10-Qs (this reproduces UPS's own published Q4 U.S. figures), and its revenue per piece is
  left empty. The Q4 U.S. domestic figure is UPS's own, from the next Q4 release where it's printed.
- FedEx: the Q4 FY26 stat book (Federal Express segment, every quarter on one five-days-a-week basis): total ADV,
  total U.S. domestic ADV and composite package yield.
- USPS: the quarterly results releases (Shipping and Packages pieces and revenue, total operating revenue). USPS
  reports pieces per quarter; packages a day is pieces over the quarter's calendar days, marked calculated.
Never estimates: a figure not printed by the company stays null."""
import calendar, json, re, sys
from pathlib import Path

F = Path(sys.argv[1] if len(sys.argv) > 1 else "filings")
DATA = Path(__file__).resolve().parent.parent / "data" / "earnings.json"
CHECKED = "2026-10-25"
num = lambda s: float(s.replace(",", "").replace("(", "-").replace(")", ""))


def text(name):
    t = (F / name).read_text()
    return t, t.split("\n", 1)[0].replace("SOURCE: ", "").strip()


def row(t, label, n=None):
    """The numbers on the first line starting with label (table cells split by |)."""
    m = re.search(r"^" + re.escape(label) + r" \|(.*)$", t, re.M)
    if not m:
        raise SystemExit(f"missing {label!r}")
    cells = [c.strip() for c in m.group(1).split("|")]
    out = [num(c) for c in cells if re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?", c)]
    return out[:n] if n else out


def ups():
    Q = {}
    for y in (2024, 2025, 2026):
        for q in (1, 2, 3):
            p = F / f"UPS-Q{q}{y}-filing.txt"
            if not p.exists():
                continue
            t, src = text(p.name)
            days = row(t, "Operating Days")
            adv = row(t, "Average Daily Package Volume (in thousands)")
            rpp = row(t, "Average Revenue Per Piece")
            us = row(t, "Total Average Daily Package Volume")
            Q[(y, q)] = dict(days=int(days[0]), pdays=int(days[1]), adv=adv[0], padv=adv[1], yoy=adv[2], rpp=rpp[0], prpp=rpp[1],
                             us=us[0], pus=us[1], src=src)
        p = F / f"UPS-Q4{y}-filing.txt"
        if p.exists():                                   # the 10-K: full year, this year and last
            t, src = text(p.name)
            days, adv, us = row(t, "Operating Days"), row(t, "Average Daily Package Volume (in thousands)"), row(t, "Total Average Daily Package Volume")
            Q[(y, "FY")] = dict(days=int(days[0]), pdays=int(days[1]), adv=adv[0], padv=adv[1], us=us[0], pus=us[1], src=src)
    def q4(y, k, prior=False):
        fy, qs = Q[(y, "FY")], [Q[(y, q)] for q in (1, 2, 3)]
        D, A = ("pdays", "p" + k) if prior else ("days", k)
        rest = sum(x[D] * x[A] for x in qs)
        d4 = fy[D] - sum(x[D] for x in qs)
        return round((fy[D] * fy[A] - rest) / d4), d4
    out = {}
    for (y, q), v in Q.items():
        if q == "FY":
            continue
        out[f"Q{q} {y}"] = {"adv_k": int(v["adv"]), "adv_prior_k": int(v["padv"]), "adv_yoy": v["yoy"], "scope": "UPS global small package",
                            "basis": "operating days", "days": v["days"], "us_adv_k": int(v["us"]), "us_adv_prior_k": int(v["pus"]),
                            "rpp": v["rpp"], "rpp_prior": v["prpp"], "pieces_m": round(v["adv"] * v["days"] / 1000, 1), "pieces_src": "calc",
                            "src": v["src"], "checked": CHECKED}
    for y in (2024, 2025):
        if (y, "FY") not in Q:
            continue
        a, d4 = q4(y, "adv"); pa, _ = q4(y, "adv", True)
        us, _ = q4(y, "us"); pus, _ = q4(y, "us", True)
        # UPS prints the Q4 U.S. domestic packages a day in its Q4 2025 release (this year and last): use its own figure
        rel = F / "UPS-Q42025-release.txt"
        if rel.exists():
            t, rsrc = text(rel.name)
            m = re.search(r"^Operating Days \| 62 \| 62\n+Average Daily U.S. Domestic Package Volume \(in thousands\) \| ([\d,]+) \| ([\d,]+)", t, re.M)
            if m:
                cur, prev = int(num(m.group(1))), int(num(m.group(2)))
                if y == 2025: assert abs(cur - us) <= 2, (cur, us); us = cur; pus_check = prev
                if y == 2024: assert abs(prev - us) <= 2, (prev, us); us = prev
        out[f"Q4 {y}"] = {"adv_k": a, "adv_prior_k": pa, "adv_yoy": round((a / pa - 1) * 100, 1), "adv_src": "calc",
                          "adv_note": "Calculated: UPS's full-year figure less its first three quarters (UPS doesn't print Q4 on its own)",
                          "scope": "UPS global small package", "basis": "operating days", "days": d4, "us_adv_k": us, "us_adv_prior_k": pus,
                          "rpp": None, "rpp_prior": None, "pieces_m": round(a * d4 / 1000, 1), "pieces_src": "calc",
                          "src": Q[(y, "FY")]["src"], "checked": CHECKED}
    return out


def fedex():
    t, src = text("FedEx-FY26Q4-statbook.txt")
    out = {}
    # the quarterly pages: "FY 2023 FY 2024" (8 quarters) then "FY 2025 FY 2026"; each "Total ADV" line has 8 numbers
    blocks = re.split(r"^FY (\d{4}) FY (\d{4})\nFIRST\nQUARTER", t, flags=re.M)
    for i in range(1, len(blocks), 3):
        y1, y2, body = blocks[i], blocks[i + 1], blocks[i + 2]
        if "Total ADV" not in body or f"FY{y1[2:]} Q1" in out:   # FedEx Freight's pages share the heading; first page wins
            continue
        def get(lab):   # the first line with this label carrying eight quarters (the annual page has four)
            for m in re.finditer(r"^" + re.escape(lab) + r"\s+(.*)$", body, re.M):
                v = [num(x) for x in m.group(1).replace("$", " ").split()]
                if len(v) == 8:
                    return v
        tot, us, yld = get("Total ADV"), get("Total U.S. domestic ADV"), get("Composite package yield")
        if not (tot and us and yld):
            continue
        for j, fy in enumerate([y1] * 4 + [y2] * 4):
            out[f"FY{fy[2:]} Q{j % 4 + 1}"] = (int(tot[j]), int(us[j]), yld[j])
    rows = {}
    for k, (tot, us, yld) in out.items():
        fy, q = int(k[2:4]), k[-2:]
        prev = out.get(f"FY{fy - 1} {q}")
        rows[k] = {"adv_k": tot, "adv_prior_k": prev and prev[0], "adv_yoy": prev and round((tot / prev[0] - 1) * 100, 1),
                   "scope": "Federal Express segment", "basis": "five days a week", "days": None, "us_adv_k": us,
                   "us_adv_prior_k": prev and prev[1], "rpp": yld, "rpp_prior": prev and prev[2], "pieces_m": None,
                   "src": src, "checked": CHECKED}
    return rows


def usps():
    rows = []
    for p in sorted(F.glob("USPS-*.txt")):
        t, src = text(p.name)
        m = re.search(r"(first|second|third|fourth)-quarter-fiscal-year-(\d{4})", src)
        if not m:
            continue
        q = ["first", "second", "third", "fourth"].index(m.group(1)) + 1
        fy = int(m.group(2))
        sp = [num(x) for x in re.search(r"^Shipping and Packages\s+([\d,\s]+)$", t, re.M).group(1).split()]
        tot = [num(x) for x in re.search(r"^Total operating revenue and volume \$\s*([\d,]+)\s+\$\s*([\d,]+)", t, re.M).groups()]
        y0 = fy - 1 if q == 1 else fy                          # FY Q1 is Oct-Dec of the year before
        m0 = {1: 10, 2: 1, 3: 4, 4: 7}[q]
        start, endm = f"{y0}-{m0:02d}-01", m0 + 2
        end = f"{y0}-{endm:02d}-{calendar.monthrange(y0, endm)[1]}"
        days = sum(calendar.monthrange(y0, mm)[1] for mm in range(m0, m0 + 3))
        pdays = sum(calendar.monthrange(y0 - 1, mm)[1] for mm in range(m0, m0 + 3))
        d = re.search(r"/(\d{4})/(\d{2})(\d{2})-usps", src)
        rows.append({"company": "USPS", "q": f"FY{str(fy)[2:]} Q{q}", "label": f"FY{str(fy)[2:]} Q{q}", "d": f"{d.group(1)}-{d.group(2)}-{d.group(3)}",
                     "rev": round(tot[0] / 1000, 1), "rev_m": int(tot[0]), "rev_prior_m": int(tot[1]), "yoy_src": "calc",
                     "revYoY": round((tot[0] / tot[1] - 1) * 100, 1), "eps": None, "take": None, "release": src, "transcript": None,
                     "webcast": None, "filing": None, "period": {"start": start, "end": end, "months": 3}, "comparable": True,
                     "vol": {"pieces_m": int(sp[2]), "pieces_prior_m": int(sp[3]), "pieces_src": "USPS",
                             "adv_k": round(sp[2] * 1000 / days), "adv_prior_k": round(sp[3] * 1000 / pdays),
                             "adv_yoy": round((sp[2] / sp[3] - 1) * 100, 1), "adv_src": "calc",
                             "adv_note": f"Calculated: {int(sp[2]):,} million Shipping and Packages pieces over the quarter's {days} calendar days (USPS reports pieces per quarter)",
                             "scope": "USPS Shipping and Packages", "basis": "calendar days", "days": days, "us_adv_k": None, "us_adv_prior_k": None,
                             "rpp": None, "rpp_prior": None, "sp_rev_m": int(sp[0]), "sp_rev_prior_m": int(sp[1]),
                             "src": src, "checked": CHECKED}})
    return rows


rows = json.loads(DATA.read_text())
U, X = ups(), fedex()
SAME = ("adv_k", "adv_prior_k", "us_adv_k", "rpp", "rpp_prior", "days")
for r in rows:
    new = (U if r.get("company") == "UPS" else X if r.get("company") == "FedEx" else {}).get(r.get("q"))
    old = r.get("vol") or {}
    if new and not all(old.get(k) == new.get(k) for k in SAME):      # a figure already checked and unchanged keeps its check
        r["vol"] = new
rows = [r for r in rows if r.get("company") != "USPS"] + usps()
DATA.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
for r in rows:
    v = r.get("vol") or {}
    print(f"{r['company']:13} {r['q']:8} adv {v.get('adv_k')} prior {v.get('adv_prior_k')} yoy {v.get('adv_yoy')} us {v.get('us_adv_k')} rpp {v.get('rpp')} {v.get('adv_src','')}")
