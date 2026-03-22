# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
uv run python main.py

# Install dependencies
uv sync

# Add a dependency
uv add <package>
```

No tests exist yet. No linting is configured.

## Environment

Copy `.env` and set these required variables:
- `TELEGRAM_TOKEN` — Telegram bot token
- `ANTHROPIC_API_KEY` — Claude API key

Optional:
- `DB_PATH` — SQLite path (default: `data/mealplanner.db`)
- `WEB_PORT` — Web server port (default: 8000)

## Architecture

Two services run concurrently from `main.py` via asyncio:

1. **Telegram bot** (`bot/`) — all user interaction happens here
2. **FastAPI web server** (`web/`) — read-only recipe browser on port 8000

### Bot flow

`bot/handlers.py` handles Telegram commands (`/suggest`, `/add`, `/chat`, `/shopping`, `/recipes`). For Claude-driven commands, it calls `bot/claude.py`, which:

- Maintains conversation history in the `session_messages` DB table
- After 2 hours of inactivity, summarizes the session into `user_preferences` (a singleton row) and clears history
- Runs an agentic tool-use loop: Claude calls tools (`list_recipes`, `add_recipe`, `edit_recipe`, `delete_recipe`) defined in `bot/tools.py`, which execute against `db/database.py`

**Recipe suggestion UX:** Claude embeds recipe JSON in responses using `---RECIPE---{...}---END---` markers. `handlers.py` regex-extracts this, displays it with inline Save/Discard buttons, and saves to DB on user confirmation.

### Database

`db/database.py` — async SQLite (aiosqlite) with three tables:
- `recipes` — the recipe store
- `session_messages` — conversation history
- `user_preferences` — singleton row; Claude-generated summary of user tastes

### Web UI

`web/app.py` — two routes (`GET /` list, `GET /recipe/{id}` detail), Jinja2 templates in `web/templates/`. Read-only; all writes happen through the bot.

### Model

The bot uses `claude-haiku-4-5-20251001` (cost-efficient for interactive use).
