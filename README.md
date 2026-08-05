# NasTech Sync

Keeps **[nastechai/NasTech-Agent](https://github.com/nastechai/NasTech-Agent)** in perfect sync with **[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)** — every commit, branded as NasTech, opened as a Pull Request. **Never pushes directly to main.**

---

## What it does

1. **Tracks** upstream `NousResearch/hermes-agent` for new commits
2. **Pulls** every new commit automatically
3. **Brands** all text content — replaces `Hermes`, `NousResearch`, `hermes-agent`, etc. with NasTech equivalents
4. **Creates a sync branch** → `nastech-sync/YYYYMMDD-<sha>`
5. **Pushes the branch** and **opens a Pull Request** on `nastechai/NasTech-Agent` — main is never touched directly
6. **AI Brain** (OpenAI Codex or Ollama cloud) answers questions about the codebase
7. **Telegram Bot** sends notifications and lets you control everything from your phone — 24/7

---

## Quick start

### 1. Install dependencies

```bash
cd tools/nastech-sync
pip install -r requirements.txt
```

### 2. Authenticate (interactive login)

```bash
python -m nastech_sync login
```

This prompts for (all values are stored in `~/.nastech-sync/workspace/.env`):

| Credential | Where to get it |
|------------|----------------|
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) — needs `repo` scope |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) — for Codex/GPT-4o brain |
| `OLLAMA_URL` | Your cloud Ollama endpoint (Fly.io, Render, etc.) |
| `TELEGRAM_BOT_TOKEN` | Create a bot via [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_IDS` | Your chat ID from [@userinfobot](https://t.me/userinfobot) |

### 3. Test locally (no push, no PR)

```bash
python -m nastech_sync test
```

Clones both repos, applies all branding, creates the sync branch — but stops before pushing. Confirms everything works before touching GitHub.

### 4. Run a real sync (branch + PR)

```bash
python -m nastech_sync sync
```

Applies branding, creates `nastech-sync/YYYYMMDD-<sha>`, pushes it, and opens a PR on `nastechai/NasTech-Agent`. **Never touches `main` directly.**

### 5. Run 24/7 (web dashboard + Telegram + auto-sync)

```bash
python main.py
```

| Flag | Default | Description |
|------|---------|-------------|
| `--interval 30` | 30 min | How often to check for upstream commits |
| `--port 8080` | 8080 | Web dashboard port |
| `--no-telegram` | — | Skip Telegram bot |
| `--no-web` | — | Skip web dashboard |
| `--once` | — | Run one sync and exit |

---

## Commands

| Command | Description |
|---------|-------------|
| `login` | Authenticate interactively (GitHub, OpenAI, Ollama, Telegram) |
| `test` | Full local test — clone + brand + branch, **no push, no PR** |
| `sync` | Pull upstream + brand + push branch + open PR |
| `sync --dry-run` | Brand locally and create branch only — no push, no PR |
| `sync --full` | Re-brand everything from scratch |
| `status` | Show sync state, last PR, last commit |
| `prs` | List open PRs on `nastechai/NasTech-Agent` |
| `rules` | List all 17 active branding rules |
| `preview <text>` | Test branding rules on a text snippet |

---

## PR Workflow

Every sync opens a Pull Request — never a direct push to `main`:

```
upstream commit
      ↓
NasTech branding applied
      ↓
branch: nastech-sync/20260805-1be70d63
      ↓
PR: "NasTech Updates from Source End: <description>"
      ↓
You review + merge on GitHub
```

**Commit messages look like:**
```
NasTech Updates from Source End: Add tool call streaming support

Source: NousResearch/hermes-agent@1be70d635488
Original author: teknium
NasTech-Agent auto-sync — branding applied
```

---

## Branding rules (17 rules, order-safe)

Rules fire in specificity order — full URLs first, then org names, then bare words — so no partial replacements corrupt URLs.

| From | To |
|------|----|
| `github.com/NousResearch/hermes-agent` | `github.com/nastechai/NasTech-Agent` |
| `https://github.com/NousResearch` | `https://github.com/nastechai` |
| `nousresearch/hermes-agent` | `nastechai/nastech-agent` |
| `hermes-agent` | `NasTech-Agent` |
| `hermes_agent` | `nastech_agent` |
| `HermesAgent` | `NasTechAgent` |
| `NousResearch` | `NasTech Research` |
| `HERMES` | `NASTECH` |
| `Hermes` | `NasTech` |
| `hermes` | `nastech` |
| …and 7 more | (run `rules` to see all) |

---

## AI Brain

The brain supports two providers, tried in order:

| Provider | Auth | Type |
|----------|------|------|
| **OpenAI (Codex/GPT-4o)** | `OPENAI_API_KEY` via `login` | Cloud API |
| **Ollama** | `OLLAMA_URL` (cloud endpoint) | Self-hosted cloud |

If neither is available, the tool still works — sync and branding run without AI.

**Ask the brain anything** via Telegram (`/ask`) or the web dashboard.

---

## Telegram Bot

Start the daemon (`python main.py`) and your bot is live 24/7.

| Command | Does |
|---------|------|
| `/status` | Current sync state |
| `/sync` | Trigger a manual sync + PR |
| `/dryrun` | Sync without pushing |
| `/rules` | List branding rules |
| `/ask <q>` | Ask the AI brain |
| `/brain` | Show AI provider status |
| Or just type | Free-form question to the brain |

---

## Web Dashboard

Available at `http://localhost:8080` when running `python main.py`.

- **Dashboard** — sync stats, state, recent syncs
- **Sync History** — full log of every sync
- **AI Brain** — live chat with streaming responses + Markdown rendering
- **Markdown Editor** — write + preview Markdown side by side
- **Brand Tools** — live branding preview for any text
- **Branding Rules** — full table of all active rules
- **Upstream Info** — everything the system knows about NousResearch/hermes-agent

---

## File structure

```
tools/nastech-sync/
├── nastech_sync/
│   ├── config.py       — Config + branding rules (ordered correctly)
│   ├── brander.py      — Text + path branding engine
│   ├── git_ops.py      — Git operations (clone, branch, commit, push)
│   ├── github_api.py   — GitHub REST API (PR creation, branch listing)
│   ├── syncer.py       — Core sync engine (PR-based workflow)
│   ├── brain.py        — AI brain (OpenAI Codex + Ollama cloud)
│   ├── telegram_bot.py — Telegram bot (24/7 commands + notifications)
│   ├── webapp.py       — FastAPI web dashboard
│   ├── scheduler.py    — 24/7 daemon (web + Telegram + sync loop)
│   └── cli.py          — CLI entry point
├── webapp/static/
│   └── index.html      — Rich single-page dashboard
├── main.py             — Main entry point (daemon)
├── config.yaml         — Configuration
└── requirements.txt    — Python dependencies
```

---

## Environment variables

All set via `python -m nastech_sync login` or directly in your shell:

```bash
export GITHUB_TOKEN=ghp_...          # Required for push + PR
export OPENAI_API_KEY=sk-...         # Optional: Codex/GPT-4o brain
export OLLAMA_URL=https://...        # Optional: cloud Ollama brain
export TELEGRAM_BOT_TOKEN=...        # Optional: Telegram bot
export TELEGRAM_CHAT_IDS=123456789   # Optional: restrict bot access
```
