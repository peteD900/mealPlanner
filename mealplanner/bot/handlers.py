import re

import aiosqlite
import httpx
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from mealplanner.bot.claude import run_claude
from mealplanner.db.database import DB_PATH, db_list_recipes

URL_RE = re.compile(r"https?://\S+")
MAX_PAGE_CHARS = 8000

BOT_COMMANDS = [
    BotCommand("recipes", "List all saved recipes"),
    BotCommand("help", "Show available commands"),
]

HELP_TEXT = (
    "Just message me — I'll handle the rest.\n\n"
    "/recipes — list saved recipes\n\n"
    "You can describe a dish, paste a URL, ask for meal ideas, request a shopping list, or plan your week."
)


async def _fetch_url_text(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text[:MAX_PAGE_CHARS]


async def _run_claude_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        reply = await run_claude(user_text, db)
    await update.message.reply_text(reply, parse_mode="HTML")


# --- Command handlers ---

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def cmd_recipes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        recipes = await db_list_recipes(db)
    if not recipes:
        await update.message.reply_text("No recipes saved yet.")
        return
    lines = [f"{r['id']}. {r['title']}" for r in recipes]
    await update.message.reply_text("\n".join(lines))


# --- Free-text message handler ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text

    url_match = URL_RE.search(user_text)
    if url_match:
        url = url_match.group(0)
        try:
            page_text = await _fetch_url_text(url)
            user_text = (
                f"[Page content from {url}]:\n{page_text}\n\n"
                "Create a recipe inspired by this and offer to save it."
            )
        except Exception:
            pass

    await _run_claude_reply(update, context, user_text)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("recipes", cmd_recipes))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
