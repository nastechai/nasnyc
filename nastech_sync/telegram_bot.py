"""
NasTech Telegram Bot — 24/7 command & notification interface.

Commands:
  /start    — Welcome + quick help
  /status   — Current sync state
  /sync     — Trigger a manual sync
  /dryrun   — Sync without pushing
  /rules    — List branding rules
  /ask <q>  — Ask the NasTech Brain
  /clear    — Clear AI conversation history
  /brain    — Show AI provider status
  /help     — Full command list
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .scheduler import NasTechScheduler

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

logger = logging.getLogger("nastech_sync.telegram")

NASTECH_BANNER = (
    "🤖 *NasTech\\-Agent Bot*\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "_Keeping NasTech in sync with the frontier — 24/7_\n\n"
)


def _escape(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


class NasTechBot:
    def __init__(self, token: str, scheduler: "NasTechScheduler",
                 allowed_chat_ids: Optional[list[int]] = None):
        self.token = token
        self.scheduler = scheduler
        self.allowed_chat_ids = allowed_chat_ids or []
        self._app: Optional[Application] = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self):
        self._app = (
            Application.builder()
            .token(self.token)
            .build()
        )
        self._register_handlers()
        await self._set_commands()
        logger.info("Telegram bot starting (polling)...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot is live.")

    async def stop(self):
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    def _register_handlers(self):
        app = self._app
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("sync", self.cmd_sync))
        app.add_handler(CommandHandler("dryrun", self.cmd_dryrun))
        app.add_handler(CommandHandler("rules", self.cmd_rules))
        app.add_handler(CommandHandler("ask", self.cmd_ask))
        app.add_handler(CommandHandler("clear", self.cmd_clear))
        app.add_handler(CommandHandler("brain", self.cmd_brain))
        # Free-form messages treated as brain questions
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    async def _set_commands(self):
        commands = [
            BotCommand("start", "Welcome and quick start"),
            BotCommand("status", "Current sync status"),
            BotCommand("sync", "Trigger a manual sync now"),
            BotCommand("dryrun", "Sync without pushing (preview)"),
            BotCommand("rules", "Show active branding rules"),
            BotCommand("ask", "Ask the NasTech Brain anything"),
            BotCommand("clear", "Clear AI conversation history"),
            BotCommand("brain", "Show AI provider status"),
            BotCommand("help", "Full command list"),
        ]
        await self._app.bot.set_my_commands(commands)

    # ------------------------------------------------------------------
    # Auth guard
    # ------------------------------------------------------------------

    def _is_allowed(self, update: Update) -> bool:
        # Fail-closed: if no allowlist is configured, deny everything.
        # This prevents unauthorised access to /sync, /dryrun, and AI
        # queries when the bot token is accidentally leaked or shared.
        if not self.allowed_chat_ids:
            return False
        chat_id = update.effective_chat.id
        return chat_id in self.allowed_chat_ids

    async def _deny(self, update: Update):
        await update.message.reply_text("⛔ Unauthorised chat.")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        text = (
            f"*NasTech\\-Agent Bot* 🤖\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"I keep `nastechai/NasTech\\-Agent` in sync with `NousResearch/hermes\\-agent` "
            f"and brand every commit as a NasTech update \\— 24/7\\.\n\n"
            f"*Quick commands:*\n"
            f"/status — sync state\n"
            f"/sync — pull \\& push now\n"
            f"/ask \\<question\\> — ask the AI brain\n"
            f"/help — all commands\n\n"
            f"Or just type any question and I'll answer\\."
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        text = (
            "*NasTech\\-Agent Bot — Commands*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "/status — Show sync state \\& last commit\n"
            "/sync — Trigger a manual sync now\n"
            "/dryrun — Sync without pushing\n"
            "/rules — List branding rules\n"
            "/ask \\<question\\> — Ask the NasTech Brain\n"
            "/clear — Clear AI conversation history\n"
            "/brain — Show AI provider status\n"
            "/help — This message\n\n"
            "_Or just type any question and I'll route it to the brain\\._"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        await update.message.reply_text("⏳ Checking status...")
        try:
            s = self.scheduler.syncer.status()
            lss = s.get("last_synced_upstream_sha") or "never"
            if lss != "never":
                lss = lss[:12]
            lst = s.get("last_sync_time") or "never"
            uh = (s.get("upstream_head") or "unknown")[:12]
            dh = (s.get("downstream_head") or "unknown")[:12]
            up_to_date = (
                s.get("last_synced_upstream_sha")
                and s.get("upstream_head")
                and s["last_synced_upstream_sha"] == s["upstream_head"]
            )
            icon = "✅" if up_to_date else "🔄"
            up_cloned = "✅" if s.get("upstream_cloned") else "❌"
            dn_cloned = "✅" if s.get("downstream_cloned") else "❌"
            footer = "✅ Up to date\\!" if up_to_date else "🔄 New upstream commits available\\. Use /sync to update\\."
            text = (
                f"*NasTech Sync Status* {icon}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Last synced SHA: `{_escape(lss)}`\n"
                f"Last sync time: {_escape(str(lst))}\n"
                f"Upstream HEAD: `{_escape(uh)}`\n"
                f"Downstream HEAD: `{_escape(dh)}`\n"
                f"Upstream cloned: {up_cloned}\n"
                f"Downstream cloned: {dn_cloned}\n\n"
                f"{footer}"
            )
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as exc:
            await update.message.reply_text(f"❌ Error: {exc}")

    async def cmd_sync(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        await update.message.reply_text(
            "🔄 Starting sync\\.\\.\\. I'll message you when done\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        asyncio.create_task(self._run_sync_and_notify(update, dry_run=False))

    async def cmd_dryrun(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        await update.message.reply_text(
            "🧪 Running dry\\-run sync \\(no push\\)\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        asyncio.create_task(self._run_sync_and_notify(update, dry_run=True))

    async def cmd_rules(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        rules = self.scheduler.config.branding_rules
        lines = [f"*NasTech Branding Rules* \\({len(rules)}\\)\n━━━━━━━━━━━━━━━━━━━━━━━━"]
        for r in rules[:20]:  # Telegram msg limit
            lines.append(f"`{_escape(r.find)}` → `{_escape(r.replace)}`")
        if len(rules) > 20:
            lines.append(f"_\\.\\.\\. and {len(rules) - 20} more_")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_ask(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        question = " ".join(ctx.args) if ctx.args else ""
        if not question:
            await update.message.reply_text(
                "Usage: /ask \\<your question\\>", parse_mode=ParseMode.MARKDOWN_V2
            )
            return
        await self._answer_question(update, question)

    async def cmd_clear(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        self.scheduler.brain.clear_history()
        await update.message.reply_text("🧹 Conversation history cleared\\.", parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_brain(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        statuses = self.scheduler.brain.provider_status()
        lines = ["*AI Brain Status*\n━━━━━━━━━━━━━━━"]
        for name, ok in statuses.items():
            icon = "✅" if ok else "❌"
            lines.append(f"{icon} {_escape(name)}")
        if not any(statuses.values()):
            lines.append("\n⚠️ _No AI provider available\\. Set OPENAI\\_API\\_KEY or start Ollama\\._")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        question = update.message.text or ""
        if question.strip():
            await self._answer_question(update, question)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _answer_question(self, update: Update, question: str):
        typing_msg = await update.message.reply_text("🧠 Thinking...")
        try:
            answer = await self.scheduler.brain.ask(question)
            await typing_msg.delete()
            # Send in chunks to stay under the 4096 char Telegram limit
            chunk_size = 4000
            for i in range(0, max(1, len(answer)), chunk_size):
                chunk = answer[i:i + chunk_size]
                if not chunk.strip():
                    continue
                # Send as plain text — AI responses can contain arbitrary formatting
                # that breaks MarkdownV2 parsing unexpectedly.
                try:
                    await update.message.reply_text(chunk)
                except Exception:
                    # Last resort: strip to ASCII-safe subset
                    await update.message.reply_text(chunk.encode("ascii", errors="replace").decode())
        except Exception as exc:
            try:
                await typing_msg.edit_text(f"❌ Brain error: {exc}")
            except Exception:
                await update.message.reply_text(f"❌ Brain error: {exc}")

    async def _run_sync_and_notify(self, update: Update, dry_run: bool = False):
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.scheduler.syncer.run(dry_run=dry_run)
            )
            mode = "DRY RUN" if dry_run else "LIVE"
            icon = "✅" if not result.errors else "⚠️"
            lines = [
                f"{icon} NasTech Sync Complete [{mode}]",
                "━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Commits synced: {result.commits_synced}",
                f"Files branded:  {result.files_branded}",
                f"Files copied:   {result.files_copied}",
            ]
            if result.branch_name:
                lines.append(f"Branch: {result.branch_name}")
            if result.pr_url:
                lines.append(f"PR: {result.pr_url}")
            if result.errors:
                lines.append("\n⚠️ Errors:")
                lines.extend(f"• {e}" for e in result.errors)
            await update.message.reply_text("\n".join(lines))
        except Exception as exc:
            await update.message.reply_text(f"❌ Sync failed: {exc}")

    # ------------------------------------------------------------------
    # Notification API (called by scheduler)
    # ------------------------------------------------------------------

    async def notify_all(self, text: str):
        """Send a notification to all allowed chat IDs."""
        if not self._app or not self.allowed_chat_ids:
            return
        for chat_id in self.allowed_chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                logger.warning("Could not notify chat %s: %s", chat_id, exc)

    def notify_sync_complete(self, result) -> None:
        """Fire-and-forget notification from sync thread."""
        if not self._app or not self.allowed_chat_ids:
            return
        icon = "✅" if not result.errors else "⚠️"
        text = (
            f"{icon} NasTech Sync complete\n"
            f"Commits: {result.commits_synced} | "
            f"Branded: {result.files_branded} files"
        )
        asyncio.create_task(self.notify_all(text))
