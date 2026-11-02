import time
import logging
import asyncio
from datetime import datetime
from telethon import events
from config import OWNER_ID, CLEANUP_DAYS
from database import (
    all_users_db, users_db, blocked_users, command_usage_db,
    block_user_db, unblock_user_db, get_user, save_user,
    command_blocked_db, users_col, all_users_col, cmd_usage_col,
    cmd_blocked_col, track_start,
)

log = logging.getLogger("CN_BOTCMD")
broadcast_history = []


def register_bot_commands(bot):
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_h(event):
        uid = event.sender_id
        if str(uid) in blocked_users:
            return
        u = get_user(uid)
        try:
            s = await event.get_sender()
            name = ((s.first_name or "") + (" " + s.last_name if getattr(s, 'last_name', None) else "")).strip() or "Unknown"
            await track_start(uid, name, s.username or "None")
        except Exception:
            pass
            
        if u["logged_in"]:
            caption = "✅ **ᴀʟʀᴇᴀᴅʏ ʟᴏɢɢᴇᴅ ɪɴ!**\n\n`/help` — ʜᴇʟᴘ ᴍᴇɴᴜ\n`/status` — ʟᴏɢɪɴ sᴛᴀᴛᴜs\n`/logout` — ʟᴏɢᴏᴜᴛ\n\nApna userbot use karne ke liye kisi bhi chat me `.help` bhejo."
        else:
            caption = "🎉 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴄʟᴏɴᴇx ᴜsᴇʀʙᴏᴛ 🎉\n\n🛑 ʟᴏɢɪɴ sᴛᴇᴘs:\n🔷 sᴇɴᴅ /ʟᴏɢɪɴ\n🔷 sᴇɴᴅ ᴘʜᴏɴᴇ ɴᴜᴍʙᴇʀ\n🔷 sᴇɴᴅ ᴏᴛᴘ (sᴘᴀᴄᴇ ᴋᴇ sᴀᴀᴛʜ)\n\n🔐 ᴛʏᴘᴇ: /ʟᴏɢɪɴ"
        await event.reply(caption, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/help'))
    async def help_h(event):
        uid = event.sender_id
        if str(uid) in blocked_users:
            return
        base = "🛑 **Bot Commands**\n\n🔹 **Login:**\n• `/start`\n• `/login`\n• `/logout`\n• `/status`\n\n🔹 **Userbot:**\nLogin ke baad kisi bhi chat me `.alive` bhejo\n\n"
        if uid == OWNER_ID:
            await event.reply(base + "👑 **Owner:**\n• `/users`\n• `/live`\n• `/broadcast`\n• `/stats`\n• `/block`\n• `/unblock`\n• `/resetall`", parse_mode='markdown')
        else:
            await event.reply(base, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/status'))
    async def status_h(event):
        u = get_user(event.sender_id)
        if u["logged_in"]:
            await event.reply(f"✅ **Logged In**\n👤 `{u.get('tg_name','N/A')}`\n🆔 `{u.get('tg_id','N/A')}`", parse_mode='markdown')
        else:
            await event.reply("❌ Not logged in. `/login`")

    @bot.on(events.NewMessage(pattern='/users'))
    async def users_h(event):
        if event.sender_id != OWNER_ID: return
        if not all_users_db:
            await event.reply("📭 Koi user nahi.")
            return
        logged = sum(1 for u in users_db.values() if u.get("logged_in"))
        t = f"👥 **Total: {len(all_users_db)}**\n✅ **Logged In: {logged}**\n🚫 **Blocked: {len(blocked_users)}**\n\n"
        for i, (uid, info) in enumerate(list(all_users_db.items())[:50], 1):
            st = "🟢" if uid in users_db and users_db[uid].get("logged_in") else "🔴"
            if uid in blocked_users: st = "🚫"
            t += f"{i}. {st} `{info.get('name','Unknown')}`\n   🆔 `{uid}`\n\n"
        await event.reply(t, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/stats'))
    async def stats_h(event):
        if event.sender_id != OWNER_ID: return
        from userbot_manager import user_bots
        await event.reply(f"📊 **Stats**\n👥 Total: `{len(all_users_db)}`\n✅ Logged: `{len(users_db)}`\n🟢 Active: `{len(user_bots)}`\n🚫 Blocked: `{len(blocked_users)}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/block(\s+.*)?$'))
    async def block_h(event):
        if event.sender_id != OWNER_ID: return
        from userbot_manager import user_bots
        args = (event.text or "").replace("/block", "").strip()
        if not args and not event.is_reply:
            await event.reply("❌ `/block <user_id>`")
            return
        target_id = None
        if event.is_reply:
            target_id = (await event.get_reply_message()).sender_id
        else:
            try: target_id = int(args.split()[0])
            except: await event.reply("❌ Invalid ID"); return
        
        target_id = str(target_id)
        if target_id in user_bots:
            try: await user_bots[target_id].disconnect()
            except: pass
            del user_bots[target_id]
            
        await block_user_db(target_id)
        await event.reply(f"🚫 **User Blocked!**\n🆔 `{target_id}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/unblock(\s+.*)?$'))
    async def unblock_h(event):
        if event.sender_id != OWNER_ID: return
        args = (event.text or "").replace("/unblock", "").strip()
        if not args:
            await event.reply("❌ `/unblock <user_id>`"); return
        try: target_id = str(int(args.split()[0]))
        except: await event.reply("❌ Invalid ID"); return
        
        await unblock_user_db(target_id)
        await event.reply(f"✅ **User Unblocked!**\n🆔 `{target_id}`", parse_mode='markdown')
