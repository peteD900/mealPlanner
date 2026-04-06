"""Reset dev state: clears meal plans and conversation history, keeps recipes."""
import asyncio
import os
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "data/mealplanner.db")


async def reset():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM meal_plans")
        await db.execute("DELETE FROM session_messages")
        await db.execute("DELETE FROM user_preferences")
        await db.commit()
    print("Cleared: meal_plans, session_messages, user_preferences. Recipes untouched.")


asyncio.run(reset())
