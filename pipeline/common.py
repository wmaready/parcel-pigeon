"""Shared helpers for the Parcel Pigeon pipeline."""
import hashlib, json, os, re, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "Mozilla/5.0 (ParcelPigeon news reader; +https://github.com)"}
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_FAST = os.environ.get("PW_MODEL_FAST", "claude-haiku-5-5")
MODEL_WRITE = os.environ.get("PW_MODEL_WRITE", "claude-sonnet-5-5")


def load(name, default):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return default
    return default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False))


def h(s):
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:12]


def get(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def claude(model, system, user, max_tokens=1500):
    """Call the Claude Messages API and return the text reply."""
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    for attempt in range(3):
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=120,
        )
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    raise RuntimeError("Claude API unavailable after retries")


def parse_json(text):
    """Pull the first JSON object or array out of a model reply. If the reply was cut off mid-list,
    keep every complete item instead of failing."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    try:
        return json.loads(m.group(1) if m else text)
    except json.JSONDecodeError:
        start = text.find("[")
        if start < 0:
            raise
        dec, out, i = json.JSONDecoder(), [], start + 1
        while True:
            while i < len(text) and text[i] in " \r\n\t,":
                i += 1
            if i >= len(text) or text[i] == "]":
                break
            try:
                obj, i = dec.raw_decode(text, i)
            except json.JSONDecodeError:
                break
            out.append(obj)
        if not out:
            raise
        return out


NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")


def numbers_supported(story_text, source_text):
    """Every number in the story must appear in the source. Returns the unsupported ones."""
    src = source_text.replace(",", "")
    missing = []
    for n in set(NUM.findall(story_text)):
        core = n.replace("$", "").replace("%", "").replace(",", "")
        if not core or core in {"1", "2", "3"}:  # impact levels, list counts
            continue
        base = core.rstrip("0").rstrip(".") if "." in core else core
        pat = r"(?<![\d.])" + re.escape(base) + (r"0*" if "." in core else "") + r"(?![\d])"
        if not re.search(pat, src):
            missing.append(n)
    return missing


# Sources that come straight from the company or regulator. These lead every story; trade press follows.
PRIMARY_DOMAINS = ["ups.com", "fedex.com", "usps.com", "prc.gov", "dhl.com", "ontrac.com", "amazon.com", "aboutamazon.com",
                   "uniuni.com", "gofo.com", "speedeedelivery.com", "gls-us.com", "lso.com", "shipveho.com", "bettertrucks.com",
                   "jitsu.com", "cdldelivery.com", "sec.gov", "federalregister.gov", "congress.gov", "uspsoig.gov",
                   "businesswire.com", "prnewswire.com", "globenewswire.com"]


def is_primary(url):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return any(host == d or host.endswith("." + d) for d in PRIMARY_DOMAINS)


def primary_first(srcs):
    """Carrier or company sources first (stable order otherwise)."""
    return sorted(srcs, key=lambda s: 0 if is_primary(s.get("url")) else 1)
