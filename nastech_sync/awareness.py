"""
NasTech Brain Awareness — connects the AI brain to full project context.

After install (`nastech-sync brain-connect`), this module:
  1. Scans the current project for all dependencies.
  2. Loads the sync state, branding rules, and AI provider status.
  3. Builds a rich system prompt extension for the brain.
  4. Saves a context snapshot to ~/.nastech-sync/workspace/brain_context.json
  5. Sends a "hello" message to the brain so it knows this installation exists.

This means the brain can answer:
  • "What packages are outdated in my project?"
  • "What branding rules are active?"
  • "When was the last sync?"
  • "Which AI provider is being used right now?"
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import NasTechSyncConfig

logger = logging.getLogger("nastech_sync.awareness")


AWARENESS_PROMPT = """
--- NasTech Awareness Context (auto-generated at {timestamp}) ---

## This Installation
- Tool: NasTech Sync (nasnyc)
- Version: {version}
- Host: {hostname}
- Work dir: {work_dir}
- Config: {config_path}

## Sync State
- Upstream:   {upstream_url}
- Downstream: {downstream_url}
- Last sync:  {last_sync_time}
- Last SHA:   {last_sha}

## AI Providers
{providers_status}

## Branding Rules ({rule_count} rules)
{rules_summary}

## Dependencies Scanned
{deps_summary}

## Active Alerts
{alerts}
--- End Awareness Context ---
"""


class NasTechAwareness:
    """
    Builds and maintains live context for the NasTech Brain.
    """

    CONTEXT_FILE = "brain_context.json"

    def __init__(self, config: NasTechSyncConfig):
        self.config = config
        self.work_dir = Path(config.work_dir)
        self.context_file = self.work_dir / self.CONTEXT_FILE

    def _get_sync_state(self) -> dict:
        """Load last sync state from disk."""
        state_file = self.work_dir / "nastech_sync_state.json"
        if state_file.exists():
            try:
                return json.loads(state_file.read_text())
            except Exception:
                pass
        return {}

    def _get_hostname(self) -> str:
        try:
            import socket
            return socket.gethostname()
        except Exception:
            return "unknown"

    def _get_version(self) -> str:
        try:
            from . import __version__
            return __version__
        except Exception:
            return "1.0.0"

    def _providers_status(self) -> str:
        lines = []
        has_openai = bool(self.config.openai_api_key)
        ollama_url = getattr(self.config, "ollama_url", "")
        has_ollama = bool(ollama_url and ollama_url != "http://localhost:11434")

        lines.append(f"- OpenAI (GPT-4o): {'✅ configured' if has_openai else '❌ not set'}")
        lines.append(f"- Ollama (cloud):  {'✅ ' + ollama_url if has_ollama else '❌ not set'}")
        return "\n".join(lines)

    def _rules_summary(self) -> str:
        rules = self.config.branding_rules
        lines = []
        for i, r in enumerate(rules, 1):
            lines.append(f"  {i:2}. '{r.find}' → '{r.replace}'")
        return "\n".join(lines[:10]) + (f"\n  ... and {len(rules)-10} more" if len(rules) > 10 else "")

    async def _deps_summary(self, scan_path: Optional[str] = None) -> str:
        """Run a quick dep scan on the given path."""
        path = scan_path or "."
        try:
            from .dependency_scanner import DependencyScanner
            scanner = DependencyScanner(root_path=path)
            report = await scanner.scan()
            if not report.packages:
                return "No dependency manifests found."
            outdated = report.outdated()
            ecos = list(report.by_ecosystem().keys())
            lines = [
                f"Scanned {len(report.packages)} packages across {len(ecos)} ecosystem(s): {', '.join(ecos)}",
                f"Outdated: {len(outdated)} | Up-to-date: {len(report.up_to_date())} | Errors: {len(report.errored())}",
            ]
            if outdated[:5]:
                lines.append("Top outdated:")
                for p in outdated[:5]:
                    lines.append(f"  - {p.name} ({p.ecosystem}): {p.current_version} → {p.latest_version}")
            return "\n".join(lines)
        except Exception as e:
            return f"Dependency scan failed: {e}"

    def _build_alerts(self, state: dict) -> str:
        alerts = []
        if not self.config.github_token:
            alerts.append("⚠️  GITHUB_TOKEN not set — PR creation will fail")
        if not self.config.openai_api_key and not getattr(self.config, "ollama_url", ""):
            alerts.append("⚠️  No AI provider configured — brain answers unavailable")
        if not self.config.telegram_bot_token:
            alerts.append("ℹ️  Telegram bot not configured (optional)")
        last = state.get("last_sync_time")
        if not last:
            alerts.append("ℹ️  No sync has run yet — run `nastech-sync sync` to start")
        return "\n".join(alerts) if alerts else "✅ No alerts"

    async def build_context(self, scan_path: Optional[str] = None) -> dict:
        """Build a full context dictionary."""
        state = self._get_sync_state()
        ts = datetime.now(timezone.utc).isoformat()

        context = {
            "timestamp": ts,
            "hostname": self._get_hostname(),
            "version": self._get_version(),
            "work_dir": str(self.work_dir),
            "upstream_url": self.config.upstream.url,
            "downstream_url": self.config.downstream.url,
            "last_sync_time": state.get("last_sync_time", "never"),
            "last_sha": state.get("last_synced_upstream_sha", "none"),
            "providers": {
                "openai": bool(self.config.openai_api_key),
                "ollama": bool(getattr(self.config, "ollama_url", "")),
            },
            "branding_rules": [
                {"find": r.find, "replace": r.replace}
                for r in self.config.branding_rules
            ],
            "deps_scanned": False,
            "deps_summary": "",
        }

        deps = await self._deps_summary(scan_path)
        context["deps_summary"] = deps
        context["deps_scanned"] = True

        return context

    def build_system_prompt_extension(self, context: dict) -> str:
        """Format context into a system prompt block for the brain."""
        return AWARENESS_PROMPT.format(
            timestamp=context.get("timestamp", ""),
            version=context.get("version", ""),
            hostname=context.get("hostname", ""),
            work_dir=context.get("work_dir", ""),
            config_path=str(Path(context.get("work_dir", "")) / "config.yaml"),
            upstream_url=context.get("upstream_url", ""),
            downstream_url=context.get("downstream_url", ""),
            last_sync_time=context.get("last_sync_time", "never"),
            last_sha=context.get("last_sha", "none"),
            providers_status=self._providers_status(),
            rule_count=len(self.config.branding_rules),
            rules_summary=self._rules_summary(),
            deps_summary=context.get("deps_summary", "not scanned"),
            alerts=self._build_alerts(self._get_sync_state()),
        )

    def save_context(self, context: dict) -> Path:
        """Persist context snapshot to disk."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.context_file.write_text(json.dumps(context, indent=2, default=str))
        logger.info("Saved brain context to %s", self.context_file)
        return self.context_file

    def load_context(self) -> Optional[dict]:
        """Load last saved context from disk."""
        if self.context_file.exists():
            try:
                return json.loads(self.context_file.read_text())
            except Exception:
                pass
        return None

    async def connect(self, scan_path: Optional[str] = None, verbose: bool = False) -> dict:
        """
        Full brain-connect flow:
          1. Build awareness context.
          2. Save it to disk.
          3. Inject into brain as system prompt extension.
          4. Send a hello message to confirm connectivity.
        Returns the context dict.
        """
        print("🧠  Building NasTech Brain awareness context...")
        context = await self.build_context(scan_path=scan_path)
        self.save_context(context)

        prompt_ext = self.build_system_prompt_extension(context)
        print("✅  Context built and saved to:", self.context_file)

        if verbose:
            print("\n── Brain Context Preview ──────────────────────────")
            print(prompt_ext[:1200])
            if len(prompt_ext) > 1200:
                print(f"... [{len(prompt_ext) - 1200} more chars]")
            print()

        # Try to talk to the brain
        try:
            from .brain import NasTechBrain, SYSTEM_PROMPT
            brain = NasTechBrain(self.config)
            # Inject awareness into brain's system
            brain_with_context = NasTechBrainWithAwareness(self.config, prompt_ext)
            hello = await brain_with_context.ask(
                "You have just been installed and connected. Confirm you are aware of this "
                "NasTech installation and summarise what you know about it in 2 sentences."
            )
            print("\n── Brain Response ─────────────────────────────────")
            print(hello)
            print()
        except Exception as e:
            print(f"\n⚠️  Brain connectivity test skipped: {e}")
            print("   (Set OPENAI_API_KEY or OLLAMA_URL to enable brain awareness)\n")

        return context


