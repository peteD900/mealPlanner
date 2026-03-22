import os
from datetime import datetime, timedelta, timezone

import anthropic
import aiosqlite

from bot.tools import TOOLS, execute_tool
from db.database import (
    append_session_message,
    clear_session_messages,
    get_last_message_time,
    get_preferences,
    get_session_messages,
    update_preferences,
)

SESSION_TIMEOUT_HOURS = 2

_SYSTEM_BASE = """\
You are a personal meal planning assistant. You help the user decide what to eat, \
discover new recipes, manage their recipe collection, and plan their weekly meals.

You have access to the following tools:
- list_recipes: retrieve all saved recipes
- add_recipe: save a new recipe
- edit_recipe: update an existing recipe
- delete_recipe: remove a recipe

When the user sends a URL, a recipe inspired by the page content will be included in their \
message — generate a well-structured recipe from it and call add_recipe to save it.

When the user pastes a shopping list (multiple lines that look like grocery items), \
call list_recipes to see their current meal plan context, then return a clean merged \
shopping list based on their meals for the week.

For general conversation — discussing meal ideas, what to cook, preferences, \
nutrition questions — just chat naturally. Use list_recipes when it helps you \
give more relevant suggestions.

## Suggesting a recipe for review

When the user asks you to suggest a specific recipe (via /suggest or by saying something \
like "write that up" or "let's go with that one"), do NOT call add_recipe. Instead, \
present the recipe for review by ending your response with a marker block in this exact format:

---RECIPE---
{"title": "Recipe Title", "ingredients": "ingredient 1\\ningredient 2\\ningredient 3", "instructions": "Step 1\\nStep 2\\nStep 3"}
---END---

Write ingredients as a newline-separated list and instructions as numbered steps separated \
by newlines. The user will be shown a Save button — only call add_recipe if they explicitly \
ask you to save without going through /suggest.\
"""


def _build_system_prompt(preferences: str) -> str:
    if not preferences:
        return _SYSTEM_BASE
    return f"{_SYSTEM_BASE}\n\n## What you know about this user:\n{preferences}"


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
            # Unexpected stop reason — bail out
            return "Sorry, something went wrong. Please try again."
