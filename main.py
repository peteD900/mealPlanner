import asyncio
import os

import uvicorn
from dotenv import load_dotenv
from telegram.ext import Application

from mealplanner.bot.handlers import BOT_COMMANDS, register_handlers
from mealplanner.db.database import init_db
from mealplanner.web.app import app as fastapi_app

load_dotenv(override=True)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))


async def run() -> None:
    await init_db()

    ptb_app = Application.builder().token(TELEGRAM_TOKEN).build()
    register_handlers(ptb_app)

    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=WEB_PORT, loop="none", log_level="info")
    server = uvicorn.Server(config)

    await ptb_app.initialize()
    await ptb_app.bot.set_my_commands(BOT_COMMANDS)
    await ptb_app.start()
    await ptb_app.updater.start_polling(drop_pending_updates=True)

    print(f"Bot started. Web app running on http://0.0.0.0:{WEB_PORT}")

    try:
        await server.serve()
    finally:
        await ptb_app.updater.stop()
        await ptb_app.stop()
        await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
