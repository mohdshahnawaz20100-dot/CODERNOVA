#!/usr/bin/env python3
# CODERNOVA USERBOT - Main Entry Point

import asyncio
import logging
from telethon import TelegramClient

from config import BOT_TOKEN, API_ID, API_HASH, OWNER_ID, SESSION_DIR
from database import (
    init_mongo, load_all, users_db, blocked_users, command_usage_db,
    cleanup_old_command_logs,
)
from helpers import cleanup_temp_loop, auto_cleanup_loop, get_ghost_image_path
from health import health_server
from login_flow import register_login_handlers
from bot_commands import register_bot_commands
from userbot_manager import start_ub, user_bots

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S',
)
log = logging.getLogger("CN_MAIN")


bot = TelegramClient(
    str(SESSION_DIR / "clonex_bot"), API_ID, API_HASH,
    device_model="❛.𝁘ໍＣｌｏｎｅ Ｘ🎭.𝁘ໍ",
    system_version="VillainZBot",
    app_version="1.0",
).start(bot_token=BOT_TOKEN)


async def main():
    # ─── Background services ───
    asyncio.create_task(health_server())
    asyncio.create_task(cleanup_temp_loop())

    # ─── MongoDB ───
    mongo_ok = await init_mongo()
    if mongo_ok:
        await load_all()

        async def delayed_cleanup():
            await asyncio.sleep(5)
            await cleanup_old_command_logs()

        asyncio.create_task(delayed_cleanup())
        asyncio.create_task(auto_cleanup_loop())
    else:
        log.warning("⚠️ No MongoDB — data will be lost")

    asyncio.create_task(get_ghost_image_path())

    # ─── Register handlers ───
    register_login_handlers(bot)
    register_bot_commands(bot)

    # ─── Info ───
    me = await bot.get_me()
    log.info(f"✅ Bot: @{me.username}")
    log.info(f"👑 Owner: {OWNER_ID}")

    # ─── Restore userbots ───
    restored = 0
    failed = 0
    for uid, u in list(users_db.items()):
        if u.get("logged_in") and u.get("session_string"):
            if uid in blocked_users:
                continue
            try:
                await start_ub(uid, u["session_string"])
                restored += 1
            except Exception as e:
                failed += 1
                log.error(f"Restore {uid}: {e}")

    log.info(f"✅ Restored {restored} userbot(s)")
    if failed:
        log.warning(f"⚠️ Failed to restore: {failed} userbot(s)")
    log.info(f"🚫 Blocked users: {len(blocked_users)}")
    log.info(f"📊 Command usage tracked: {len(command_usage_db)} users")
    log.info("⚙️ Type .help in Telegram.")

    await bot.run_until_disconnected()


if __name__ == '__main__':
    print("=" * 45)
    print("  CODERNOVA MULTI-USER USERBOT")
    print("=" * 45)
    try:
        bot.loop.run_until_complete(main())
    except KeyboardInterrupt:
        log.info("🛑 Stopped.")
    except Exception as e:
        log.error(f"Fatal: {e}")
