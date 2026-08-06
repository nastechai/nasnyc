"""
Tests for Telegram bot authorization guard.

Ensures that /sync, /dryrun, and AI queries are denied when:
  - No allowlist is configured (empty allowed_chat_ids)
  - The requesting chat ID is not in the allowlist
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_update(chat_id: int) -> MagicMock:
    """Build a minimal fake telegram Update with the given chat_id."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.text = "hello"
    return update


def _make_bot(allowed_chat_ids: list) -> "NasTechBot":  # noqa: F821
    """Construct a NasTechBot with a mocked scheduler."""
    from nastech_sync.telegram_bot import NasTechBot

    scheduler = MagicMock()
    scheduler.brain = MagicMock()
    scheduler.config = MagicMock()
    scheduler.config.branding_rules = []
    scheduler.syncer = MagicMock()

    bot = NasTechBot(
        token="fake:token",
        scheduler=scheduler,
        allowed_chat_ids=allowed_chat_ids,
    )
    return bot


# ---------------------------------------------------------------------------
# _is_allowed
# ---------------------------------------------------------------------------

class TestIsAllowed:
    def test_empty_allowlist_denies_all(self):
        """No allowlist → every chat must be denied (fail-closed)."""
        bot = _make_bot([])
        update = _make_update(chat_id=12345)
        assert bot._is_allowed(update) is False

    def test_chat_in_allowlist_is_permitted(self):
        bot = _make_bot([12345, 67890])
        assert bot._is_allowed(_make_update(12345)) is True

    def test_chat_not_in_allowlist_is_denied(self):
        bot = _make_bot([12345])
        assert bot._is_allowed(_make_update(99999)) is False

    def test_multiple_ids_only_matching_permitted(self):
        bot = _make_bot([111, 222, 333])
        assert bot._is_allowed(_make_update(222)) is True
        assert bot._is_allowed(_make_update(444)) is False


# ---------------------------------------------------------------------------
# /sync, /dryrun, free-form message — must be blocked without allowlist
# ---------------------------------------------------------------------------

class TestCommandsRequireAllowlist:
    """Commands that trigger repository writes must fail without an allowlist."""

    @pytest.mark.asyncio
    async def test_sync_denied_with_no_allowlist(self):
        bot = _make_bot([])
        update = _make_update(chat_id=12345)
        ctx = MagicMock()

        await bot.cmd_sync(update, ctx)

        # Must reply with the denial message, never trigger a sync
        update.message.reply_text.assert_awaited()
        first_call_args = update.message.reply_text.call_args_list[0][0]
        assert "Unauthorised" in first_call_args[0] or "⛔" in first_call_args[0]

    @pytest.mark.asyncio
    async def test_dryrun_denied_with_no_allowlist(self):
        bot = _make_bot([])
        update = _make_update(chat_id=12345)
        ctx = MagicMock()

        await bot.cmd_dryrun(update, ctx)

        update.message.reply_text.assert_awaited()
        first_call_args = update.message.reply_text.call_args_list[0][0]
        assert "Unauthorised" in first_call_args[0] or "⛔" in first_call_args[0]

    @pytest.mark.asyncio
    async def test_free_form_message_denied_with_no_allowlist(self):
        bot = _make_bot([])
        update = _make_update(chat_id=12345)
        ctx = MagicMock()

        await bot.handle_message(update, ctx)

        # Brain must NOT be called
        bot.scheduler.brain.ask.assert_not_called()
        update.message.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_ask_command_denied_with_no_allowlist(self):
        bot = _make_bot([])
        update = _make_update(chat_id=12345)
        ctx = MagicMock()
        ctx.args = ["what", "is", "nastech"]

        await bot.cmd_ask(update, ctx)

        bot.scheduler.brain.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_denied_for_unknown_chat_even_with_allowlist(self):
        """Allowlist is set but this chat ID is not in it."""
        bot = _make_bot([99999])
        update = _make_update(chat_id=12345)
        ctx = MagicMock()

        await bot.cmd_sync(update, ctx)

        first_call_args = update.message.reply_text.call_args_list[0][0]
        assert "Unauthorised" in first_call_args[0] or "⛔" in first_call_args[0]

    @pytest.mark.asyncio
    async def test_sync_allowed_for_authorised_chat(self):
        """Allowlist contains the chat — /sync must proceed (fire the task)."""
        bot = _make_bot([12345])
        update = _make_update(chat_id=12345)
        ctx = MagicMock()

        with patch("nastech_sync.telegram_bot.asyncio.create_task") as mock_task:
            await bot.cmd_sync(update, ctx)
            mock_task.assert_called_once()
