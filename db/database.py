import os
from datetime import datetime, timezone

import aiosqlite

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
        """)
        await db.commit()


# --- Recipes ---

async def db_add_recipe(db: aiosqlite.Connection, title: str, ingredients: str, instructions: str) -> int:
    cursor = await db.execute(
        "INSERT INTO recipes (title, ingredients, instructions) VALUES (?, ?, ?)",
        (title, ingredients, instructions),
    )
    await db.commit()
    return cursor.lastrowid


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


async def db_get_recipe(db: aiosqlite.Connection, id: int) -> aiosqlite.Row | None:
    async with db.execute("SELECT * FROM recipes WHERE id = ?", (id,)) as cursor:
        return await cursor.fetchone()


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
