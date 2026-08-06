# NasTech Sync

24/7 daemon that tracks upstream commits, applies NasTech branding to all text content, and opens Pull Requests on `nastechai/NasTech-Agent` — never pushing directly to main.

## How to run

```bash
python main.py --host 0.0.0.0 --port 5000
```

The managed workflow **NasTech Sync** does this automatically.

## Required secrets (set in Replit Secrets)

| Secret | Purpose |
|--------|---------|
| `GITHUB_TOKEN` | Push branches + open PRs (needs `repo` scope) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot via @BotFather |
| `OPENAI_API_KEY` | OpenAI / GPT-4o brain |
| `OLLAMA_API_KEY` | api.ollama.com cloud brain |

## Optional env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `TELEGRAM_CHAT_IDS` | — | Comma-separated chat IDs allowed to control the bot |
| `OLLAMA_URL` | `https://api.ollama.com` | Ollama endpoint (cloud or self-hosted) |
| `OLLAMA_MODEL` | `llama3.1` | Model name |

## Ports

- **5000** — Web dashboard (FastAPI + Uvicorn)

## Architecture

```
main.py               — CLI entry point
nastech_sync/
  scheduler.py        — asyncio daemon (sync loop + web + Telegram)
  syncer.py           — core sync engine (clone → brand → commit → PR)
  brander.py          — text + path branding engine
  brain.py            — AI brain (OpenAI or api.ollama.com)
  telegram_bot.py     — Telegram bot interface
  webapp.py           — FastAPI web dashboard
  git_ops.py          — subprocess git wrapper
  github_api.py       — GitHub REST API (PR creation)
  config.py           — config + branding rules
config.yaml           — editable configuration
```

## State file

Sync state (last synced SHA, last PR URL) is stored at:
`~/.nastech-sync/workspace/nastech_sync_state.json`

## Branding

17 ordered rules replace all Hermes/NousResearch references with NasTech equivalents. Rules fire most-specific first to avoid partial URL corruption. Edit `config.yaml` → `extra_branding_rules` to add custom rules.

## User preferences

- Ollama brain uses `api.ollama.com/v1` (OpenAI-compatible endpoint), not a local server
- Telegram bot must handle free-form chat (routes to AI brain) as well as commands
- Dry-run mode does NOT advance sync state (no real push made)
- PR URL is saved in state and reported in Telegram sync notifications
