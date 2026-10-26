"""Reading package figures straight from a carrier's filing (used by earnings.py for new quarters).

Only figures printed in the filing are taken, and only when they pass their own cross-checks: the year-over-year change
printed beside a figure must match the figure and its prior-year value, and the prior-year value must equal the one
already on file for that quarter. Anything that doesn't check out is left empty and sent to review."""
import html as _html, re
from html.parser import HTMLParser


class _Text(HTMLParser):
    """HTML to text that keeps each table row on one line, cells split by ' | '."""
    def __init__(self):
        super().__init__(); self.out, self.row, self.cell, self.skip = [], None, [], 0

    def handle_starttag(self, t, a):
        if t in ("script", "style"): self.skip += 1
        elif t == "tr": self.row = []
        elif t in ("td", "th"): self.cell = []
        elif t in ("br", "p", "div") and self.row is None: self.out.append("\n")

    def handle_endtag(self, t):
        if t in ("script", "style"): self.skip -= 1
        elif t in ("td", "th") and self.row is not None:
            c = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            if c: self.row.append(c)
        elif t == "tr" and self.row is not None:
            if self.row: self.out.append("\n" + " | ".join(self.row) + "\n")
            self.row = None
        elif t in ("p", "div") and self.row is None: self.out.append("\n")

    def handle_data(self, d):
        if not self.skip:
            (self.cell if self.row is not None else self.out).append(d)


def to_text(raw):
    p = _Text(); p.feed(raw)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", _html.unescape("".join(p.out))))


def _num(s):
    return float(s.replace(",", "").replace("(", "-").replace(")", ""))


def table_row(text, label):
    """The numbers on the first table line that starts with label, or None."""
    m = re.search(r"^" + re.escape(label) + r" \|(.*)$", text, re.M)
    if not m:
        return None
    return [_num(c) for c in (x.strip() for x in m.group(1).split("|")) if re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?", c)]


def ups_quarter(text):
    """UPS 10-Q: the quarter's operating days, packages a day (worldwide and U.S. domestic) and revenue per piece, with
    their prior-year values and UPS's printed changes. None when a line is missing or a printed change doesn't match."""
    days = table_row(text, "Operating Days")
    adv = table_row(text, "Average Daily Package Volume (in thousands)")
    rpp = table_row(text, "Average Revenue Per Piece")
    us = table_row(text, "Total Average Daily Package Volume")
    if not (days and len(days) >= 2 and adv and len(adv) >= 3 and rpp and len(rpp) >= 4 and us and len(us) >= 3):
        return None
    out = {"days": int(days[0]), "adv_k": int(adv[0]), "adv_prior_k": int(adv[1]), "adv_yoy": adv[2],
           "us_adv_k": int(us[0]), "us_adv_prior_k": int(us[1]), "us_yoy": us[2], "rpp": rpp[0], "rpp_prior": rpp[1], "rpp_yoy": rpp[3]}
    pct = lambda a, b: round((a / b - 1) * 100, 1)
    if abs(pct(out["adv_k"], out["adv_prior_k"]) - out["adv_yoy"]) > 0.15 or abs(pct(out["us_adv_k"], out["us_adv_prior_k"]) - out["us_yoy"]) > 0.15 \
            or abs(pct(out["rpp"], out["rpp_prior"]) - out["rpp_yoy"]) > 0.15:
        return None
    return out


def ups_year(text):
    """UPS 10-K: the full year's operating days and packages a day (worldwide and U.S. domestic), this year and last, or
    None when a line is missing or the printed change doesn't match."""
    days = table_row(text, "Operating Days")
    adv = table_row(text, "Average Daily Package Volume (in thousands)")
    us = table_row(text, "Total Average Daily Package Volume")
    if not (days and len(days) >= 2 and adv and len(adv) >= 3 and us and len(us) >= 3):
        return None
    if abs(round((adv[0] / adv[1] - 1) * 100, 1) - adv[2]) > 0.15 or abs(round((us[0] / us[1] - 1) * 100, 1) - us[2]) > 0.15:
        return None
    return {"days": int(days[0]), "pdays": int(days[1]), "adv": adv[0], "padv": adv[1], "us": us[0], "pus": us[1]}


def q4_from_year(year, quarters):
    """Fourth-quarter packages a day: the full year less the first three quarters, weighted by operating days.
    quarters: the three quarters' vol blocks (days, adv_k, us_adv_k). Returns (worldwide, U.S. domestic, Q4 days), or None
    when a figure is missing."""
    if len(quarters) != 3 or any(q.get(k) is None for q in quarters for k in ("days", "adv_k", "us_adv_k")):
        return None
    d4 = year["days"] - sum(q["days"] for q in quarters)
    if d4 <= 0:
        return None
    adv = round((year["days"] * year["adv"] - sum(q["days"] * q["adv_k"] for q in quarters)) / d4)
    us = round((year["days"] * year["us"] - sum(q["days"] * q["us_adv_k"] for q in quarters)) / d4)
    return adv, us, d4
