"""Publish held stories you've OK'd. An open GitHub issue labeled `draft` (or `needs-ok`) goes live when you reply
`run` (or `publish`, `yes`, `ok`, `send`) or add the `publish` label; replying `skip` (or `no`, `drop`, `hold`) closes it.
Edits you make to the TITLE / SUMMARY / EFFECT lines in the issue are used. Only the repo owner's replies count."""
import json, os, re, sys
import requests
from common import load, save, apply_doc_effective

FIELDS = {"TITLE": "title", "SUMMARY": "sum", "EFFECT": "plain"}
GO = re.compile(r"^(run|publish|yes|ok|okay|send|approve|approved|go)\b", re.I)
NO = re.compile(r"^(skip|no|drop|hold|stop|cancel|kill)\b", re.I)


def decision(iss, hdr, owner):
    if any(l.get("name") == "publish" for l in iss.get("labels", [])):
        return "run"
    out = None
    if not iss.get("comments"):
        return None
    for c in requests.get(f"{iss['url']}/comments", headers=hdr, params={"per_page": 100}, timeout=30).json():
        if c.get("author_association") != "OWNER" and (c.get("user") or {}).get("login") != owner:
            continue
        w = (c.get("body") or "").strip()
        if GO.match(w):
            out = "run"
        elif NO.match(w):
            out = "skip"
    return out


def main():
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return
    owner = repo.split("/")[0]
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    seen, issues = set(), []
    for lab in ("publish", "draft", "needs-ok"):
        for iss in requests.get(f"https://api.github.com/repos/{repo}/issues", params={"labels": lab, "state": "open", "per_page": 50},
                                headers=hdr, timeout=30).json():
            if isinstance(iss, dict) and iss.get("number") not in seen and not iss.get("pull_request"):
                seen.add(iss["number"]); issues.append(iss)
    live = load("news.json", [])
    approved = load("approved.json", [])
    changed = False
    for iss in issues:
        body = iss.get("body") or ""
        m = re.search(r"<!-- parcelwatch-data\s*(\{.*?\})\s*-->", body, re.S)
        if not m:
            continue
        d = decision(iss, hdr, owner)
        if d is None:
            continue
        if d == "skip":
            requests.post(f"{iss['url']}/comments", headers=hdr, json={"body": "Skipped. It stays off the site."}, timeout=30)
            requests.patch(iss["url"], headers=hdr, json={"state": "closed", "state_reason": "not_planned"}, timeout=30)
            print(f"skipped: {iss.get('title')}")
            continue
        try:
            story = json.loads(m.group(1))
        except Exception as e:
            print(f"publish: draft #{iss.get('number')} has unreadable story data ({e}); skipped"); continue
        for label, key in FIELDS.items():
            f = re.search(rf"^{label}:\s*(.+)$", body, re.M)
            if f and f.group(1).strip():
                if story.get(key) != f.group(1).strip():
                    # your edit wins on the story page too: the written synopsis / "affects" list it replaces is dropped
                    story.pop({"sum": "syn", "plain": "aff"}.get(key, ""), None)
                story[key] = f.group(1).strip()
        story.pop("unsupported_numbers", None)
        apply_doc_effective(story, load("docs.json", []))      # the library knows the date the document prints
        extras = story.pop("_extras", None) or {}
        if not any(s.get("id") == story["id"] for s in live):
            live.insert(0, story); changed = True
            if extras:
                try:
                    from news import publish_extras
                    publish_extras(story, extras, live)
                except Exception as e:
                    print(f"  extras: {e}", file=sys.stderr)
        # you already OK'd it, so if it's big the phone alert goes out without a second approval
        if story["id"] not in approved:
            approved.append(story["id"])
        requests.post(f"{iss['url']}/comments", headers=hdr, json={"body": "Published to Parcel Pigeon."}, timeout=30)
        requests.patch(iss["url"], headers=hdr, json={"state": "closed"}, timeout=30)
        print(f"published: {story['title']}")
    if changed:
        live.sort(key=lambda s: s["date"], reverse=True)
        save("news.json", live)
    save("approved.json", approved[-500:])


if __name__ == "__main__":
    main()
