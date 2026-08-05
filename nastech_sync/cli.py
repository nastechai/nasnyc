"""
NasTech Sync CLI — entry point for all commands.

Usage examples:
  python -m nastech_sync sync           # pull & push latest
  python -m nastech_sync sync --dry-run # preview without pushing
  python -m nastech_sync sync --full    # re-brand everything from scratch
  python -m nastech_sync status         # show sync state
  python -m nastech_sync setup          # clone repos only
  python -m nastech_sync preview "some hermes text"  # test branding rules
"""

import sys
import logging
import argparse
from pathlib import Path

from .config import load_config
from .syncer import Syncer
from .brander import Brander


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False, log_file: str | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_sync(args, config) -> int:
    syncer = Syncer(config)
    result = syncer.run(dry_run=args.dry_run, force_full=args.full)

    if result.errors:
        print("\n⚠  Errors during sync:")
        for err in result.errors:
            print(f"   • {err}")
        return 1

    print(f"\n✅  {result}")
    return 0


def cmd_status(args, config) -> int:
    syncer = Syncer(config)
    status = syncer.status()

    print("\n── NasTech Sync Status ─────────────────────────────")
    print(f"  Upstream URL   : {status['upstream_url']}")
    print(f"  Downstream URL : {status['downstream_url']}")
    print(f"  Upstream cloned: {'yes' if status['upstream_cloned'] else 'no'}")
    print(f"  Downstream cloned: {'yes' if status['downstream_cloned'] else 'no'}")

    lss = status.get("last_synced_upstream_sha")
    print(f"  Last synced SHA: {lss[:12] if lss else 'never'}")
    print(f"  Last sync time : {status.get('last_sync_time') or 'never'}")

    uh = status.get("upstream_head")
    dh = status.get("downstream_head")
    print(f"  Upstream HEAD  : {uh[:12] if uh else 'unknown'}")
    print(f"  Downstream HEAD: {dh[:12] if dh else 'unknown'}")

    if lss and uh and lss == uh:
        print("\n  ✅  Up to date!")
    elif lss and uh:
        print("\n  🔄  Upstream has new commits. Run `sync` to update.")
    else:
        print("\n  ⚙️   Not set up yet. Run `setup` first.")
    print()
    return 0


def cmd_setup(args, config) -> int:
    syncer = Syncer(config)
    print("Setting up repos...")
    syncer.setup()
    print("✅  Setup complete.")
    return 0


def cmd_preview(args, config) -> int:
    """Preview branding rules on a text input."""
    brander = Brander(config)
    text = " ".join(args.text)
    result = brander.brand_text(text)
    changes = brander.describe_changes(text, result)

    print(f"\nInput   : {text}")
    print(f"Output  : {result}")
    if changes:
        print("Changes :")
        for c in changes:
            print(c)
    else:
        print("No branding rules matched.")
    return 0


def cmd_rules(args, config) -> int:
    """List all active branding rules."""
    print("\n── Active Branding Rules ───────────────────────────")
    for i, rule in enumerate(config.branding_rules, 1):
        cs = "" if rule.case_sensitive else " (case-insensitive)"
        print(f"  {i:>2}. '{rule.find}' → '{rule.replace}'{cs}")
    print()
    return 0


def cmd_login(args, config) -> int:
    """
    Authenticate with OpenAI (Codex) and/or GitHub interactively.
    Saves credentials to a local .env file in the work directory.
    """
    import getpass
    from pathlib import Path

    work_dir = Path(config.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    env_file = work_dir / ".env"

    existing: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    print("\n── NasTech Sync Login ──────────────────────────────")
    print("Credentials are stored in:", env_file)
    print("Press Enter to keep existing value (shown as [set] or [not set]).\n")

    updated = dict(existing)

    # GitHub Token
    gh_hint = "[set]" if existing.get("GITHUB_TOKEN") else "[not set]"
    print(f"GitHub Personal Access Token {gh_hint}")
    print("  Scopes needed: repo (full access to nastechai/NasTech-Agent)")
    print("  Create at: https://github.com/settings/tokens/new")
    gh = getpass.getpass("  GITHUB_TOKEN: ").strip()
    if gh:
        updated["GITHUB_TOKEN"] = gh
        print("  ✅ GitHub token saved.")
    elif existing.get("GITHUB_TOKEN"):
        print("  ↩  Keeping existing token.")

    print()

    # OpenAI / Codex
    oai_hint = "[set]" if existing.get("OPENAI_API_KEY") else "[not set]"
    print(f"OpenAI API Key (for Codex / GPT-4o brain) {oai_hint}")
    print("  Create at: https://platform.openai.com/api-keys")
    oai = getpass.getpass("  OPENAI_API_KEY: ").strip()
    if oai:
        updated["OPENAI_API_KEY"] = oai
        print("  ✅ OpenAI key saved.")
    elif existing.get("OPENAI_API_KEY"):
        print("  ↩  Keeping existing key.")

    print()

    # Ollama cloud URL
    ollama_hint = existing.get("OLLAMA_URL", "http://localhost:11434")
    print(f"Ollama Cloud URL [{ollama_hint}]")
    print("  For cloud Ollama: https://your-ollama.fly.dev or similar")
    print("  Leave blank to keep current.")
    ollama = input("  OLLAMA_URL: ").strip()
    if ollama:
        updated["OLLAMA_URL"] = ollama
        print("  ✅ Ollama URL saved.")

    print()

    # Telegram
    tg_hint = "[set]" if existing.get("TELEGRAM_BOT_TOKEN") else "[not set]"
    print(f"Telegram Bot Token {tg_hint}")
    print("  Get from @BotFather on Telegram.")
    tg = getpass.getpass("  TELEGRAM_BOT_TOKEN: ").strip()
    if tg:
        updated["TELEGRAM_BOT_TOKEN"] = tg
        print("  ✅ Telegram token saved.")
    elif existing.get("TELEGRAM_BOT_TOKEN"):
        print("  ↩  Keeping existing token.")

    tg_ids_hint = existing.get("TELEGRAM_CHAT_IDS", "")
    print(f"\nTelegram Chat IDs (comma-separated) [{tg_ids_hint or 'not set'}]")
    print("  Get your ID by messaging @userinfobot on Telegram.")
    tg_ids = input("  TELEGRAM_CHAT_IDS: ").strip()
    if tg_ids:
        updated["TELEGRAM_CHAT_IDS"] = tg_ids
        print("  ✅ Chat IDs saved.")

    # Write .env
    lines = ["# NasTech Sync credentials — DO NOT COMMIT THIS FILE"]
    for k, v in updated.items():
        lines.append(f"{k}={v}")
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)  # restrict read permissions

    print(f"\n✅  Credentials saved to {env_file}")
    print("   Load them with: export $(cat ~/.nastech-sync/workspace/.env | xargs)\n")
    return 0


