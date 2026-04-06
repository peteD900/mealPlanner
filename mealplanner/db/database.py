import json
import os
from datetime import datetime, timezone

import aiosqlite

from mealplanner.bot.models import MealPlan, Recipe

DB_PATH = os.getenv("DB_PATH", "data/mealplanner.db")


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                ingredients TEXT NOT NULL,
                instructions TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                summary TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS meal_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meals TEXT NOT NULL,
                week_of DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()


# --- Recipes ---

async def db_add_recipe(db: aiosqlite.Connection, title: str, ingredients: str, instructions: str) -> Recipe:
    cursor = await db.execute(
        "INSERT INTO recipes (title, ingredients, instructions) VALUES (?, ?, ?)",
        (title, ingredients, instructions),
    )
    await db.commit()
    rows = await db.execute_fetchall(
        "SELECT id, title, ingredients, instructions, created_at FROM recipes WHERE id = ?",
        (cursor.lastrowid,),
    )
    r = rows[0]
    return Recipe(id=r[0], title=r[1], ingredients=r[2], instructions=r[3], created_at=r[4])


async def db_edit_recipe(db: aiosqlite.Connection, id: int, title: str = None, ingredients: str = None, instructions: str = None) -> None:
    fields, values = [], []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if ingredients is not None:
        fields.append("ingredients = ?")
        values.append(ingredients)
    if instructions is not None:
        fields.append("instructions = ?")
        values.append(instructions)
    if not fields:
        return
    values.append(id)
    await db.execute(f"UPDATE recipes SET {', '.join(fields)} WHERE id = ?", values)
    await db.commit()


async def db_delete_recipe(db: aiosqlite.Connection, id: int) -> None:
    await db.execute("DELETE FROM recipes WHERE id = ?", (id,))
    await db.commit()


async def db_list_recipes(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute("SELECT id, title FROM recipes ORDER BY created_at DESC") as cursor:
        return await cursor.fetchall()


async def db_search_recipes(db: aiosqlite.Connection, query: str) -> list[aiosqlite.Row]:
    pattern = f"%{query}%"
    async with db.execute(
        "SELECT id, title FROM recipes WHERE title LIKE ? OR ingredients LIKE ? ORDER BY created_at DESC",
        (pattern, pattern),
    ) as cursor:
        return await cursor.fetchall()


async def db_get_recipe(db: aiosqlite.Connection, id: int) -> Recipe | None:
    async with db.execute(
        "SELECT id, title, ingredients, instructions, created_at FROM recipes WHERE id = ?", (id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return Recipe(id=row[0], title=row[1], ingredients=row[2], instructions=row[3], created_at=row[4])


# --- Meal plans ---

async def db_save_meal_plan(db: aiosqlite.Connection, meals: list[str], week_of: str | None = None) -> MealPlan:
    await db.execute(
        "INSERT INTO meal_plans (meals, week_of) VALUES (?, ?)",
        (json.dumps(meals), week_of),
    )
    await db.commit()
    return MealPlan(meals=meals, week_of=week_of)


async def db_get_meal_plan(db: aiosqlite.Connection) -> MealPlan | None:
    async with db.execute(
        "SELECT meals, week_of FROM meal_plans ORDER BY created_at DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return MealPlan(meals=json.loads(row[0]), week_of=row[1])


# --- Session messages ---

async def get_session_messages(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute("SELECT role, content, created_at FROM session_messages ORDER BY id ASC") as cursor:
        return await cursor.fetchall()


async def get_last_message_time(db: aiosqlite.Connection) -> datetime | None:
    async with db.execute("SELECT created_at FROM session_messages ORDER BY id DESC LIMIT 1") as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)


async def append_session_message(db: aiosqlite.Connection, role: str, content: str) -> None:
    await db.execute(
        "INSERT INTO session_messages (role, content) VALUES (?, ?)",
        (role, content),
    )
    await db.commit()


async def clear_session_messages(db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM session_messages")
    await db.commit()


# --- User preferences ---

async def get_preferences(db: aiosqlite.Connection) -> str:
    async with db.execute("SELECT summary FROM user_preferences WHERE id = 1") as cursor:
        row = await cursor.fetchone()
    return row[0] if row else ""


async def update_preferences(db: aiosqlite.Connection, summary: str) -> None:
    await db.execute(
        "INSERT INTO user_preferences (id, summary, updated_at) VALUES (1, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at",
        (summary,),
    )
    await db.commit()
