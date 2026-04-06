# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app locally (kills any existing instance first)
./scripts/run.sh

# Reset dev state (clears meal plans + conversation history, keeps recipes)
uv run python scripts/reset_dev.py

# Install dependencies
uv sync

# Add a dependency
uv add <package>
```

## Deploying with Docker

```bash
git clone <repo>
cd mealPlanner
cp .env.example .env        # fill in TELEGRAM_TOKEN and ANTHROPIC_API_KEY
# copy data/ingredients.txt and data/sites.txt into ./data/
docker compose up -d
```

The `./data` directory is mounted as a volume — the database and config files persist across restarts and rebuilds. To update the app:

```bash
git pull
docker compose up -d --build
```

# Run tests
uv run pytest tests/ -v

No linting is configured.

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

`save_recipe`, `update_recipe`, `delete_recipe`, `list_recipes`, `get_recipe`, `search_recipes`, `save_meal_plan`, `get_meal_plan`, `return_shopping_list`

### Pydantic models

`mealplanner/bot/models.py` — `Recipe`, `MealEntry`, `MealPlan`, `ShoppingList`, `ToolResult`. Tool inputs are validated against these before DB operations.

### Database

`mealplanner/db/database.py` — async SQLite (aiosqlite) with four tables:
- `recipes` — the recipe store
- `meal_plans` — one row per week (unique index on `week_of`); meals stored as JSON array of `{id, title}` objects; upserted on save
- `session_messages` — conversation history
- `user_preferences` — singleton row; Claude-generated summary of user tastes

### Web UI

`mealplanner/web/app.py` — two routes (`GET /` list, `GET /recipe/{id}` detail), Jinja2 templates in `mealplanner/web/templates/`. Read-only; all writes happen through the bot.

### Ingredients reference

`data/ingredients.txt` — user-maintained list of locally available ingredients (Portugal). One item per line; bullet/dash prefixes are stripped automatically on load. Injected into Claude's system prompt to ground recipe suggestions and shopping lists. Edit this file directly to add or remove items.

### Recipe style inspiration

`data/sites.txt` — user-maintained list of cooking websites whose style Claude should draw inspiration from. One site per line (e.g. `Smitten Kitchen (smittenkitchen.com)`). Injected into the system prompt at runtime — no fetching occurs. Claude uses its training knowledge of these sites for style guidance.

### Shopping list flow

User pastes their existing AnyList list → Claude calls `get_meal_plan` (no args, gets most recent week) → calls `get_recipe` for each meal ID in the plan → computes missing ingredients → calls `return_shopping_list` with the result. Output is one ingredient per line, plain text, no headers or formatting.

### Model

The bot uses `claude-haiku-4-5-20251001` (cost-efficient for interactive use).
