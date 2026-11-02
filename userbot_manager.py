import random
import logging
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH
from database import users_db, blocked_users, save_user

log = logging.getLogger("CN_UB")

user_bots = {}
raid_state = {"reply": {}, "rr": {}, "flag": {}, "hrr": {}}


async def start_ub(uid, ss):
    from userbot_commands import reg_commands
    from scheduler import _restore_schedules_on_startup
    uid = str(uid)
    if uid in blocked_users:
        return
    if uid in user_bots:
        return
    try:
        ub = TelegramClient(
            StringSession(ss), API_ID, API_HASH,
            connection_retries=None,
            retry_delay=1,
            auto_reconnect=True,
            request_retries=5,
            timeout=20,
            flood_sleep_threshold=120,
            device_model="❛.𝁘ໍＣｌｏｎｅ Ｘ🎭.𝁘ໍ",
            system_version="VillainZBot",
            app_version="1.0",
            lang_code="en",
            system_lang_code="en-US",
            use_ipv6=False,
        )
        await ub.start()
        log.info(f"✅ Userbot started: {uid}")
        user_bots[uid] = ub
        reg_commands(ub, int(uid))
        asyncio.create_task(_restore_schedules_on_startup(ub, int(uid)))
        asyncio.create_task(keepalive_loop(uid, ub))
    except Exception as e:
        log.error(f"❌ start_ub {uid} FAILED: {type(e).__name__}: {e}")
        try:
            if uid in users_db:
                users_db[uid]["logged_in"] = False
                users_db[uid]["session_string"] = None
                await save_user(uid, users_db[uid])
        except Exception:
            pass


async def keepalive_loop(uid, ub):
    from telethon.tl.functions import PingRequest
    while True:
        await asyncio.sleep(20)
        if uid not in user_bots or user_bots[uid] is not ub:
            return
        try:
            if not ub.is_connected():
                log.warning(f"🔄 Reconnecting userbot {uid}")
                await ub.connect()
            await asyncio.wait_for(
                ub(PingRequest(ping_id=random.randint(1, 10 ** 9))),
                timeout=10,
            )
        except asyncio.TimeoutError:
            log.warning(f"⏱️ Ping timeout for {uid}, forcing reconnect...")
            try:
                await ub.disconnect()
                await asyncio.sleep(1)
                await ub.connect()
            except Exception as e:
                log.error(f"Reconnect {uid} failed: {e}")
        except Exception as e:
            log.warning(f"Keepalive {uid}: {e}")
            try:
                if not ub.is_connected():
                    await ub.connect()
            except Exception:
                pass
