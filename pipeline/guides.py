"""Coop's reference shelf: the text of the rate guides, service guides, surcharge, peak, GRI, fuel and terms documents
in the library, cut into short passages and published as data/guides.json. The Ask Coop service searches it for every
question, so answers quote the carriers' own documents instead of memory.

Built from the text snapshots docwatch already keeps (data/docwatch/*.txt.gz). Cheap: no API calls.
Usage: python guides.py
"""
import gzip, json, re
from common import ROOT, load, save, h, canon

SNAP = ROOT / "data" / "docwatch"
KEEP = {"Rate guide", "Service guide", "Terms", "Surcharges & fees", "Peak", "GRI notice", "Fuel", "Zones & DAS", "Special program", "Regulatory filing"}
CHUNK, MAX_PER_DOC, MAX_TOTAL = 1100, 160, 4000


def chunks(text):
    paras, out, cur = re.split(r"\n{1,}", text), [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(cur) + len(p) + 1 > CHUNK and cur:
            out.append(cur); cur = ""
        cur = (cur + "\n" + p).strip() if cur else p[:CHUNK * 2]
    if cur:
        out.append(cur)
    return out


def main():
    seed = load("seed.json", {})
    docs = {}
    for d in (seed.get("docs") or []) + load("docs.json", []):
        if d.get("u") and d.get("t") in KEEP and d.get("cur", True) is not False:
            docs.setdefault(canon(d["u"]), d)
    out_docs, out_chunks = [], []
    for u, d in sorted(docs.items(), key=lambda kv: (kv[1].get("c", ""), kv[1].get("t", ""), kv[1].get("n", ""))):
        p = SNAP / f"{h(d['u'])}.txt.gz"
        if not p.exists():
            p = SNAP / f"{h(u)}.txt.gz"
        if not p.exists():
            continue
        text = gzip.decompress(p.read_bytes()).decode(errors="ignore")
        cs = chunks(text)[:MAX_PER_DOC]
        if not cs:
            continue
        i = len(out_docs)
        out_docs.append({"c": d.get("c"), "t": d.get("t"), "n": d.get("n"), "y": d.get("y"), "u": d["u"]})
        out_chunks += [[i, c] for c in cs]
    # one file per carrier, so the app only downloads the shelf it needs for a question
    (ROOT / "data" / "guides").mkdir(parents=True, exist_ok=True)
    index = {}
    for c in sorted({d["c"] for d in out_docs if d.get("c")}):
        ids = [k for k, d in enumerate(out_docs) if d.get("c") == c]
        remap = {k: n for n, k in enumerate(ids)}
        part = {"docs": [out_docs[k] for k in ids], "chunks": [[remap[k], t] for k, t in out_chunks if k in remap][:MAX_TOTAL]}
        name = re.sub(r"[^A-Za-z0-9]+", "-", c).strip("-").lower() + ".json"
        (ROOT / "data" / "guides" / name).write_text(json.dumps(part, ensure_ascii=False, separators=(",", ":")))
        index[c] = {"file": "data/guides/" + name, "docs": len(ids), "passages": len(part["chunks"])}
    save("guides/index.json", index)
    print(f"guides: {len(out_docs)} documents, {len(out_chunks)} passages for Ask Coop, {len(index)} carriers")


if __name__ == "__main__":
    main()
