import json
import re

import aiosqlite
import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.claude import run_claude
from db.database import DB_PATH, db_add_recipe, db_list_recipes

URL_RE = re.compile(r"https?://\S+")
RECIPE_RE = re.compile(r"---RECIPE---\s*(\{.*?\})\s*---END---", re.DOTALL)
MAX_PAGE_CHARS = 8000

BOT_COMMANDS = [
    BotCommand("chat", "Chat about meal ideas or what to cook this week"),
    BotCommand("suggest", "Ask Claude to write up a recipe ready to save"),
    BotCommand("add", "Add a recipe — describe it or paste a URL"),
    BotCommand("recipes", "List all saved recipes"),
    BotCommand("shopping", "Paste your shopping list to get a merged weekly list"),
    BotCommand("help", "Show available commands"),
]

HELP_TEXT = (
    "Here's what I can do:\n\n"
    "/chat — talk about meal ideas, what to cook, preferences\n"
    "/suggest — write up a recipe ready to review and save\n"
    "/add — describe a recipe or paste a URL and I'll save it\n"
    "/recipes — see all your saved recipes\n"
    "/shopping — paste your current shopping list and I'll merge it with your meal plan\n\n"
    "You can also just message me directly without a command."
)


async def _fetch_url_text(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text[:MAX_PAGE_CHARS]


def _format_recipe(recipe: dict) -> str:
    lines = [f"*{recipe['title']}*\n"]
    lines.append("*Ingredients*")
    for item in recipe["ingredients"].splitlines():
        if item.strip():
            lines.append(f"• {item.strip()}")
    lines.append("\n*Instructions*")
    for i, step in enumerate(recipe["instructions"].splitlines(), 1):
        step = re.sub(r"^\d+[\.\)]\s*", "", step.strip())
        if step:
            lines.append(f"{i}. {step}")
    return "\n".join(lines)


async def _send_recipe_card(update: Update, context: ContextTypes.DEFAULT_TYPE, display_text: str, recipe: dict) -> None:
    """Show the recipe nicely formatted with a Save button."""
    chat_id = update.effective_chat.id
    context.bot_data[f"pending_recipe_{chat_id}"] = recipe

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Save this recipe", callback_data="save_recipe"),
        InlineKeyboardButton("Discard", callback_data="discard_recipe"),
    ]])

    if display_text.strip():
        await update.message.reply_text(display_text.strip())

    await update.message.reply_text(
        _format_recipe(recipe),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _run_claude_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        reply = await run_claude(user_text, db)

    match = RECIPE_RE.search(reply)
    if match:
        try:
            recipe = json.loads(match.group(1))
            display_text = reply[:match.start()].strip()
            await _send_recipe_card(update, context, display_text, recipe)
            return
        except (json.JSONDecodeError, KeyError):
            pass

    await update.message.reply_text(reply)


# --- Callback handler for Save/Discard buttons ---

async def handle_recipe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    key = f"pending_recipe_{chat_id}"

    if query.data == "save_recipe":
        recipe = context.bot_data.pop(key, None)
        if not recipe:
            await query.edit_message_text("Couldn't find the recipe — try /suggest again.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            recipe_id = await db_add_recipe(db, recipe["title"], recipe["ingredients"], recipe["instructions"])
        await query.edit_message_text(
            f"{_format_recipe(recipe)}\n\n✓ Saved as recipe #{recipe_id}",
            parse_mode="Markdown",
        )
    elif query.data == "discard_recipe":
        context.bot_data.pop(key, None)
        await query.edit_message_text("Recipe discarded.")


# --- Command handlers ---

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def cmd_recipes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        recipes = await db_list_recipes(db)
    if not recipes:
        await update.message.reply_text("No recipes saved yet. Use /add to add one!")
        return
    lines = [f"{r['id']}. {r['title']}" for r in recipes]
    await update.message.reply_text("Your recipes:\n\n" + "\n".join(lines))


async def cmd_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    inline = " ".join(context.args).strip() if context.args else ""
    prompt = f"Please write up this recipe: {inline}" if inline else \
        "Based on our conversation, write up a recipe for me to review."
    await _run_claude_reply(update, context, prompt)


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    inline = " ".join(context.args).strip() if context.args else ""
    if inline:
        await _run_claude_reply(update, context, f"Please add this recipe: {inline}")
    else:
        await update.message.reply_text(
            "Tell me what recipe to add, or paste a URL and I'll create one inspired by it."
        )


async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    inline = " ".join(context.args).strip() if context.args else ""
    if inline:
        await _run_claude_reply(update, context, inline)
    else:
        await update.message.reply_text(
            "What are you thinking about for meals? Ask me anything."
        )


async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Paste your current shopping list and I'll merge it with your meal plan."
    )


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
                "Please create a recipe inspired by this and save it."
            )
        except Exception:
            pass

    await _run_claude_reply(update, context, user_text)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("recipes", cmd_recipes))
    app.add_handler(CommandHandler("suggest", cmd_suggest))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("shopping", cmd_shopping))
    app.add_handler(CallbackQueryHandler(handle_recipe_callback, pattern="^(save|discard)_recipe$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
