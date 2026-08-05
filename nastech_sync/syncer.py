"""
Core sync engine — PR-based workflow.

Flow:
  1. Ensure upstream (NousResearch/hermes-agent) is cloned/up-to-date.
  2. Ensure downstream (nastechai/NasTech-Agent) is cloned/up-to-date.
  3. Read the last-synced upstream SHA from the state file.
  4. Collect all new upstream commits since that SHA.
  5. Create a sync branch: nastech-sync/YYYYMMDD-<sha>
  6. For each commit: apply NasTech branding to changed files, commit to branch.
  7. Push branch to GitHub.
  8. Open a Pull Request via GitHub API (never push directly to main).
  9. Save the new last-synced SHA.
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import NasTechSyncConfig
from .brander import Brander
from .git_ops import GitRepo

logger = logging.getLogger("nastech_sync.syncer")


class SyncResult:
    def __init__(self):
        self.commits_synced: int = 0
        self.files_branded: int = 0
        self.files_copied: int = 0
        self.errors: list[str] = []
        self.pr_url: Optional[str] = None
        self.branch_name: Optional[str] = None
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None

    def finish(self):
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def __str__(self):
        parts = [
            f"Synced {self.commits_synced} commits",
            f"Branded {self.files_branded} files",
            f"Copied {self.files_copied} files",
        ]
        if self.pr_url:
            parts.append(f"PR: {self.pr_url}")
        if self.errors:
            parts.append(f"Errors: {len(self.errors)}")
        return " | ".join(parts)


class Syncer:
    STATE_FILE = "nastech_sync_state.json"

    def __init__(self, config: NasTechSyncConfig):
        self.config = config
        self.brander = Brander(config)
        self.work_dir = Path(config.work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.upstream = GitRepo(
            config.upstream.local_path,
            user_name=config.git_user_name,
            user_email=config.git_user_email,
        )
        self.downstream = GitRepo(
            config.downstream.local_path,
            user_name=config.git_user_name,
            user_email=config.git_user_email,
        )

        self._state_path = self.work_dir / self.STATE_FILE

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Clone repos if they don't exist yet."""
        self._setup_upstream()
        self._setup_downstream()

    def run(self, dry_run: bool = False, force_full: bool = False) -> SyncResult:
        """
        Main sync entry point.
        - dry_run: apply branding locally, create branch, but do NOT push/open PR.
        - force_full: ignore state, re-sync ALL upstream commits.
        """
        result = SyncResult()
        logger.info("=" * 60)
        logger.info("NasTech Sync started at %s", result.started_at)

        try:
            self.setup()
            self._fetch_upstream()

            last_synced_sha = None if force_full else self._load_last_synced_sha()
            upstream_head = self.upstream.head_sha()

            if last_synced_sha and last_synced_sha == upstream_head:
                logger.info("Already up to date. Upstream: %s", upstream_head[:8])
                result.finish()
                return result

            # Get commits to process
            if last_synced_sha:
                commits = self.upstream.log_since(last_synced_sha, upstream_head)
                logger.info("Found %d new commit(s) since %s", len(commits), last_synced_sha[:8])
            else:
                commits = [{
                    "sha": upstream_head,
                    "subject": "Initial branded snapshot from upstream source",
                    "author_name": "NasTech-Agent",
                    "author_email": "agent@nastechai.com",
                    "date": datetime.now(timezone.utc).isoformat(),
                }]
                logger.info("First run: creating initial NasTech branded snapshot.")

            if not commits:
                logger.info("No new commits to sync.")
                result.finish()
                return result

            # Create a new sync branch from latest downstream main
            branch_name = self._make_branch_name(upstream_head)
            result.branch_name = branch_name
            self._prepare_sync_branch(branch_name)

            # Process commits onto the sync branch
            for i, commit in enumerate(commits, 1):
                logger.info(
                    "[%d/%d] Processing upstream commit %s: %s",
                    i, len(commits), commit["sha"][:8], commit["subject"],
                )
                self._sync_commit(
                    commit,
                    prev_sha=commits[i - 2]["sha"] if i > 1 else last_synced_sha,
                    result=result,
                )

            if not self.downstream.has_uncommitted_changes() and result.commits_synced == 0:
                logger.info("Nothing new to push.")
                result.finish()
                return result

            if dry_run:
                logger.info("[DRY RUN] Branch '%s' ready. Would push + open PR.", branch_name)
                self._save_last_synced_sha(upstream_head)
                result.finish()
                return result

            # Push branch (NOT main)
            pushed = self.downstream.push_branch(
                branch_name=branch_name,
                token=self.config.github_token,
            )
            if not pushed:
                result.errors.append("Failed to push sync branch.")
                result.finish()
                return result

            # Open Pull Request via GitHub API
            pr = self._open_pull_request(result, commits, upstream_head)
            if pr:
                result.pr_url = pr.get("html_url")
                logger.info("PR opened: %s", result.pr_url)
                self._save_last_synced_sha(upstream_head)
            else:
                result.errors.append("Could not open PR (no token or API error).")

        except Exception as exc:
            logger.exception("Unexpected error during sync: %s", exc)
            result.errors.append(str(exc))

        result.finish()
        logger.info("Result: %s", result)
        return result

    def status(self) -> dict:
        state = self._load_state()
        upstream_head = None
        downstream_head = None

        if self.upstream.exists():
            try:
                upstream_head = self.upstream.head_sha()
            except Exception:
                pass

        if self.downstream.exists():
            try:
                downstream_head = self.downstream.head_sha()
            except Exception:
                pass

        return {
            "last_synced_upstream_sha": state.get("last_synced_sha"),
            "last_sync_time": state.get("last_sync_time"),
            "last_pr_url": state.get("last_pr_url"),
            "upstream_head": upstream_head,
            "downstream_head": downstream_head,
            "upstream_url": self.config.upstream.url,
            "downstream_url": self.config.downstream.url,
            "upstream_cloned": self.upstream.exists(),
            "downstream_cloned": self.downstream.exists(),
        }

    # ------------------------------------------------------------------
    # Internal — setup
    # ------------------------------------------------------------------

    def _setup_upstream(self) -> None:
        if not self.upstream.exists():
            logger.info("Cloning upstream: %s", self.config.upstream.url)
            self.upstream.clone(
                self.config.upstream.url,
                branch=self.config.upstream.branch,
            )
        else:
            logger.info("Upstream already cloned at %s", self.upstream.path)

    def _setup_downstream(self) -> None:
        if not self.downstream.exists():
            logger.info("Cloning downstream: %s", self.config.downstream.url)
            self.downstream.clone(
                self.config.downstream.url,
                branch=self.config.downstream.branch,
                token=self.config.github_token,
            )
        else:
            logger.info("Downstream already cloned at %s", self.downstream.path)
            self.downstream._configure_identity()

    def _fetch_upstream(self) -> None:
        logger.info("Fetching latest from upstream...")
        self.upstream.fetch(branch=self.config.upstream.branch)
        self.upstream.reset_hard(f"origin/{self.config.upstream.branch}")

    # ------------------------------------------------------------------
    # Branch management
    # ------------------------------------------------------------------

    def _make_branch_name(self, upstream_sha: str) -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"nastech-sync/{date_str}-{upstream_sha[:8]}"

    def _prepare_sync_branch(self, branch_name: str) -> None:
        """Ensure downstream is on main, then create the sync branch."""
        # Reset downstream to its remote main first
        base = self.config.downstream.branch
        self.downstream.fetch(branch=base, token=self.config.github_token)
        try:
            self.downstream.checkout_branch(base)
        except Exception:
            pass
        self.downstream.reset_hard(f"origin/{base}")

        # Remove old branch of the same name if it exists locally
        if self.downstream.branch_exists_locally(branch_name):
            from .git_ops import _run
            _run(["git", "branch", "-D", branch_name], cwd=str(self.downstream.path))

        self.downstream.create_branch(branch_name, from_ref=f"origin/{base}")
        logger.info("Created sync branch: %s", branch_name)

    # ------------------------------------------------------------------
    # Per-commit sync
    # ------------------------------------------------------------------

    def _sync_commit(self, commit: dict, prev_sha: Optional[str],
                     result: SyncResult) -> None:
        sha = commit["sha"]

        if prev_sha:
            changed = self.upstream.changed_files(prev_sha, sha)
            self._apply_incremental(sha, changed, result)
        else:
            all_files = self.upstream.all_files(sha)
            self._apply_full_snapshot(sha, all_files, result)

        self.downstream.add_all()

        if self.downstream.has_staged_changes():
            branded_subject = self.brander.brand_text(commit["subject"])
            msg = (
                f"NasTech Updates from Source End: {branded_subject}\n\n"
                f"Source: NousResearch/hermes-agent@{commit['sha'][:12]}\n"
                f"Original author: {commit['author_name']}\n"
                f"NasTech-Agent auto-sync — branding applied"
            )
            self.downstream.commit(
                message=msg,
                author_name=self.config.git_user_name,
                author_email=self.config.git_user_email,
                author_date=commit.get("date"),
            )
            result.commits_synced += 1
        else:
            logger.debug("No staged changes for %s, skipping.", sha[:8])

    def _apply_incremental(self, sha: str, changed_files: list[tuple[str, str]],
                           result: SyncResult) -> None:
        for status, rel_path in changed_files:
            if self.brander.is_excluded(rel_path):
                continue

            branded_rel = self.brander.brand_path(rel_path)
            dst = Path(self.downstream.path) / branded_rel

            if status.startswith("D"):
                if dst.exists():
                    dst.unlink()
                old_dst = Path(self.downstream.path) / rel_path
                if old_dst != dst and old_dst.exists():
                    old_dst.unlink()
                continue

            raw = self.upstream.show_file_bytes_at(sha, rel_path)
            if raw is None:
                logger.warning("Could not read %s at %s", rel_path, sha[:8])
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            src_path = Path(rel_path)

            if self.brander.is_text_file(src_path):
                try:
                    text = raw.decode("utf-8", errors="replace")
                    branded = self.brander.brand_text(text, source_path=rel_path)
                    dst.write_text(branded, encoding="utf-8")
                    result.files_branded += 1
                except Exception as exc:
                    logger.warning("Brand failed %s: %s", rel_path, exc)
                    dst.write_bytes(raw)
                    result.files_copied += 1
            else:
                dst.write_bytes(raw)
                result.files_copied += 1

    def _apply_full_snapshot(self, sha: str, all_files: list[str],
                             result: SyncResult) -> None:
        ds_path = Path(self.downstream.path)
        for item in ds_path.iterdir():
            if item.name == ".git":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        for rel_path in all_files:
            if self.brander.is_excluded(rel_path):
                continue

            branded_rel = self.brander.brand_path(rel_path)
            dst = ds_path / branded_rel
            raw = self.upstream.show_file_bytes_at(sha, rel_path)
            if raw is None:
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)

            if self.brander.is_text_file(Path(rel_path)):
                try:
                    text = raw.decode("utf-8", errors="replace")
                    branded = self.brander.brand_text(text, source_path=rel_path)
                    dst.write_text(branded, encoding="utf-8")
                    result.files_branded += 1
                except Exception as exc:
                    logger.warning("Brand failed %s: %s", rel_path, exc)
                    dst.write_bytes(raw)
                    result.files_copied += 1
            else:
                dst.write_bytes(raw)
                result.files_copied += 1

    # ------------------------------------------------------------------
    # Pull Request
    # ------------------------------------------------------------------

    def _open_pull_request(
        self, result: SyncResult, commits: list[dict], upstream_head: str
    ) -> Optional[dict]:
        if not self.config.github_token:
            logger.warning("No GITHUB_TOKEN — skipping PR creation.")
            return None

        try:
            from .github_api import GitHubAPI
        except ImportError:
            logger.error("github_api module not available.")
            return None

        # Parse owner/repo from downstream URL
        owner, repo = _parse_owner_repo(self.config.downstream.url)
        if not owner or not repo:
            logger.error("Cannot parse owner/repo from %s", self.config.downstream.url)
            return None

        api = GitHubAPI(
            token=self.config.github_token,
            owner=owner,
            repo=repo,
        )

        base_branch = self.config.downstream.branch
        head_branch = result.branch_name

        # Check if PR already open for this branch
        if api.pr_already_open(head_branch, base_branch):
            existing = api.find_pr_for_branch(head_branch, base_branch)
            logger.info("PR already open: %s", existing.get("html_url"))
            return existing

        # Build PR title + body
        if len(commits) == 1:
            title = f"NasTech Updates from Source End: {self.brander.brand_text(commits[0]['subject'])}"
        else:
            title = f"NasTech Updates from Source End — {len(commits)} upstream commits"

        commit_lines = "\n".join(
            f"- `{c['sha'][:10]}` {self.brander.brand_text(c['subject'])}"
            for c in commits
        )
        body = (
            f"## NasTech Updates from Source End\n\n"
            f"Auto-synced {len(commits)} commit(s) from "
            f"[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)"
            f" @ `{upstream_head[:12]}`.\n\n"
            f"NasTech branding applied to all text content.\n\n"
            f"### Commits included\n\n"
            f"{commit_lines}\n\n"
            f"---\n"
            f"*Opened automatically by NasTech-Agent sync daemon.*"
        )

        pr = api.create_pull_request(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
            draft=getattr(self.config, "pr_draft", False),
        )
        return pr

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except Exception:
                pass
        return {}

    def _load_last_synced_sha(self) -> Optional[str]:
        return self._load_state().get("last_synced_sha")

    def _save_last_synced_sha(self, sha: str, pr_url: Optional[str] = None) -> None:
        state = self._load_state()
        state["last_synced_sha"] = sha
        state["last_sync_time"] = datetime.now(timezone.utc).isoformat()
        if pr_url:
            state["last_pr_url"] = pr_url
        self._state_path.write_text(json.dumps(state, indent=2))
        logger.debug("Saved state: %s", sha[:8])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_owner_repo(url: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (owner, repo) from a GitHub https URL."""
    url = url.rstrip("/").removesuffix(".git")
    if "github.com/" in url:
        parts = url.split("github.com/", 1)[1].split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None
