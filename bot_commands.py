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
            caption = ("✅ **ᴀʟʀᴇᴀᴅʏ ʟᴏɢɢᴇᴅ ɪɴ!**\n"
                       "━━━━━━━━━━━━━━━━━━━━━\n\n"
                       "**🔹 ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅs**\n"
                       "• `/help` — ʜᴇʟᴘ ᴍᴇɴᴜ\n"
                       "• `/status` — ʟᴏɢɪɴ sᴛᴀᴛᴜs\n"
                       "• `/logout` — ʟᴏɢᴏᴜᴛ\n\n"
                       "**💡 ɴᴏᴛᴇ:**\n"
                       "Apna userbot use karne ke liye kisi bhi chat me `.help` bhejo.\n\n"
                       "━━━━━━━━━━━━━━━━━━━━━\n"
                       "✨ **ᴘᴏᴡᴇʀᴇᴅ ʙʏ ᴠɪʟʟᴀɪɴ** 😎 ✨")
        else:
            caption = ("🎉 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴄʟᴏɴᴇx ᴜsᴇʀʙᴏᴛ 🎉\n"
                       "━━━━━━━━━━━━━━━━━━━━━\n\n"
                       "🛑 ʟᴏɢɪɴ sᴛᴇᴘs:\n\n"
                       "🔷  sᴇɴᴅ /ʟᴏɢɪɴ\n\n"
                       "🔷  sᴇɴᴅ ᴘʜᴏɴᴇ ɴᴜᴍʙᴇʀ (ᴡɪᴛʜ ᴄᴏᴜɴᴛʀʏ ᴄᴏᴅᴇ)\n\n"
                       "🔷  sᴇɴᴅ ᴏᴛᴘ (sᴘᴀᴄᴇ ᴋᴇ sᴀᴀᴛʜ)\n\n"
                       "🔷  sᴇɴᴅ 𝟸ғᴀ ᴘᴀssᴡᴏʀᴅ (ɪғ ᴇɴᴀʙʟᴇᴅ)\n\n"
                       "━━━━━━━━━━━━━━━━━━━━━\n"
                       "🔐 ʀᴇᴀᴅʏ? ᴛʏᴘᴇ: /ʟᴏɢɪɴ\n\n"
                       "✨ ᴘᴏᴡᴇʀᴇᴅ ʙʏ ᴠɪʟʟᴀɪɴ 😎 ✨")
        try:
            await event.reply(caption, parse_mode='markdown')
        except Exception:
            pass

    @bot.on(events.NewMessage(pattern='/help'))
    async def help_h(event):
        uid = event.sender_id
        if str(uid) in blocked_users:
            return
        base = ("🛑 ❛.𝁘ໍＣｌｏｎｅ Ｘ🎭.𝁘ໍ Bot\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🔹 **Login:**\n• `/start`\n• `/login`\n• `/logout`\n• `/status`\n\n"
                "🔹 **Userbot:**\nLogin ke baad kisi bhi chat me `.alive` bhejo\n\n")
        if uid == OWNER_ID:
            await event.reply(base + "👑 **Owner:**\n• `/users`\n• `/live`\n• `/remove <tg_id>`\n• `/broadcast <msg>`\n• `/delbroadcast`\n• `/stats`\n• `/block <id>`\n• `/unblock <id>`\n• `/blocked`\n• `/cmdstats`\n• `/userstats <id>`\n• `/cmdusage <cmd>`\n• `/blockcmd <id> <cmd>`\n• `/unblockcmd <id> <cmd>`\n• `/blockedcmds <id>`\n• `/cmdcleanup`\n• `/clearsessions`\n• `/resetusers`\n• `/resetall`\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n✨ **ᴘᴏᴡᴇʀᴇᴅ ʙʏ ᴠɪʟʟᴀɪɴ** 😎", parse_mode='markdown')
        else:
            await event.reply(base + "━━━━━━━━━━━━━━━━━━━━━\n✨ **ᴘᴏᴡᴇʀᴇᴅ ʙʏ ᴠɪʟʟᴀɪɴ** 😎", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/status'))
    async def status_h(event):
        if str(event.sender_id) in blocked_users:
            return
        u = get_user(event.sender_id)
        if u["logged_in"]:
            await event.reply(
                f"✅ **Logged In**\n👤 `{u.get('tg_name','N/A')}`\n"
                f"🆔 `{u.get('tg_id','N/A')}`\n🕐 `{u.get('login_time','N/A')}`",
                parse_mode='markdown')
        else:
            await event.reply("❌ Not logged in. `/login`")

    @bot.on(events.NewMessage(pattern='/users'))
    async def users_h(event):
        if event.sender_id != OWNER_ID:
            await event.reply("❌ Sirf owner.")
            return
        if not all_users_db:
            await event.reply("📭 Koi user nahi.")
            return
        logged = sum(1 for u in users_db.values() if u.get("logged_in"))
        t = (f"👥 **Total: {len(all_users_db)}**\n"
             f"✅ **Logged In: {logged}**\n"
             f"🚫 **Blocked: {len(blocked_users)}**\n"
             + "═" * 25 + "\n\n")
        for i, (uid, info) in enumerate(list(all_users_db.items())[:50], 1):
            is_logged = uid in users_db and users_db[uid].get("logged_in")
            st = "🟢" if is_logged else "🔴"
            if uid in blocked_users:
                st = "🚫"
            t += f"{i}. {st} `{info.get('name','Unknown')}`\n"
            t += f"   🆔 `{uid}`\n"
            t += f"   📛 @{info.get('username','None')}\n"
            t += f"   📅 `{info.get('first_seen','N/A')}`\n\n"
        if len(all_users_db) > 50:
            t += f"\n_...aur {len(all_users_db) - 50}_"
        await event.reply(t, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/stats'))
    async def stats_h(event):
        if event.sender_id != OWNER_ID:
            return
        from userbot_manager import user_bots
        await event.reply(
            f"📊 **Bot Stats**\n"
            f"👥 Total: `{len(all_users_db)}`\n"
            f"✅ Logged: `{len(users_db)}`\n"
            f"🟢 Active: `{len(user_bots)}`\n"
            f"🚫 Blocked: `{len(blocked_users)}`\n"
            f"📊 Cmd Tracked: `{len(command_usage_db)}`",
            parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/block(\s+.*)?$'))
    async def block_h(event):
        if event.sender_id != OWNER_ID:
            return
        from userbot_manager import user_bots
        args = (event.text or "").replace("/block", "").strip()
        if not args and not event.is_reply:
            await event.reply("❌ **Usage:**\n`/block <user_id>`\n`/block @username`\n`/block` (reply)")
            return
        target_id = None
        if event.is_reply:
            msg = await event.get_reply_message()
            target_id = msg.sender_id
        elif args.startswith("@"):
            try:
                u = await bot.get_entity(args)
                target_id = u.id
            except Exception:
                await event.reply(f"❌ `{args}` not found."); return
        else:
            try:
                target_id = int(args.split()[0])
            except Exception:
                await event.reply("❌ Invalid user ID."); return
        if target_id == OWNER_ID:
            await event.reply("❌ Aap khud ko block nahi kar sakte."); return
        target_id = str(target_id)
        if target_id in blocked_users:
            await event.reply(f"⚠️ Ye user already blocked hai.\n🆔 `{target_id}`", parse_mode='markdown'); return
        if target_id in user_bots:
            try:
                await user_bots[target_id].disconnect()
            except Exception:
                pass
            del user_bots[target_id]
        if target_id in users_db:
            users_db[target_id]["logged_in"] = False
            users_db[target_id]["session_string"] = None
            await save_user(target_id, users_db[target_id])
        await block_user_db(target_id)
        await event.reply(f"🚫 **User Blocked!**\n🆔 `{target_id}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/unblock(\s+.*)?$'))
    async def unblock_h(event):
        if event.sender_id != OWNER_ID:
            return
        args = (event.text or "").replace("/unblock", "").strip()
        if not args:
            await event.reply("❌ `/unblock <user_id/@username>`"); return
        target_id = None
        if args.startswith("@"):
            try:
                u = await bot.get_entity(args)
                target_id = u.id
            except Exception:
                await event.reply(f"❌ `{args}` not found."); return
        else:
            try:
                target_id = int(args.split()[0])
            except Exception:
                await event.reply("❌ Invalid user ID."); return
        target_id = str(target_id)
        if target_id not in blocked_users:
            await event.reply(f"⚠️ Ye user blocked nahi hai.\n🆔 `{target_id}`", parse_mode='markdown'); return
        await unblock_user_db(target_id)
        await event.reply(f"✅ **User Unblocked!**\n🆔 `{target_id}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/blocked'))
    async def blocked_h(event):
        if event.sender_id != OWNER_ID:
            return
        if not blocked_users:
            await event.reply("📭 Koi blocked user nahi hai."); return
        text = f"🚫 **Blocked ({len(blocked_users)})**\n\n"
        for i, uid in enumerate(list(blocked_users)[:50], 1):
            text += f"{i}. `{uid}`\n"
        await event.reply(text, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/broadcast(\s+.*)?$'))
    async def bcast_h(event):
        if event.sender_id != OWNER_ID:
            return
        has_reply = event.is_reply
        reply_msg = await event.get_reply_message() if has_reply else None
        text = (event.text or "").replace("/broadcast", "", 1).strip()
        if not text and not has_reply and not event.media:
            await event.reply("❌ **Usage:**\n`/broadcast <message>`")
            return
        targets = set(all_users_db.keys())
        for uid, u in users_db.items():
            if u.get("logged_in"):
                targets.add(str(uid))
                if u.get("tg_id"):
                    targets.add(str(u["tg_id"]))
        sent, failed = 0, 0
        sent_msgs = []
        for user_id in targets:
            try:
                sent_msg = None
                if has_reply and reply_msg:
                    if reply_msg.media:
                        sent_msg = await bot.send_file(int(user_id), reply_msg.media,
                                                       caption=reply_msg.text or "")
                    else:
                        sent_msg = await bot.send_message(int(user_id), reply_msg.text or "")
                elif event.media:
                    sent_msg = await bot.send_file(int(user_id), event.media, caption=text)
                else:
                    sent_msg = await bot.send_message(int(user_id), text)
                if sent_msg:
                    sent_msgs.append({
                        "user_id": int(user_id),
                        "message_id": sent_msg.id,
                        "timestamp": time.time(),
                    })
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"Broadcast to {user_id} failed: {e}")
                failed += 1
        broadcast_history.clear()
        broadcast_history.extend(sent_msgs)
        await event.reply(
            f"✅ **Broadcast Done!**\n📤 Sent: `{sent}`\n❌ Failed: `{failed}`\n"
            f"👥 Total: `{len(targets)}`\n\n💡 Delete: `/delbroadcast`",
            parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/delbroadcast'))
    async def delbroadcast_h(event):
        if event.sender_id != OWNER_ID:
            await event.reply("❌ Sirf owner."); return
        if not broadcast_history:
            await event.reply("📭 Koi recent broadcast nahi hai."); return
        msg = await event.reply(f"🗑️ Deleting broadcast from `{len(broadcast_history)}` users...")
        deleted, failed, too_old = 0, 0, 0
        for entry in list(broadcast_history):
            try:
                age = time.time() - entry["timestamp"]
                if age > 48 * 3600:
                    too_old += 1; continue
                await bot.delete_messages(entry["user_id"], [entry["message_id"]])
                deleted += 1
                await asyncio.sleep(0.3)
            except Exception:
                failed += 1
        broadcast_history.clear()
        await msg.edit(
            f"✅ **Broadcast Deleted!**\n🗑️ Deleted: `{deleted}`\n"
            f"❌ Failed: `{failed}`\n⏰ Too old: `{too_old}`")
