"""Publish approved drafts: any open GitHub issue labeled `publish` goes live on the site, then closes.
Edits you make to the TITLE / SUMMARY / EFFECT / TODO lines in the issue are used."""
import json, os, re, sys
import requests
from common import load, save

FIELDS = {"TITLE": "title", "SUMMARY": "sum", "EFFECT": "plain"}


def main():
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    issues = requests.get(f"https://api.github.com/repos/{repo}/issues", params={"labels": "publish", "state": "open"}, headers=hdr, timeout=30).json()
    live = load("news.json", [])
    for iss in issues:
        body = iss.get("body") or ""
        m = re.search(r"<!-- parcelwatch-data\s*(\{.*?\})\s*-->", body, re.S)
        if not m:
            continue
        story = json.loads(m.group(1))
        for label, key in FIELDS.items():
            f = re.search(rf"^{label}:\s*(.+)$", body, re.M)
            if f and f.group(1).strip():
                story[key] = f.group(1).strip()
        story.pop("unsupported_numbers", None)
        extras = story.pop("_extras", None) or {}
        if not any(s.get("id") == story["id"] for s in live):
            live.insert(0, story)
            if extras:
                try:
                    from news import publish_extras
                    publish_extras(story, extras, live)
                except Exception as e:
                    print(f"  extras: {e}", file=sys.stderr)
        requests.post(f"{iss['url']}/comments", headers=hdr, json={"body": "Published to Parcel Pigeon."}, timeout=30)
        requests.patch(iss["url"], headers=hdr, json={"state": "closed"}, timeout=30)
        print(f"published: {story['title']}")
    live.sort(key=lambda s: s["date"], reverse=True)
    save("news.json", live)


if __name__ == "__main__":
    main()
