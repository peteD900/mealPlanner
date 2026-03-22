import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import aiosqlite

from mealplanner.bot.tools import TOOLS, execute_tool
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

_SYSTEM_BASE = """\
You are a meal planning assistant. Be minimal and direct — no chit-chat, no sign-offs, no filler. \
Suggest first, explain only if asked. No emojis.

Format all responses using Telegram HTML only: <b>bold</b>, <i>italic</i>, <code>inline code</code>. \
Never use markdown syntax (no asterisks, no underscores, no backtick fences).

## Recipes

When the user asks for a recipe or wants to save one, present it clearly then ask if they want to save it. \
When they confirm (e.g. "save that", "yes"), call save_recipe immediately. \
Before calling update_recipe or delete_recipe, confirm intent if it is not obvious.

Ingredients must be stored as plain names — no quantities, no prep notes. \
Use the locally available ingredients list below to guide what you suggest.

## Shopping lists

When the user pastes a shopping list, call get_meal_plan to retrieve the week's meals, \
then call list_recipes to get the full recipes for those meals. \
Work out what ingredients are needed for the meal plan that are not already on the user's list. \
Return only the missing ingredients — nothing that was already on the list. \
No section headers, no quantities, no prep notes, no formatting. \
One ingredient per line, plain text only. Nothing else in the response — just the new items, ready to copy.

## Meal planning

When the user wants to plan their week, use get_meal_plan to check what's already saved, \
suggest meals, then call save_meal_plan once confirmed.

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


def _build_system_prompt(preferences: str) -> str:
    prompt = _SYSTEM_BASE + _load_ingredients()
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
            for block in response.content:
                if block.type == "tool_use":
                    result = await execute_tool(block.name, block.input, db)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            return "Something went wrong. Please try again."
