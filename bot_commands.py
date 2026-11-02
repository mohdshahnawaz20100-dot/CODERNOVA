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
        START_MEDIA = "https://files.catbox.moe/35bl05.mp4"
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
            await bot.send_file(event.chat_id, START_MEDIA, caption=caption,
                                parse_mode='markdown', supports_streaming=True)
        except Exception:
            try:
                await bot.send_file(event.chat_id, START_MEDIA, caption=caption)
            except Exception:
                await event.reply(caption, parse_mode='markdown')

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

    @bot.on(events.NewMessage(pattern='/live'))
    async def live_h(event):
        if event.sender_id != OWNER_ID:
            await event.reply("❌ Sirf owner.")
            return
        if not all_users_db and not users_db:
            await event.reply("📭 Koi user nahi.")
            return
        from userbot_manager import user_bots
        all_ids = set(all_users_db.keys()) | set(users_db.keys())
        active, logged_off, started_only, offline = [], [], [], []
        for uid in all_ids:
            u = users_db.get(uid, {})
            info = all_users_db.get(uid, {})
            name = u.get("tg_name") or info.get("name") or "Unknown"
            tg_id = u.get("tg_id") or info.get("tg_id") or uid
            username = u.get("tg_username") or info.get("username") or "None"
            first_seen = info.get("first_seen", "N/A")
            is_logged = u.get("logged_in", False)
            is_running = uid in user_bots
            has_start = uid in all_users_db
            entry = {"name": name, "tg_id": tg_id, "username": username, "first_seen": first_seen}
            if is_running:
                active.append(entry)
            elif is_logged:
                logged_off.append(entry)
            elif has_start and not is_logged:
                started_only.append(entry)
            else:
                offline.append(entry)

        def render_list(title, items, icon):
            if not items:
                return ""
            out = f"{icon} **{title} ({len(items)})**\n\n"
            for i, info in enumerate(items, 1):
                out += f"{i}. 👤 `{info['name']}`\n"
                out += f"   🆔 `{info['tg_id']}`\n"
                out += f"   📛 @{info['username']}\n"
                out += f"   📅 `{info['first_seen']}`\n\n"
            return out + "─" * 25 + "\n\n"

        text = f"📡 **LIVE STATUS**\n" + "═" * 25 + "\n\n"
        text += render_list("ACTIVE (Userbot Running)", active, "🟢")
        text += render_list("LOGGED IN (Userbot Off)", logged_off, "🟡")
        text += render_list("STARTED ONLY (Not Logged In)", started_only, "🔵")
        text += render_list("OFFLINE / SESSION REMOVED", offline, "🔴")
        text += (f"━━━━━━━━━━━━━━━━━━\n"
                 f"📊 **Summary**\n"
                 f"🟢 Active: `{len(active)}`\n"
                 f"🟡 Logged (off): `{len(logged_off)}`\n"
                 f"🔵 Started only: `{len(started_only)}`\n"
                 f"🔴 Offline: `{len(offline)}`\n"
                 f"🚫 Blocked: `{len(blocked_users)}`")
        await event.reply(text, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/remove(\s+.*)?$'))
    async def remove_h(event):
        if event.sender_id != OWNER_ID:
            await event.reply("❌ Sirf owner.")
            return
        from userbot_manager import user_bots
        args = (event.text or "").replace("/remove", "").strip()
        if not args:
            await event.reply("❌ `/remove <tg_id>`")
            return
        t = args.split()[0]
        f = None
        for uid, u in users_db.items():
            if str(u.get("tg_id")) == str(t) or uid == str(t):
                f = uid; break
        if not f:
            await event.reply(f"❌ `{t}` not found.")
            return
        n = users_db[f].get("tg_name", "Unknown")
        if f in user_bots:
            try:
                await user_bots[f].disconnect()
            except Exception:
                pass
            del user_bots[f]
        try:
            if users_col is not None:
                await users_col.delete_one({"_id": str(f)})
        except Exception:
            pass
        del users_db[f]
        await event.reply(f"✅ **Removed!**\n👤 `{n}`\n🆔 `{t}`", parse_mode='markdown')
        try:
            await bot.send_message(int(f), "⚠️ Access removed. `/login` dobara.")
        except Exception:
            pass

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

    @bot.on(events.NewMessage(pattern='/cmdstats'))
    async def cmdstats_h(event):
        if event.sender_id != OWNER_ID:
            return
        cmd_totals = {}
        user_totals = {}
        for uid, data in command_usage_db.items():
            cmds = data.get("commands", {}) if isinstance(data, dict) else data
            for cmd_name, count in cmds.items():
                cmd_totals[cmd_name] = cmd_totals.get(cmd_name, 0) + count
                user_totals[uid] = user_totals.get(uid, 0) + count
        if not cmd_totals:
            await event.reply("📭 Abhi tak koi command use nahi hui.")
            return
        top_cmds = sorted(cmd_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        top_users = sorted(user_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        text = f"📊 **COMMAND STATS**\n" + "═" * 25 + "\n\n"
        text += "🔥 **Top 10 Commands:**\n\n"
        for i, (cmd_name, count) in enumerate(top_cmds, 1):
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"**{i}.**"
            text += f"{medal} `.{cmd_name}` — **{count}** times\n"
        text += "\n" + "─" * 25 + "\n\n"
        text += "👥 **Top 10 Users:**\n\n"
        for i, (uid, count) in enumerate(top_users, 1):
            name = "Unknown"
            try:
                u = await bot.get_entity(int(uid))
                name = ((u.first_name or "") + (" " + u.last_name if getattr(u, 'last_name', None) else "")).strip() or "Unknown"
            except Exception:
                pass
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"**{i}.**"
            text += f"{medal} `{name}` (`{uid}`) — **{count}** commands\n"
        text += f"\n📌 **Total Commands Used:** `{sum(cmd_totals.values())}`\n"
        text += f"👤 **Total Users Tracked:** `{len(command_usage_db)}`"
        await event.reply(text, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/userstats(\s+.*)?$'))
    async def userstats_h(event):
        if event.sender_id != OWNER_ID:
            return
        args = (event.text or "").replace("/userstats", "").strip()
        if not args:
            await event.reply("❌ `/userstats <user_id>`"); return
        uid = args.split()[0]
        data = command_usage_db.get(uid, {})
        cmds = data.get("commands", {}) if isinstance(data, dict) else data
        if not cmds:
            await event.reply(f"📭 `{uid}` ne koi command use nahi ki."); return
        name = "Unknown"
        try:
            u = await bot.get_entity(int(uid))
            name = ((u.first_name or "") + (" " + u.last_name if getattr(u, 'last_name', None) else "")).strip() or "Unknown"
        except Exception:
            pass
        sorted_cmds = sorted(cmds.items(), key=lambda x: x[1], reverse=True)
        total = sum(cmds.values())
        text = (f"👤 **User:** `{name}`\n🆔 **ID:** `{uid}`\n"
                f"📊 **Total:** `{total}` commands\n" + "═" * 25 + "\n\n")
        for i, (cmd_name, count) in enumerate(sorted_cmds, 1):
            text += f"**{i}.** `.{cmd_name}` — **{count}** times\n"
        blocked = command_blocked_db.get(uid, [])
        if blocked:
            text += "\n🚫 **Blocked Commands:**\n"
            for c in blocked:
                text += f"• `.{c}`\n"
        await event.reply(text, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/cmdusage(\s+.*)?$'))
    async def cmdusage_h(event):
        if event.sender_id != OWNER_ID:
            return
        args = (event.text or "").replace("/cmdusage", "").strip()
        if not args:
            await event.reply("❌ `/cmdusage <command>`\nExample: `/cmdusage clone`"); return
        cmd_name = args.split()[0].lstrip('.')
        users_used = []
        for uid, data in command_usage_db.items():
            cmds = data.get("commands", {}) if isinstance(data, dict) else data
            if cmd_name in cmds:
                users_used.append((uid, cmds[cmd_name]))
        if not users_used:
            await event.reply(f"📭 `.{cmd_name}` koi bhi use nahi kiya."); return
        users_used.sort(key=lambda x: x[1], reverse=True)
        total = sum(c for _, c in users_used)
        text = (f"📌 **Command:** `.{cmd_name}`\n📊 **Total Uses:** `{total}`\n"
                f"👥 **Users:** `{len(users_used)}`\n" + "═" * 25 + "\n\n")
        for i, (uid, count) in enumerate(users_used[:20], 1):
            name = "Unknown"
            try:
                u = await bot.get_entity(int(uid))
                name = ((u.first_name or "") + (" " + u.last_name if getattr(u, 'last_name', None) else "")).strip() or "Unknown"
            except Exception:
                pass
            text += f"**{i}.** `{name}` (`{uid}`) — **{count}** times\n"
        await event.reply(text, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/blockcmd(\s+.*)?$'))
    async def blockcmd_h(event):
        if event.sender_id != OWNER_ID:
            return
        args = (event.text or "").replace("/blockcmd", "").strip()
        if not args or len(args.split()) < 2:
            await event.reply("❌ **Usage:**\n`/blockcmd <user_id> <command>`"); return
        parts = args.split()
        uid, c = parts[0], parts[1].lstrip('.')
        if uid not in command_blocked_db:
            command_blocked_db[uid] = []
        if c not in command_blocked_db[uid]:
            command_blocked_db[uid].append(c)
        if cmd_blocked_col is not None:
            await cmd_blocked_col.update_one(
                {"_id": uid},
                {"$set": {"commands": command_blocked_db[uid]}},
                upsert=True)
        await event.reply(f"🚫 **Command Blocked!**\n🆔 `{uid}`\n📌 `.{c}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/unblockcmd(\s+.*)?$'))
    async def unblockcmd_h(event):
        if event.sender_id != OWNER_ID:
            return
        args = (event.text or "").replace("/unblockcmd", "").strip()
        if not args or len(args.split()) < 2:
            await event.reply("❌ **Usage:**\n`/unblockcmd <user_id> <command>`"); return
        parts = args.split()
        uid, c = parts[0], parts[1].lstrip('.')
        if uid in command_blocked_db and c in command_blocked_db[uid]:
            command_blocked_db[uid].remove(c)
            if cmd_blocked_col is not None:
                await cmd_blocked_col.update_one(
                    {"_id": uid},
                    {"$set": {"commands": command_blocked_db[uid]}},
                    upsert=True)
        await event.reply(f"✅ **Command Unblocked!**\n🆔 `{uid}`\n📌 `.{c}`", parse_mode='markdown')

    @bot.on(events.NewMessage(pattern=r'^/blockedcmds(\s+.*)?$'))
    async def blockedcmds_h(event):
        if event.sender_id != OWNER_ID:
            return
        args = (event.text or "").replace("/blockedcmds", "").strip()
        if not args:
            await event.reply("❌ `/blockedcmds <user_id>`"); return
        uid = args.split()[0]
        cmds = command_blocked_db.get(uid, [])
        if not cmds:
            await event.reply(f"📭 `{uid}` ke liye koi command blocked nahi hai."); return
        text = f"🚫 **Blocked Commands for `{uid}`**\n" + "═" * 25 + "\n\n"
        for i, c in enumerate(cmds, 1):
            text += f"**{i}.** `.{c}`\n"
        await event.reply(text, parse_mode='markdown')

    @bot.on(events.NewMessage(pattern='/cmdcleanup'))
    async def cmdcleanup_h(event):
        if event.sender_id != OWNER_ID:
            return
        if cmd_usage_col is None:
            await event.reply("❌ MongoDB connected nahi hai."); return
        msg = await event.reply("🧹 Cleaning up old command logs...")
        try:
            cutoff_time = time.time() - (CLEANUP_DAYS * 24 * 60 * 60)
            result = await cmd_usage_col.delete_many({"last_update": {"$lt": cutoff_time}})
            await msg.edit(f"✅ **Cleanup Done!**\n🗑️ Deleted: `{result.deleted_count}` records")
        except Exception as e:
            await msg.edit(f"❌ Error: `{str(e)[:200]}`")

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
        try:
            await bot.send_message(int(target_id), "🚫 Aapko block kar diya gaya hai.")
        except Exception:
            pass

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
        try:
            await bot.send_message(int(target_id), "✅ Aapko unblock kar diya gaya hai.")
        except Exception:
            pass

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

    @bot.on(events.NewMessage(pattern='/clearsessions'))
    async def clear_sessions_h(event):
        if event.sender_id != OWNER_ID:
            return
        from userbot_manager import user_bots
        if users_col is None:
            await event.reply("❌ No DB"); return
        try:
            for uid in list(user_bots.keys()):
                try:
                    await user_bots[uid].disconnect()
                except Exception:
                    pass
                del user_bots[uid]
            await users_col.delete_many({})
            users_db.clear()
            await event.reply("✅ All sessions cleared!")
        except Exception as e:
            await event.reply(f"❌ {str(e)[:200]}")

    @bot.on(events.NewMessage(pattern='/resetusers'))
    async def resetusers_h(event):
        if event.sender_id != OWNER_ID:
            return
        if all_users_col is None:
            await event.reply("❌ No DB"); return
        try:
            await all_users_col.delete_many({})
            all_users_db.clear()
            await event.reply("✅ All users reset!")
        except Exception as e:
            await event.reply(f"❌ {str(e)[:200]}")

    @bot.on(events.NewMessage(pattern='/resetall'))
    async def resetall_h(event):
        if event.sender_id != OWNER_ID:
            return
        from userbot_manager import user_bots
        from database import user_data_cache
        try:
            for uid in list(user_bots.keys()):
                try:
                    await user_bots[uid].disconnect()
                except Exception:
                    pass
                del user_bots[uid]
            if users_col is not None:
                await users_col.delete_many({})
            if all_users_col is not None:
                await all_users_col.delete_many({})
            users_db.clear()
            all_users_db.clear()
            user_data_cache.clear()
            broadcast_history.clear()
            await event.reply("✅ **FULL RESET DONE!**")
        except Exception as e:
            await event.reply(f"❌ {str(e)[:200]}")
