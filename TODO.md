# Bot Issues — To Fix

Issues identified from a review of `mealplanner/bot/`. Ordered by priority.

---

## Critical

### 1. Shopping list system prompt is wrong about `list_recipes`
**File:** `mealplanner/bot/claude.py:44`

The system prompt tells Claude to "call `list_recipes` to get the full recipes for those meals" — but `list_recipes` only returns `id` and `title`, not ingredients. To build an accurate shopping list, Claude must call `get_recipe` for each relevant recipe ID.

**Fix:** Update the shopping list section of `_SYSTEM_BASE` to instruct Claude to call `list_recipes` first (to get IDs by title), then call `get_recipe` for each meal in the plan to retrieve ingredients.

---

### 2. URL fetching sends raw HTML to Claude
**File:** `mealplanner/bot/handlers.py:32–36`

`_fetch_url_text` returns raw HTML. Recipe content is buried in markup, scripts, and nav. 8000 chars of raw HTML often won't reach the actual recipe.

**Fix:** Parse the response with `BeautifulSoup` (add `beautifulsoup4` + `lxml` via `uv add`) to strip tags and extract meaningful text before passing to Claude.

---

## Moderate

### 3. Meal plan stores title strings, not recipe IDs
**File:** `mealplanner/bot/tools.py:171`, `mealplanner/db/database.py`

`save_meal_plan` stores free-text meal names. The shopping list flow then has to fuzzy-match those titles against saved recipes, which is fragile (case, typos, abbreviations).

**Fix:** Update `save_meal_plan` tool to optionally accept recipe IDs alongside titles. Update the DB schema and `MealPlan` model accordingly. Update the system prompt to instruct Claude to resolve titles to IDs (via `list_recipes`) before saving a plan.

---

### 4. URL fetch failure is silent
**File:** `mealplanner/bot/handlers.py:76–78`

```python
except Exception:
    pass
```

If the URL fetch fails, the original message is sent to Claude unchanged with no indication of failure. Claude sees the URL as plain text.

**Fix:** On exception, prepend a note to `user_text` such as `f"[Could not fetch content from {url}]\n\n{user_text}"` so Claude knows the fetch failed.

---

## Minor

### 5. `list_recipes` uses tuple index access inconsistently
**File:** `mealplanner/bot/tools.py:157`

```python
lines = "\n".join(f"{r[0]}: {r[1]}" for r in recipes)
```

The rest of the codebase uses named `aiosqlite.Row` access (`r['id']`, `r['title']`). This is inconsistent and fragile if column order changes.

**Fix:** Change to `f"{r['id']}: {r['title']}"`.

---

### 6. `/start` missing from `BOT_COMMANDS`
**File:** `mealplanner/bot/handlers.py:20–23`

`/start` is registered as a handler (mapped to `cmd_help`) but not listed in `BOT_COMMANDS`, so it doesn't appear in the Telegram command menu.

**Fix:** Add `BotCommand("start", "Get started")` to `BOT_COMMANDS`.

---

### 7. No recipe search tool
**File:** `mealplanner/bot/tools.py`

If a user asks "do I have anything with chicken?", Claude calls `list_recipes` (titles only) and guesses. This breaks down with large recipe collections.

**Fix:** Add a `search_recipes` tool that accepts a `query` string and does a basic `LIKE` search against title and ingredients in the DB.