def cmd_test(args, config) -> int:
    """
    Local test — clone repos, apply branding, create a sync branch,
    but do NOT push or open a PR. Verifies the full pipeline works.
    """
    from .syncer import Syncer

    print("\n── NasTech Sync — Local Test (no push, no PR) ─────")
    print(f"Upstream  : {config.upstream.url}")
    print(f"Downstream: {config.downstream.url}")
    print(f"Work dir  : {config.work_dir}\n")

    syncer = Syncer(config)
    result = syncer.run(dry_run=True)

    print(f"\n{'✅' if not result.errors else '⚠️ '} Result: {result}")
    if result.branch_name:
        print(f"   Branch ready : {result.branch_name}")
        print(f"   Commits ready: {result.commits_synced}")
        print(f"   Files branded: {result.files_branded}")
        print(f"   Files copied : {result.files_copied}")
    if result.errors:
        print("\nErrors:")
        for e in result.errors:
            print(f"  • {e}")
    return 1 if result.errors else 0


def cmd_prs(args, config) -> int:
    """List open PRs on the downstream repo."""
    if not config.github_token:
        print("❌  GITHUB_TOKEN not set. Run `login` first.")
        return 1
    from .github_api import GitHubAPI
    from .syncer import _parse_owner_repo
    owner, repo = _parse_owner_repo(config.downstream.url)
    if not owner:
        print("❌  Cannot parse owner/repo from downstream URL.")
        return 1
    api = GitHubAPI(config.github_token, owner, repo)
    prs = api.list_pull_requests(state="open")
    if not prs:
        print("No open PRs.")
        return 0
    print(f"\n── Open PRs on {owner}/{repo} ──────────────────────")
    for pr in prs:
        print(f"  #{pr['number']} {pr['title']}")
        print(f"     {pr['html_url']}")
        print(f"     {pr['head']['ref']} → {pr['base']['ref']}")
    print()
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="nastech-sync",
        description="NasTech Sync — keep NasTech-Agent in sync with hermes-agent",
    )
    parser.add_argument("-c", "--config", help="Path to config.yaml", default=None)
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    p_sync = sub.add_parser("sync", help="Pull upstream + open PR (never pushes to main)")
    p_sync.add_argument("--dry-run", action="store_true",
                        help="Apply branding locally, create branch, but do NOT push or open PR")
    p_sync.add_argument("--full", action="store_true",
                        help="Re-brand everything from scratch (ignores saved state)")

    # test — local dry-run with output
    sub.add_parser("test", help="Full local test: clone + brand + branch (no push, no PR)")

    # status
    sub.add_parser("status", help="Show current sync state")

    # setup
    sub.add_parser("setup", help="Clone repos without syncing")

    # preview
    p_preview = sub.add_parser("preview", help="Preview branding on a text snippet")
    p_preview.add_argument("text", nargs="+", help="Text to test branding rules on")

    # rules
    sub.add_parser("rules", help="List all active branding rules")

    # login
    sub.add_parser("login", help="Authenticate with GitHub, OpenAI (Codex), Telegram interactively")

    # prs
    sub.add_parser("prs", help="List open PRs on the downstream repo")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    setup_logging(verbose=args.verbose, log_file=config.log_file)

    dispatch = {
        "sync": cmd_sync,
        "test": cmd_test,
        "status": cmd_status,
        "setup": cmd_setup,
        "preview": cmd_preview,
        "rules": cmd_rules,
        "login": cmd_login,
        "prs": cmd_prs,
    }
    return dispatch[args.command](args, config)


if __name__ == "__main__":
    sys.exit(main())
