"""
GitHub API client — handles PR creation, branch checks, and repo info.
Uses only the standard `requests` library, no extra GitHub SDK needed.
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger("nastech_sync.github_api")


class GitHubAPI:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str, repo: str):
        self.token = token
        self.owner = owner
        self.repo = repo
        self._repo_url = f"{self.BASE}/repos/{owner}/{repo}"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------------
    # Repo
    # ------------------------------------------------------------------

    def repo_info(self) -> dict:
        r = requests.get(self._repo_url, headers=self._headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def authenticated_user(self) -> dict:
        r = requests.get(f"{self.BASE}/user", headers=self._headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def default_branch(self) -> str:
        return self.repo_info().get("default_branch", "main")

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,      # branch name to merge FROM
        base: str = "main",
        draft: bool = False,
    ) -> dict:
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        r = requests.post(
            f"{self._repo_url}/pulls",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        if r.status_code == 422:
            # May already exist — try to find it
            existing = self.find_pr_for_branch(head, base)
            if existing:
                logger.info("PR already exists: %s", existing.get("html_url"))
                return existing
        r.raise_for_status()
        return r.json()

    def list_pull_requests(self, state: str = "open", head: Optional[str] = None) -> list[dict]:
        params: dict = {"state": state, "per_page": 50}
        if head:
            params["head"] = f"{self.owner}:{head}"
        r = requests.get(
            f"{self._repo_url}/pulls",
            headers=self._headers,
            params=params,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def find_pr_for_branch(self, head: str, base: str = "main") -> Optional[dict]:
        prs = self.list_pull_requests(state="open", head=head)
        for pr in prs:
            if pr.get("base", {}).get("ref") == base:
                return pr
        return None

    def pr_already_open(self, head: str, base: str = "main") -> bool:
        return self.find_pr_for_branch(head, base) is not None

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def branch_exists(self, branch: str) -> bool:
        r = requests.get(
            f"{self._repo_url}/branches/{branch}",
            headers=self._headers,
            timeout=10,
        )
        return r.status_code == 200

    def list_branches(self, prefix: str = "") -> list[str]:
        r = requests.get(
            f"{self._repo_url}/branches",
            headers=self._headers,
            params={"per_page": 100},
            timeout=20,
        )
        r.raise_for_status()
        names = [b["name"] for b in r.json()]
        if prefix:
            names = [n for n in names if n.startswith(prefix)]
        return names

    # ------------------------------------------------------------------
    # Rate limit check
    # ------------------------------------------------------------------

    def rate_limit(self) -> dict:
        r = requests.get(f"{self.BASE}/rate_limit", headers=self._headers, timeout=10)
        r.raise_for_status()
        return r.json().get("rate", {})
