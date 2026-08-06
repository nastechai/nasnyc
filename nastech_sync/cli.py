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
import asyncio
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


def cmd_deps(args, config) -> int:
    """Scan all dependency manifests for outdated packages."""
    from .dependency_scanner import DependencyScanner

    scan_path = args.scan_path or "."
    fmt = getattr(args, "format", "table")

    print(f"\n🔍  Scanning dependencies in: {scan_path}")

    async def _run():
        scanner = DependencyScanner(root_path=scan_path)
        return await scanner.scan()

    report = asyncio.run(_run())

    if fmt == "json":
        import json
        out = {
            "root": report.root_path,
            "total": len(report.packages),
            "outdated": [
                {
                    "name": p.name,
                    "ecosystem": p.ecosystem,
                    "current": p.current_version,
                    "latest": p.latest_version,
                    "manifest": p.manifest_file,
                    "url": p.latest_url,
                }
                for p in report.outdated()
            ],
            "up_to_date": len(report.up_to_date()),
            "errors": report.errors,
        }
        print(json.dumps(out, indent=2))
    elif fmt == "markdown":
        print(report.markdown_report())
    else:
        # Table view
        by_eco = report.by_ecosystem()
        for eco, pkgs in sorted(by_eco.items()):
            print(f"\n── {eco.upper()} ({'  '.join(p.manifest_file.split('/')[-1:])}) ──")
            for p in sorted(pkgs, key=lambda x: (not x.is_outdated, x.name)):
                print(f"  {p}")

    print(f"\n{report.summary()}")
    if report.outdated():
        print("  Run `nastech-sync update` to apply all updates.")
    return 0


def cmd_update(args, config) -> int:
    """Apply dependency updates across all ecosystems."""
    from .dependency_scanner import DependencyScanner
    from .dependency_updater import DependencyUpdater

    scan_path = args.scan_path or "."
    dry_run = getattr(args, "dry_run", False)
    ecosystems = getattr(args, "ecosystems", None)
    eco_list = [e.strip() for e in ecosystems.split(",")] if ecosystems else None

    print(f"\n📦  Scanning dependencies in: {scan_path}")

    async def _scan():
        return await DependencyScanner(root_path=scan_path).scan()

    report = asyncio.run(_scan())
    outdated = report.outdated()

    if not outdated:
        print("✅  All packages are up to date!")
        return 0

    print(f"  Found {len(outdated)} outdated packages.")
    if dry_run:
        print("  (Dry run — no files will be changed)\n")

    updater = DependencyUpdater(root_path=scan_path)
    changes = updater.apply_updates(report, dry_run=dry_run, ecosystems=eco_list)

    if not changes:
        print("  No manifest files could be updated automatically.")
        return 0

    for fpath, file_changes in changes.items():
        print(f"\n  {fpath}:")
        for c in file_changes:
            prefix = "  would update" if dry_run else "  ✅ updated"
            print(f"    {prefix}: {c}")

    if not dry_run:
        # Run post-update commands (npm install, go mod tidy, etc.)
        updated_ecosystems = {p.ecosystem for p in outdated if any(p.name in c for c in sum(changes.values(), []))}
        if updated_ecosystems:
            print(f"\n  Running post-update commands for: {', '.join(updated_ecosystems)}")
            results = updater.run_post_update(updated_ecosystems)
            for cmd, ok, output in results:
                icon = "✅" if ok else "⚠️ "
                print(f"  {icon} {cmd}")
                if not ok and output:
                    print(f"     {output[:200]}")

        print(f"\n✅  Updated {sum(len(v) for v in changes.values())} packages across {len(changes)} file(s).")
        print("  Commit the changes and push to create a PR.")
    return 0


def cmd_brain_connect(args, config) -> int:
    """Connect this installation to the NasTech Brain — load full project context."""
    from .awareness import NasTechAwareness

    scan_path = getattr(args, "scan_path", None) or "."
    verbose = getattr(args, "verbose_output", False)

    print("\n🧠  Connecting to NasTech Brain...")
    print(f"   Scanning: {scan_path}")
    print(f"   Brain providers: OpenAI={bool(config.openai_api_key)}, Ollama={bool(config.ollama_url)}\n")

    awareness = NasTechAwareness(config)

    async def _run():
        return await awareness.connect(scan_path=scan_path, verbose=verbose)

    context = asyncio.run(_run())

    print(f"\n✅  Brain connected.")
    print(f"   Context saved to: {awareness.context_file}")
    print(f"   Packages scanned: see context file for full dependency report")
    print(f"   Branding rules  : {len(config.branding_rules)} rules loaded")
    print(f"\n   The brain now knows about this NasTech installation.")
    print(f"   Run `python main.py` to start the 24/7 daemon with full brain awareness.\n")
    return 0


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

    # deps — scan all dependency manifests
    p_deps = sub.add_parser("deps", help="Scan all dependency manifests for outdated packages (npm, pip, cargo, go, …)")
    p_deps.add_argument("--scan-path", default=".", help="Directory to scan (default: current dir)")
    p_deps.add_argument("--format", choices=["table", "json", "markdown"], default="table",
                        help="Output format")

    # update — apply dependency updates
    p_update = sub.add_parser("update", help="Apply dependency updates across all ecosystems")
    p_update.add_argument("--scan-path", default=".", help="Directory to scan and update")
    p_update.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    p_update.add_argument("--ecosystems", default=None,
                          help="Comma-separated list of ecosystems to update (e.g. pip,npm)")

    # brain-connect — connect to NasTech Brain with full awareness
    p_brain = sub.add_parser("brain-connect",
                              help="Connect this install to the NasTech Brain — scans deps + loads project context")
    p_brain.add_argument("--scan-path", default=".", help="Project path to scan for dependencies")
    p_brain.add_argument("--verbose-output", action="store_true", help="Show full brain context preview")

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
        "deps": cmd_deps,
        "update": cmd_update,
        "brain-connect": cmd_brain_connect,
    }
    return dispatch[args.command](args, config)


if __name__ == "__main__":
    sys.exit(main())
