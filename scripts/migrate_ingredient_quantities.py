"""One-time migration: convert plain newline-separated ingredients to JSON list of {name, quantity}.

Run once after deploying the ingredient-quantity change:

    uv run python scripts/migrate_ingredient_quantities.py

Safe to run multiple times — rows already in JSON form are skipped.
"""
import asyncio
import json
import os

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "data/mealplanner.db")


def _already_migrated(raw: str) -> bool:
    s = raw.strip()
    if not s.startswith("["):
        return False
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, list) and all(
        isinstance(x, dict) and "name" in x for x in parsed
    )


def _convert(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return json.dumps([{"name": line, "quantity": None} for line in lines])


async def migrate() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, title, ingredients FROM recipes") as cursor:
            rows = await cursor.fetchall()

        updated = 0
        skipped = 0
        for row in rows:
            if _already_migrated(row["ingredients"]):
                skipped += 1
                continue
            new_value = _convert(row["ingredients"])
            await db.execute(
                "UPDATE recipes SET ingredients = ? WHERE id = ?",
                (new_value, row["id"]),
            )
            updated += 1
            print(f"  #{row['id']} {row['title']}")
        await db.commit()

    print(f"\nMigrated {updated} recipe(s). Skipped {skipped} already-migrated.")


if __name__ == "__main__":
    asyncio.run(migrate())
