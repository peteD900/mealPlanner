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
- `INGREDIENTS_PATH` — Path to ingredients reference file (default: `data/ingredients.txt`)

## Architecture

Two services run concurrently from `main.py` via asyncio:

1. **Telegram bot** (`mealplanner/bot/`) — all user interaction happens here
2. **FastAPI web server** (`mealplanner/web/`) — read-only recipe browser on port 8000

### Bot flow

`mealplanner/bot/handlers.py` exposes only `/start`, `/help`, and `/recipes`. All free text goes to Claude via `mealplanner/bot/claude.py`, which:

- Maintains conversation history in the `session_messages` DB table
- After 2 hours of inactivity, summarizes the session into `user_preferences` (a singleton row) and clears history
- Runs an agentic tool-use loop: Claude calls tools defined in `mealplanner/bot/tools.py`, which validate inputs with Pydantic and execute against `mealplanner/db/database.py`
- All Telegram responses use `parse_mode="HTML"` — Claude is instructed to use HTML tags only, never markdown syntax

### Tools available to Claude

`save_recipe`, `update_recipe`, `delete_recipe`, `list_recipes`, `get_recipe`, `save_meal_plan`, `get_meal_plan`

### Pydantic models

`mealplanner/bot/models.py` — `Recipe`, `MealPlan`, `ToolResult`. Tool inputs are validated against these before DB operations.

### Database

`mealplanner/db/database.py` — async SQLite (aiosqlite) with four tables:
- `recipes` — the recipe store
- `meal_plans` — weekly meal plans (JSON array of meal titles, latest row is current)
- `session_messages` — conversation history
- `user_preferences` — singleton row; Claude-generated summary of user tastes

### Web UI

`mealplanner/web/app.py` — two routes (`GET /` list, `GET /recipe/{id}` detail), Jinja2 templates in `mealplanner/web/templates/`. Read-only; all writes happen through the bot.

### Ingredients reference

`data/ingredients.txt` — user-maintained list of locally available ingredients (Portugal). One item per line; bullet/dash prefixes are stripped automatically on load. Injected into Claude's system prompt to ground recipe suggestions and shopping lists. Edit this file directly to add or remove items.

### Shopping list flow

User pastes their existing AnyList list → Claude calls `get_meal_plan` + `list_recipes` → returns only the ingredients missing from the pasted list, one per line, plain text, no headers or formatting.

### Model

The bot uses `claude-haiku-4-5-20251001` (cost-efficient for interactive use).
