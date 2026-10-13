"""Merge two versions of a data file that were both changed since they split (used when a push loses a race).
Nothing from either side is dropped: lists are unioned by identity, dates keep the later one, other values take the second file's.
Usage: python mergejson.py upstream.json mine.json out.json"""
import json, sys


def ident(x):
    if isinstance(x, dict):
        if "a" in x and "b" in x and "k" in x:
            return ("edge", x["a"], x["b"], x["k"])
        if "id" in x and "k" in x:
            return ("move", x["id"], x["k"], x.get("d"))
        if "id" in x:
            return ("id", x["id"])
        if "kind" in x and "n" in x:
            return ("rev", x["kind"], x["n"], x.get("why"))
    return ("raw", json.dumps(x, sort_keys=True))


def merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = merge(a[k], v) if k in a else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        out, pos = [], {}
        for x in a + b:
            k = ident(x)
            if k in pos:
                out[pos[k]] = merge(out[pos[k]], x) if isinstance(x, dict) else x
            else:
                pos[k] = len(out); out.append(x)
        return out
    if isinstance(a, str) and isinstance(b, str) and len(a) == len(b) == 10 and a[4] == b[4] == "-":
        return max(a, b)                      # a date: keep the later check
    return b


if __name__ == "__main__":
    up, mine = (json.load(open(f)) for f in sys.argv[1:3])
    json.dump(merge(up, mine), open(sys.argv[3], "w"), indent=1, ensure_ascii=False)
