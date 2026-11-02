import re
import logging
import asyncio
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError,
)
from config import API_ID, API_HASH, OWNER_ID
from database import get_user, save_user, blocked_users, users_db, track_start, all_users_db

log = logging.getLogger("CN_LOGIN")

pending_clients = {}
user_bots = {}


def register_login_handlers(bot):
    @bot.on(events.NewMessage(pattern='/login'))
    async def login_h(event):
        log.info(f"🔥 /login from {event.sender_id}")
        try:
            uid = str(event.sender_id)
            if uid in blocked_users:
                await event.reply("🚫 **Aap is bot ko use nahi kar sakte.**")
                return
            u = get_user(event.sender_id)
            if u["logged_in"]:
                await event.reply(
                    f"✅ Already logged in as `{u.get('tg_name', 'N/A')}`\n\n"
                    f"Pehle `/logout` karo.",
                    parse_mode='markdown',
                )
                return
            await event.reply(
                "📱 **Phone number bhejo** (country code ke saath)\n"
                "Example: `+919876543210`"
            )
            u["step"] = "await_phone"
            asyncio.create_task(save_user(event.sender_id, u))
        except Exception as e:
            log.error(f"❌ /login error: {e}", exc_info=True)

    @bot.on(events.NewMessage(pattern='/logout'))
    async def logout_h(event):
        log.info(f"🔥 /logout from {event.sender_id}")
        try:
            uid = str(event.sender_id)
            u = get_user(uid)
            if not u["logged_in"]:
                await event.reply("❌ Aap login nahi ho. `/login`")
                return
            if uid in user_bots:
                try:
                    await user_bots[uid].disconnect()
                except Exception:
                    pass
                del user_bots[uid]
            u["logged_in"] = False
            u["session_string"] = None
            u["step"] = None
            await event.reply("✅ **Logged Out!**")
            asyncio.create_task(save_user(uid, u))
        except Exception as e:
            log.error(f"❌ /logout error: {e}", exc_info=True)

    @bot.on(events.NewMessage(
        func=lambda e: e.is_private and not e.out and not (e.text or "").startswith('/')
    ))
    async def login_flow(event):
        uid = event.sender_id
        if str(uid) in blocked_users:
            return
        u = get_user(uid)
        st = u.get("step")
        if not st:
            return
        text = (event.text or "").strip()

        if st == "await_phone":
            if not text.startswith("+") or len(re.sub(r'\D', '', text)) < 8:
                await event.reply("❌ Galat. Example: `+919876543210`")
                return
            try:
                await event.reply("⏳ Client ban raha hai...")
                cli = TelegramClient(
                    StringSession(), API_ID, API_HASH,
                    device_model="❛.𝁘ໍＣｌｏｎｅ Ｘ🎭.𝁘ໍ",
                    system_version="VillainZBot",
                    app_version="1.0",
                )
                await cli.connect()
                sent = await cli.send_code_request(text)
                pending_clients[uid] = cli
                u["phone"] = text
                u["phone_code_hash"] = sent.phone_code_hash
                u["step"] = "await_otp"
                asyncio.create_task(save_user(uid, u))
                await event.reply(
                    "📨 **OTP BHEJA GAYA!**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "OTP space ke saath bhejo\n\n"
                    "**Example:**\n"
                    "`1 2 3 4 5`\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ **Bina space wala OTP accept nahi hoga**",
                    parse_mode='markdown',
                )
            except Exception as e:
                u["step"] = None
                asyncio.create_task(save_user(uid, u))
                await event.reply(f"❌ `{str(e)[:200]}`")
            return

        if st == "await_otp":
            raw = text.strip()
            if " " not in raw:
                await event.reply(
                    "❌ **Space ke saath bhejo**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "**Example:**\n"
                    "`1 2 3 4 5`\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ **Bina space wala OTP accept nahi hoga**",
                    parse_mode='markdown',
                )
                return
            otp = raw.replace(" ", "")
            if not otp.isdigit():
                await event.reply("❌ Sirf digits (space ke saath)")
                return
            cli = pending_clients.get(uid)
            if not cli:
                u["step"] = None
                asyncio.create_task(save_user(uid, u))
                await event.reply("❌ Session khatam.")
                return
            try:
                await cli.sign_in(
                    phone=u["phone"], code=otp,
                    phone_code_hash=u["phone_code_hash"],
                )
                await _finalize(uid, cli, event, bot)
            except SessionPasswordNeededError:
                u["step"] = "await_password"
                asyncio.create_task(save_user(uid, u))
                await event.reply("🔐 **Two-Step Verification Password Required!**")
            except PhoneCodeInvalidError:
                await event.reply("❌ Galat OTP.")
            except PhoneCodeExpiredError:
                u["step"] = None
                asyncio.create_task(save_user(uid, u))
                await event.reply("❌ Expire. `/login`")
            except Exception as e:
                u["step"] = None
                asyncio.create_task(save_user(uid, u))
                await event.reply(f"❌ `{str(e)[:200]}`")
            return

        if st == "await_password":
            cli = pending_clients.get(uid)
            if not cli:
                u["step"] = None
                asyncio.create_task(save_user(uid, u))
                await event.reply("❌ Session khatam.")
                return
            try:
                await cli.sign_in(password=text)
                try:
                    await event.delete()
                except Exception:
                    pass
                await _finalize(uid, cli, event, bot)
            except PasswordHashInvalidError:
                await event.reply("❌ Galat 2FA Password!")
            except Exception as e:
                u["step"] = None
                asyncio.create_task(save_user(uid, u))
                await event.reply(f"❌ `{str(e)[:200]}`")
            return


async def _finalize(uid, cli, event, bot):
    from userbot_manager import start_ub
    uid = str(uid)
    if uid in blocked_users:
        try:
            await cli.disconnect()
        except Exception:
            pass
        return
    u = users_db[uid]
    try:
        me = await cli.get_me()
        u["session_string"] = cli.session.save()
        u["logged_in"] = True
        u["step"] = None
        u["tg_id"] = me.id
        u["tg_name"] = (
            (me.first_name or "")
            + (" " + me.last_name if me.last_name else "")
        ).strip()
        u["tg_username"] = me.username or "None"
        u["login_time"] = datetime.now().strftime("%d %b %Y, %I:%M %p")
        await save_user(uid, u)
        if uid not in all_users_db:
            await track_start(uid, u["tg_name"], u["tg_username"])
        pending_clients.pop(uid, None)
        await start_ub(uid, u["session_string"])
        await event.reply(
            f"🎉 **USERBOT ACTIVE!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 **{u['tg_name']}**\n"
            f"🆔 `{u['tg_id']}`\n"
            f"📛 @{u['tg_username']}\n\n"
            f"**Bot On hai** ye check karne ke liye\n"
            f"👉 `.alive` Bhejo\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Logout:** `/logout`",
            parse_mode='markdown',
        )
        try:
            await bot.send_message(
                OWNER_ID,
                f"🔔 **New Login**\n"
                f"👤 `{u['tg_name']}`\n"
                f"🆔 `{u['tg_id']}`\n"
                f"📛 @{u['tg_username']}\n"
                f"🕐 `{u['login_time']}`",
                parse_mode='markdown',
            )
        except Exception:
            pass
    except Exception as e:
        log.error(f"finalize: {e}")
        await event.reply(f"❌ `{str(e)[:200]}`")
