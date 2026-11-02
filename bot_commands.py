import time
import logging
import asyncio
from telethon import events
from config import OWNER_ID
from database import all_users_db, users_db, blocked_users, get_user, block_user_db, unblock_user_db, save_user
from userbot_manager import user_bots

log = logging.getLogger("CN_BOTCMD")

def register_bot_commands(bot):
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_h(event):
        uid = event.sender_id
        if str(uid) in blocked_users: return
        u = get_user(uid)
        if u.get("logged_in"):
            caption = "✅ **ᴀʟʀᴇᴀᴅʏ ʟᴏɢɢᴇᴅ ɪɴ!**\n\n`/help` — ʜᴇʟᴘ\n`/status` — sᴛᴀᴛᴜs\n`/logout` — ʟᴏɢᴏᴜᴛ\n\nApna userbot use karne ke liye kisi bhi chat me `.help` bhejo."
        else:
            caption = "🎉 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ CLONE_SHAH 🎉\n\n🛑 ʟᴏɢɪɴ sᴛᴇᴘs:\n🔷 sᴇɴᴅ /login\n🔷 sᴇɴᴅ ᴘʜᴏɴᴇ ɴᴜᴍʙᴇʀ\n🔷 sᴇɴᴅ ᴏᴛᴘ (sᴘᴀᴄᴇ ᴋᴇ sᴀᴀᴛʜ)\n\n🔐 ᴛʏᴘᴇ: /login"
        await event.reply(caption, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/help'))
    async def help_h(event):
        uid = event.sender_id
        if str(uid) in blocked_users: return
        base = "🛑 **Bot Commands**\n\n🔹 **Login:**\n• `/start`\n• `/login`\n• `/logout`\n• `/status`\n\n🔹 **Userbot:**\nLogin ke baad kisi bhi chat me `.alive` bhejo\n\n"
        if uid == OWNER_ID:
            await event.reply(base + "👑 **Owner:**\n• `/users`\n• `/stats`\n• `/block`\n• `/unblock`\n• `/broadcast`", parse_mode='markdown')
        else:
            await event.reply(base, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/status'))
    async def status_h(event):
        u = get_user(event.sender_id)
        if u.get("logged_in"):
            await event.reply(f"✅ **Logged In**\n👤 `{u.get('tg_name','N/A')}`\n🆔 `{u.get('tg_id','N/A')}`", parse_mode='markdown')
        else:
            await event.reply("❌ Not logged in. `/login`")

    @bot.on(events.NewMessage(pattern='/users'))
    async def users_h(event):
        if event.sender_id != OWNER_ID: return
        if not all_users_db:
            await event.reply("📭 Koi user nahi."); return
        logged = sum(1 for u in users_db.values() if u.get("logged_in"))
        t = f"👥 **Total: {len(all_users_db)}**\n✅ **Logged In: {logged}**\n🚫 **Blocked: {len(blocked_users)}**\n\n"
        await event.reply(t, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/stats'))
    async def stats_h(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(f"📊 **Stats**\n👥 Total: `{len(all_users_db)}`\n✅ Logged: `{len(users_db)}`\n🟢 Active: `{len(user_bots)}`\n🚫 Blocked: `{len(blocked_users)}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/broadcast(\s+.*)?$'))
    async def bcast_h(event):
        if event.sender_id != OWNER_ID: return
        text = (event.text or "").replace("/broadcast", "", 1).strip()
        if not text and not event.is_reply:
            await event.reply("❌ `/broadcast <message>`"); return
        targets = set(all_users_db.keys())
        for uid, u in users_db.items():
            if u.get("logged_in"):
                targets.add(str(uid))
                if u.get("tg_id"): targets.add(str(u["tg_id"]))
        sent = 0
        for user_id in targets:
            try:
                await bot.send_message(int(user_id), text)
                sent += 1
                await asyncio.sleep(0.5)
            except: pass
        await event.reply(f"✅ **Broadcast Done!**\n📤 Sent: `{sent}`", parse_mode='markdown')
