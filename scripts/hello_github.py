"""Smoke test for GitHub API access. Zero external dependencies (stdlib only).

Usage:
    1. Create .env from .env.example and paste your GITHUB_TOKEN
    2. Run: py scripts/hello_github.py
    3. Should print your username, rate limit, and one sample issue.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def gh(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "oss-engine-smoke-test",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        headers = dict(resp.headers)
    return {"body": body, "headers": headers}


def main() -> int:
    load_env(Path(__file__).parent.parent / ".env")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token or token.startswith("github_pat_paste"):
        print("ERROR: GITHUB_TOKEN not set in .env")
        return 1

    try:
        me = gh("/user", token)
        print(f"Authenticated as: {me['body']['login']}")
        print(f"Account name:     {me['body'].get('name') or '(none)'}")
        print(f"Public repos:     {me['body']['public_repos']}")

        rl = gh("/rate_limit", token)
        core = rl["body"]["resources"]["core"]
        search = rl["body"]["resources"]["search"]
        print(f"\nRate limit (core):   {core['remaining']}/{core['limit']}")
        print(f"Rate limit (search): {search['remaining']}/{search['limit']}")

        print("\nSample search: 1 'good first issue' in Python")
        q = "label:%22good+first+issue%22+language:python+state:open"
        search_resp = gh(f"/search/issues?q={q}&per_page=1", token)
        if search_resp["body"]["items"]:
            issue = search_resp["body"]["items"][0]
            print(f"  Title:  {issue['title']}")
            print(f"  Repo:   {issue['repository_url'].split('/repos/')[-1]}")
            print(f"  URL:    {issue['html_url']}")

        print("\nGitHub API access OK.")
        return 0

    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.reason}")
        if e.code == 401:
            print("  Token is invalid or expired. Regenerate at github.com/settings/tokens")
        elif e.code == 403:
            print("  Forbidden. Check token permissions or rate limit.")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
