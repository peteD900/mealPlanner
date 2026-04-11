import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import aiosqlite

from mealplanner.bot.tools import SHOPPING_LIST_SENTINEL, TOOLS, execute_tool
from mealplanner.db.database import (
    append_session_message,
    clear_session_messages,
    get_last_message_time,
    get_preferences,
    get_session_messages,
    update_preferences,
)

SESSION_TIMEOUT_HOURS = 2

INGREDIENTS_PATH = Path(os.getenv("INGREDIENTS_PATH", "data/ingredients.txt"))
SITES_PATH = Path(os.getenv("SITES_PATH", "data/sites.txt"))

_SYSTEM_BASE = """\
You are a meal planning assistant. Be minimal and direct — no chit-chat, no sign-offs, no filler. \
Suggest first, explain only if asked. No emojis.

Format all responses using Telegram HTML only: <b>bold</b>, <i>italic</i>, <code>inline code</code>. \
Never use markdown syntax (no asterisks, no underscores, no backtick fences).

## Recipes

When the user asks for a recipe or wants to save one, present it clearly then ask if they want to save it. \
When they confirm (e.g. "save that", "yes"), call save_recipe immediately — never skip the tool call. \
After saving, your confirmation must include the recipe ID returned by the tool (e.g. "Saved as recipe #3."). \
Never say "Saved" without having called save_recipe and received an ID. \
Before calling update_recipe or delete_recipe, confirm intent if it is not obvious.

Each ingredient has a plain shopping-list-ready 'name' (no prep notes, no quantity embedded in it) \
and an optional free-form 'quantity' string (e.g. "2", "300g", "1 tbsp"). Quantities belong in the \
quantity field only, never in the name. Omit quantity for staples like salt, pepper, olive oil where \
a precise amount isn't useful. Use the locally available ingredients list below to guide what you suggest.

## Shopping lists

When the user pastes a shopping list: \
1. Call get_meal_plan with no week_of argument to get the most recent plan. \
2. Each meal in the plan has an id and title. Call get_recipe for each meal id to retrieve its ingredients. \
   If get_recipe returns not found for a meal, skip that meal silently — do not mention it. \
3. Each ingredient comes back as an object with 'name' and optional 'quantity'. Use only the 'name' field — \
   ignore quantities entirely for shopping list purposes. Combine all ingredient names from the recipes \
   you retrieved. Remove anything already on the user's list. \
4. Call return_shopping_list with the missing ingredient names — one plain name per item, no quantities, no prep notes. Do not say anything else.

## Meal planning

Meal plans are stored per week, identified by the Monday of that week. \
When the user wants to plan meals, always confirm which week they mean before saving \
(e.g. "Which week — this one starting Monday 7 April, or next week?"). \
Use get_meal_plan to check what's already saved for that week. \
Each meal must be a saved recipe — use the ID returned by save_recipe or look up IDs via list_recipes. \
Call save_meal_plan with meals as a list of objects with id and title, and week_of as the Monday ISO date. \
Saving overwrites the existing plan for that week.

## Core recipes

Core recipes are staple meals the user cooks regularly — they aim to keep around 10–12. \
Use list_core_recipes to see them. Use mark_recipe_core to mark or unmark any recipe as core. \
When helping the user plan meals for a week, call list_core_recipes first and suggest including \
some core recipes alongside any new ideas. Mention this naturally — never expose tool names \
or internal flags to the user.

## URLs

When the user sends a URL, page content will be included in their message. \
Generate a recipe inspired by it, present it, and offer to save it.\
"""


def _load_ingredients() -> str:
    try:
        lines = INGREDIENTS_PATH.read_text().splitlines()
        cleaned = [line.lstrip("-•* \t") for line in lines if line.strip()]
        if cleaned:
            return "\n\n## Locally available ingredients (Portugal)\n" + "\n".join(cleaned)
    except FileNotFoundError:
        pass
    return ""


def _load_sites() -> str:
    try:
        lines = SITES_PATH.read_text().splitlines()
        cleaned = [line.lstrip("-•* \t") for line in lines if line.strip()]
        if cleaned:
            return (
                "\n\n## Recipe style inspiration\n"
                "Draw stylistic inspiration from these sources when suggesting recipes — "
                "their flavour profiles, techniques, and presentation style. You are not limited to them.\n"
                + "\n".join(cleaned)
            )
    except FileNotFoundError:
        pass
    return ""


def _build_system_prompt(preferences: str) -> str:
    today = datetime.now(timezone.utc).date()
    days_since_monday = today.weekday()  # Monday=0
    this_monday = today - timedelta(days=days_since_monday)
    next_monday = this_monday + timedelta(days=7)
    date_context = (
        f"\n\n## Current date\nToday is {today.strftime('%A %-d %B %Y')}. "
        f"This week's Monday is {this_monday}. Next week's Monday is {next_monday}. "
        f"You have been given the current date — never tell the user you don't know it."
    )
    prompt = _SYSTEM_BASE + date_context + _load_ingredients() + _load_sites()
    if preferences:
        prompt += f"\n\n## What you know about this user\n{preferences}"
    return prompt


async def _summarize_session(messages: list, existing_preferences: str) -> str:
    client = anthropic.AsyncAnthropic()
    history_text = "\n".join(f"{m[0].upper()}: {m[1]}" for m in messages)
    prompt = (
        f"Existing preferences summary:\n{existing_preferences}\n\n"
        f"Recent conversation:\n{history_text}\n\n"
        "Extract any new insights about the user's food preferences, dislikes, dietary habits, "
        "or patterns from the conversation above. Merge them with the existing summary. "
        "Return only the updated summary as plain text. Keep it concise."
    )
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def run_claude(user_text: str, db: aiosqlite.Connection) -> str:
    # Check session boundary
    last_time = await get_last_message_time(db)
    if last_time is not None:
        now = datetime.now(timezone.utc)
        if now - last_time > timedelta(hours=SESSION_TIMEOUT_HOURS):
            old_messages = await get_session_messages(db)
            if old_messages:
                existing_prefs = await get_preferences(db)
                new_prefs = await _summarize_session(old_messages, existing_prefs)
                await update_preferences(db, new_prefs)
            await clear_session_messages(db)

    preferences = await get_preferences(db)
    system_prompt = _build_system_prompt(preferences)

    session_rows = await get_session_messages(db)
    messages = [{"role": row[0], "content": row[1]} for row in session_rows]
    messages.append({"role": "user", "content": user_text})

    client = anthropic.AsyncAnthropic()

    while True:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            final_text = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "",
            )
            await append_session_message(db, "user", user_text)
            await append_session_message(db, "assistant", final_text)
            return final_text

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            shopping_list_output = None
            for block in response.content:
                if block.type == "tool_use":
                    result = await execute_tool(block.name, block.input, db)
                    if result.startswith(SHOPPING_LIST_SENTINEL):
                        # Capture output but keep looping so all tool results are collected
                        shopping_list_output = result[len(SHOPPING_LIST_SENTINEL):]
                        # Replace sentinel in tool result so the API sees a clean ack
                        result = '{"success": true, "message": "Shopping list returned."}'
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Return shopping list immediately after all tools in this turn are processed
            if shopping_list_output is not None:
                await append_session_message(db, "user", user_text)
                await append_session_message(db, "assistant", shopping_list_output)
                return shopping_list_output

            messages.append({"role": "user", "content": tool_results})

        else:
            return "Something went wrong. Please try again."