class NasTechBrainWithAwareness:
    """
    Wraps NasTechBrain and injects the awareness context into every conversation.
    Use this in the daemon so the brain always knows about the installation state.
    """

    def __init__(self, config: NasTechSyncConfig, awareness_prompt: str = ""):
        from .brain import NasTechBrain, SYSTEM_PROMPT
        self._brain = NasTechBrain(config)
        self._awareness = awareness_prompt
        self._base_system = SYSTEM_PROMPT

    def refresh_awareness(self, awareness_prompt: str):
        self._awareness = awareness_prompt

    def _full_system_prompt(self) -> str:
        if self._awareness:
            return self._base_system + "\n\n" + self._awareness
        return self._base_system

    async def ask(self, question: str, context: str = "") -> str:
        from .brain import SYSTEM_PROMPT
        # Temporarily override system prompt
        import nastech_sync.brain as brain_mod
        original = brain_mod.SYSTEM_PROMPT
        brain_mod.SYSTEM_PROMPT = self._full_system_prompt()
        try:
            return await self._brain.ask(question, context=context)
        finally:
            brain_mod.SYSTEM_PROMPT = original

    async def stream_ask(self, question: str, context: str = ""):
        import nastech_sync.brain as brain_mod
        original = brain_mod.SYSTEM_PROMPT
        brain_mod.SYSTEM_PROMPT = self._full_system_prompt()
        try:
            async for chunk in self._brain.stream_ask(question, context=context):
                yield chunk
        finally:
            brain_mod.SYSTEM_PROMPT = original

    def provider_status(self) -> dict:
        return self._brain.provider_status()

    def clear_history(self):
        self._brain.clear_history()
