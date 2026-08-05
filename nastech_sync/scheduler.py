"""
NasTech Scheduler — 24/7 orchestration daemon.

Runs:
  • Periodic git sync (every N minutes)
  • FastAPI web dashboard
  • Telegram bot

All three run concurrently in a single asyncio event loop.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import uvicorn

from .config import NasTechSyncConfig, load_config
from .syncer import Syncer, SyncResult
from .brander import Brander
from .brain import NasTechBrain

logger = logging.getLogger("nastech_sync.scheduler")


class NasTechScheduler:
    def __init__(self, config: NasTechSyncConfig, interval_minutes: int = 30):
        self.config = config
        self.interval_minutes = interval_minutes

        self.syncer = Syncer(config)
        self.brander = Brander(config)
        self.brain = NasTechBrain(config)

        self._start_time = time.time()
        self._sync_history: list[dict] = []
        self._next_sync_at: float = time.time()
        self._running = False
        self._bot = None  # set after construction if Telegram is enabled

    # ------------------------------------------------------------------
    # Public helpers (used by webapp & telegram)
    # ------------------------------------------------------------------

    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    def next_sync_in_seconds(self) -> float:
        return max(0.0, self._next_sync_at - time.time())

    def get_sync_history(self) -> list[dict]:
        return list(self._sync_history)

    def record_sync(self, result: SyncResult) -> None:
        self._sync_history.append({
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "commits_synced": result.commits_synced,
            "files_branded": result.files_branded,
            "files_copied": result.files_copied,
            "errors": result.errors,
        })
        # Keep last 100
        self._sync_history = self._sync_history[-100:]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_forever(
        self,
        web_host: str = "0.0.0.0",
        web_port: int = 8080,
        enable_telegram: bool = True,
        enable_web: bool = True,
    ) -> None:
        self._running = True
        logger.info("NasTech Sync daemon starting...")
        logger.info("  Upstream  : %s", self.config.upstream.url)
        logger.info("  Downstream: %s", self.config.downstream.url)
        logger.info("  Interval  : %d min", self.interval_minutes)

        tasks = [asyncio.create_task(self._sync_loop(), name="sync-loop")]

        if enable_web:
            tasks.append(asyncio.create_task(
                self._run_web(web_host, web_port), name="web"
            ))

        if enable_telegram:
            tg_token = (
                os.environ.get("TELEGRAM_BOT_TOKEN")
                or getattr(self.config, "telegram_bot_token", None)
            )
            tg_chat_ids_raw = (
                os.environ.get("TELEGRAM_CHAT_IDS", "")
                or getattr(self.config, "telegram_chat_ids", "")
            )
            chat_ids = [
                int(x.strip())
                for x in str(tg_chat_ids_raw).split(",")
                if x.strip().lstrip("-").isdigit()
            ]

            if tg_token:
                tasks.append(asyncio.create_task(
                    self._run_telegram(tg_token, chat_ids), name="telegram"
                ))
            else:
                logger.warning(
                    "TELEGRAM_BOT_TOKEN not set — Telegram bot disabled. "
                    "Set it in env or config.yaml."
                )

        logger.info("NasTech Sync is live. Press Ctrl+C to stop.")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.info("NasTech Sync daemon stopped.")

    # ------------------------------------------------------------------
    # Sync loop
    # ------------------------------------------------------------------

    async def _sync_loop(self) -> None:
        # Initial setup
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.syncer.setup)

        # Run first sync immediately
        await self._do_sync()

        while self._running:
            self._next_sync_at = time.time() + self.interval_minutes * 60
            # Sleep in 10-second ticks so we can be cancelled cleanly
            while time.time() < self._next_sync_at and self._running:
                await asyncio.sleep(10)
            if self._running:
                await self._do_sync()

    async def _do_sync(self) -> SyncResult:
        logger.info("Starting scheduled sync...")
        loop = asyncio.get_event_loop()
        result: SyncResult = await loop.run_in_executor(
            None, lambda: self.syncer.run()
        )
        self.record_sync(result)

        if self._bot and result.commits_synced > 0:
            self._bot.notify_sync_complete(result)

        logger.info("Sync done: %s", result)
        return result

    # ------------------------------------------------------------------
    # Web server
    # ------------------------------------------------------------------

    async def _run_web(self, host: str, port: int) -> None:
        from .webapp import create_app
        app = create_app(self)
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        logger.info("Web dashboard: http://%s:%d", host, port)
        await server.serve()

    # ------------------------------------------------------------------
    # Telegram bot
    # ------------------------------------------------------------------

    async def _run_telegram(self, token: str, chat_ids: list[int]) -> None:
        from .telegram_bot import NasTechBot
        self._bot = NasTechBot(token=token, scheduler=self, allowed_chat_ids=chat_ids)
        try:
            await self._bot.start()
            # Keep alive
            while self._running:
                await asyncio.sleep(5)
        finally:
            if self._bot:
                await self._bot.stop()
