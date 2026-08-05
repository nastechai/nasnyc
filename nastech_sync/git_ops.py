"""
Git operations wrapper — thin layer over subprocess git commands.
All heavy lifting uses plain git so no extra Python lib is required.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nastech_sync.git_ops")


def _run(cmd: list[str], cwd: Optional[str] = None, env: Optional[dict] = None,
         capture: bool = True) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    logger.debug("git cmd: %s (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=full_env,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        logger.debug("stderr: %s", result.stderr.strip())
    return result


class GitRepo:
    def __init__(self, local_path: str, user_name: str = "NasTech-Agent",
                 user_email: str = "agent@nastechai.com"):
        self.path = Path(local_path)
        self.user_name = user_name
        self.user_email = user_email

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        return (self.path / ".git").is_dir()

    def clone(self, url: str, branch: str = "main", token: Optional[str] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        auth_url = _inject_token(url, token)
        logger.info("Cloning %s → %s", url, self.path)
        _run(["git", "clone", "--branch", branch, "--depth", "1",
              auth_url, str(self.path)])
        self._configure_identity()

    def init_empty(self, url: str, branch: str = "main") -> None:
        """Create a bare local repo with a remote set, no clone."""
        self.path.mkdir(parents=True, exist_ok=True)
        _run(["git", "init", "-b", branch], cwd=str(self.path))
        _run(["git", "remote", "add", "origin", url], cwd=str(self.path))
        self._configure_identity()

    def set_remote_url(self, url: str, remote: str = "origin",
                       token: Optional[str] = None) -> None:
        auth_url = _inject_token(url, token)
        _run(["git", "remote", "set-url", remote, auth_url], cwd=str(self.path))

    def _configure_identity(self) -> None:
        _run(["git", "config", "user.name", self.user_name], cwd=str(self.path))
        _run(["git", "config", "user.email", self.user_email], cwd=str(self.path))

    # ------------------------------------------------------------------
    # Fetch / pull
    # ------------------------------------------------------------------

    def fetch(self, remote: str = "origin", branch: str = "main",
              token: Optional[str] = None) -> None:
        if token:
            url = self.remote_url(remote)
            self.set_remote_url(url, remote, token)
        logger.info("Fetching %s/%s", remote, branch)
        _run(["git", "fetch", remote, branch], cwd=str(self.path))

    def pull(self, remote: str = "origin", branch: str = "main") -> None:
        logger.info("Pulling %s/%s", remote, branch)
        _run(["git", "pull", remote, branch, "--ff-only"], cwd=str(self.path))

    def reset_hard(self, ref: str = "HEAD") -> None:
        _run(["git", "reset", "--hard", ref], cwd=str(self.path))

    # ------------------------------------------------------------------
    # Commit history queries
    # ------------------------------------------------------------------

    def head_sha(self) -> str:
        r = _run(["git", "rev-parse", "HEAD"], cwd=str(self.path))
        return r.stdout.strip()

    def remote_head_sha(self, remote: str = "origin", branch: str = "main") -> str:
        r = _run(["git", "rev-parse", f"{remote}/{branch}"], cwd=str(self.path))
        return r.stdout.strip()

    def log_since(self, since_sha: str, until: str = "HEAD") -> list[dict]:
        """Return commits between since_sha (exclusive) and until (inclusive)."""
        fmt = "%H\x1f%s\x1f%an\x1f%ae\x1f%ai"
        r = _run(
            ["git", "log", f"{since_sha}..{until}", f"--format={fmt}", "--reverse"],
            cwd=str(self.path),
        )
        commits = []
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) >= 5:
                commits.append({
                    "sha": parts[0],
                    "subject": parts[1],
                    "author_name": parts[2],
                    "author_email": parts[3],
                    "date": parts[4],
                })
        return commits

    def all_files(self, ref: str = "HEAD") -> list[str]:
        """Return all tracked file paths at the given ref."""
        r = _run(["git", "ls-tree", "-r", "--name-only", ref], cwd=str(self.path))
        return [line for line in r.stdout.strip().splitlines() if line]

    def changed_files(self, from_sha: str, to_sha: str) -> list[tuple[str, str]]:
        """Return [(status, path)] for files changed between two commits."""
        r = _run(
            ["git", "diff", "--name-status", from_sha, to_sha],
            cwd=str(self.path),
        )
        results = []
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                results.append((parts[0], parts[1]))
        return results

    def show_file_at(self, sha: str, rel_path: str, dest: Path) -> bool:
        """Write the file content at a given commit to dest. Returns True on success."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = _run(["git", "show", f"{sha}:{rel_path}"], cwd=str(self.path))
        if r.returncode != 0:
            return False
        dest.write_bytes(r.stdout.encode() if isinstance(r.stdout, str) else r.stdout)
        return True

    def show_file_bytes_at(self, sha: str, rel_path: str) -> Optional[bytes]:
        """Return raw file bytes at a given commit, or None if missing."""
        result = subprocess.run(
            ["git", "show", f"{sha}:{rel_path}"],
            cwd=str(self.path),
            capture_output=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout

    # ------------------------------------------------------------------
    # Working tree / staging
    # ------------------------------------------------------------------

    def checkout_ref(self, ref: str) -> None:
        _run(["git", "checkout", ref], cwd=str(self.path))

    def add_all(self) -> None:
        _run(["git", "add", "-A"], cwd=str(self.path))

    def commit(self, message: str, author_name: Optional[str] = None,
               author_email: Optional[str] = None,
               author_date: Optional[str] = None) -> Optional[str]:
        env: dict = {}
        if author_name:
            env["GIT_AUTHOR_NAME"] = author_name
        if author_email:
            env["GIT_AUTHOR_EMAIL"] = author_email
        if author_date:
            env["GIT_AUTHOR_DATE"] = author_date
            env["GIT_COMMITTER_DATE"] = author_date

        r = _run(["git", "commit", "-m", message], cwd=str(self.path), env=env)
        if r.returncode != 0:
            if "nothing to commit" in r.stdout + r.stderr:
                logger.debug("Nothing to commit, skipping.")
                return None
            logger.error("git commit failed: %s", r.stderr)
            return None
        sha = self.head_sha()
        logger.info("Committed %s: %s", sha[:8], message[:72])
        return sha

    def has_staged_changes(self) -> bool:
        r = _run(["git", "diff", "--cached", "--quiet"], cwd=str(self.path))
        return r.returncode != 0

    def has_uncommitted_changes(self) -> bool:
        r = _run(["git", "status", "--porcelain"], cwd=str(self.path))
        return bool(r.stdout.strip())

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def current_branch(self) -> str:
        r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(self.path))
        return r.stdout.strip()

    def create_branch(self, branch_name: str, from_ref: str = "HEAD") -> None:
        """Create and checkout a new local branch."""
        _run(["git", "checkout", "-b", branch_name, from_ref], cwd=str(self.path))
        logger.debug("Created branch: %s", branch_name)

    def checkout_branch(self, branch_name: str) -> None:
        """Checkout an existing branch."""
        _run(["git", "checkout", branch_name], cwd=str(self.path))

    def branch_exists_locally(self, branch_name: str) -> bool:
        r = _run(["git", "branch", "--list", branch_name], cwd=str(self.path))
        return bool(r.stdout.strip())

    def push(self, remote: str = "origin", branch: str = "main",
             force: bool = False, token: Optional[str] = None) -> bool:
        if token:
            url = self.remote_url(remote)
            self.set_remote_url(url, remote, token)

        cmd = ["git", "push", remote, f"HEAD:{branch}"]
        if force:
            cmd.append("--force")

        logger.info("Pushing to %s/%s", remote, branch)
        r = _run(cmd, cwd=str(self.path))
        if r.returncode != 0:
            logger.error("Push failed: %s", r.stderr)
            return False
        logger.info("Push succeeded.")
        return True

    def push_branch(self, branch_name: str, remote: str = "origin",
                    token: Optional[str] = None) -> bool:
        """Push a named branch and set upstream tracking."""
        if token:
            url = self.remote_url(remote)
            self.set_remote_url(url, remote, token)
        cmd = ["git", "push", "-u", remote, branch_name]
        logger.info("Pushing branch %s → %s", branch_name, remote)
        r = _run(cmd, cwd=str(self.path))
        if r.returncode != 0:
            logger.error("Branch push failed: %s", r.stderr)
            return False
        logger.info("Branch push succeeded: %s", branch_name)
        return True

    # ------------------------------------------------------------------
    # Remote info
    # ------------------------------------------------------------------

    def remote_url(self, remote: str = "origin") -> str:
        r = _run(["git", "remote", "get-url", remote], cwd=str(self.path))
        # Strip embedded tokens if present
        url = r.stdout.strip()
        if "@" in url and url.startswith("https://"):
            url = "https://" + url.split("@", 1)[1]
        return url

    def branch_exists_on_remote(self, remote: str, branch: str) -> bool:
        r = _run(["git", "ls-remote", "--heads", remote, branch], cwd=str(self.path))
        return bool(r.stdout.strip())


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _inject_token(url: str, token: Optional[str]) -> str:
    """Inject a GitHub PAT into an https:// URL for auth."""
    if not token:
        return url
    if url.startswith("https://"):
        return url.replace("https://", f"https://{token}@", 1)
    return url
