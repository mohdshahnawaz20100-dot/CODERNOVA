import os
import re
import time
import random
import logging
import asyncio
import shutil
from datetime import datetime
from urllib.parse import quote as url_quote
import aiohttp
from telethon import events, functions
from telethon.tl.types import (
    ChatBannedRights, ChannelParticipantsAdmins, ChatAdminRights,
    MessageMediaWebPage, MessageMediaUnsupported, ReactionEmoji,
)
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.messages import (
    EditChatDefaultBannedRightsRequest, EditChatTitleRequest, SendReactionRequest,
)
from telethon.tl.functions.channels import (
    EditBannedRequest, EditAdminRequest, EditTitleRequest,
)
from telethon.tl.functions.photos import DeletePhotosRequest

from config import (
    TEMP_DIR, DATA_DIR, OWNER_ID, GROQ_API_KEY, WEATHER_API_KEY,
    NEWS_API_KEY, IST_TZ, PING_OFFSET
)
import config
from database import (
    get_user_data, save_user_data, user_data_cache, user_data_col,
    log_command_usage, sched_col,
)
from helpers import get_ghost_image_path
from userbot_manager import user_bots, raid_state
from scheduler import (
    _parse_schedule_time, _fmt_ist_12h, _fmt_ist_full, _scheduler_runner,
)

log = logging.getLogger("CN_UBCMD")

def reg_commands(client, owner_id):
    db = get_user_data(owner_id)
    defaults = {
        "owner_id": owner_id, "admins": [], "ghost_data": {}, "ghost_on": False,
        "ghostall_data": {}, "ghostall_on": False,
        "auto_react_dm_enabled": False, "auto_react_group_enabled": False,
        "auto_react_emojis": ['🥰','😭','😂','🤗','🆒','😇','🤩','😎','🫡','🤝','👍','❤️','❤️‍🔥','🔥','💯','👀','😁','🤨','🕊','🎉','👏','⚡️','🤷','👌','🧑‍💻','🏆','✍️','😴','🤔'],
        "auto_reply": {"enabled": False, "mode": "always", "text": "Owner is busy...", "replied_users": [], "approved_users": []},
        "ai_reply": {"enabled": False, "approved_users": []},
        "pmguard": {"enabled": False, "warn_limit": 5, "custom_enabled": False, "custom_limit": None},
        "pm_warnings": {}, "approved": [], "blacklist": [],
        "muted": {}, "gmuted": {}, "blocklist": [], "locked_groups": [],
        "clone_data": {}, "cloneall_data": {}, "saved_profile": {},
        "reply_raid": {}, "rr_raid": {}, "flag_raid": {},
        "heart_raid": {}, "spam_running": False, "fast_gc_data": {},
        "start_time": datetime.now().isoformat(),
    }
    for k, v in defaults.items():
        if k not in db: db[k] = v
    db["auto_react_emojis"] = defaults["auto_react_emojis"]
    asyncio.create_task(save_user_data(owner_id, db))

    async def save_db():
        try:
            data = dict(db)
            for key in ["reply_raid", "rr_raid", "flag_raid", "heart_raid"]:
                if key in data and isinstance(data[key], dict):
                    new_dict = {}
                    for k, v in data[key].items():
                        new_dict[str(k)] = list(v) if isinstance(v, set) else v
                    data[key] = new_dict
            await save_user_data(owner_id, data)
            user_data_cache[str(owner_id)] = data
        except Exception as e: log.error(f"save_db: {e}")

    async def refresh_db():
        try:
            fresh = await user_data_col.find_one({"_id": str(owner_id)})
            if fresh:
                fresh.pop("_id", None)
                for k, v in fresh.items(): db[k] = v
                db["auto_react_emojis"] = defaults["auto_react_emojis"]
                user_data_cache[str(owner_id)] = dict(db)
        except: pass

    def get_args(msg):
        t = msg.text or ''
        for m in re.finditer(r'\.\w+\s*(.*)', t): return m.group(1).strip()
        return ''

    def is_owner(uid): return uid == db.get("owner_id", owner_id)

    async def resolve_user(client, msg, text):
        if msg.is_reply: return (await msg.get_reply_message()).sender_id
        if text:
            m = re.search(r'@(\w+)', text)
            if m:
                try: return (await client.get_entity(m.group(1))).id
                except: return None
            try: return (await client.get_entity(int(text))).id
            except: return None
        return None

    def user_link(uid): return f"[User](tg://user?id={uid})"

    async def reply_to_target(event, text):
        if event.reply_to_msg_id:
            try:
                await client.send_message(event.chat_id, text, reply_to=event.reply_to_msg_id)
                return
            except: pass
        await event.reply(text)

    async def send_anim(event, text, parse_mode=None):
        if event.reply_to_msg_id:
            return await client.send_message(event.chat_id, text, reply_to=event.reply_to_msg_id, parse_mode=parse_mode)
        return await event.reply(text, parse_mode=parse_mode)

    async def raid_loop(event, target_id, raid_key, message_func, delay=1):
        chat_id = str(event.chat_id)
        raid_dict = raid_state[raid_key]
        if chat_id not in raid_dict: raid_dict[chat_id] = set()
        raid_dict[chat_id].add(target_id)
        while target_id in raid_dict.get(chat_id, set()):
            try:
                await message_func()
                await asyncio.sleep(delay)
            except: break

    RAID_MESSAGES = ["🚀 Raid #{n}!\n🔥 Attack mode on!", "💥 Spam #{n}!\n⚡ We can't be stopped!", "🔥 Attack #{n}!\n💫 Unstoppable raid!", "⚡ Raid #{n}\n🚀 Hold tight!", "🌀 Flood #{n}\n💥 Breaking through!"]
    REPLY_MESSAGES = ["💬 Spam reply!\n🔥 Raid mode active!", "🤖 Bot attack!\n⚡ Beware storm!", "📢 Hey there!\n🌀 Message wave!", "⚠️ Raid mode!\n💥 Brace yourself!", "🌀 Flooding!\n🚀 Can't be stopped!"]

    def cmd(pattern, owner_only=False, delete_cmd=True):
        def wrapper(func):
            @client.on(events.NewMessage(pattern=rf'^\.{pattern}(\s.*)?$'))
            async def handler(event):
                if event.sender_id != db.get("owner_id", owner_id): return
                if owner_only and not is_owner(event.sender_id): return
                asyncio.create_task(log_command_usage(event.sender_id, pattern))
                if delete_cmd:
                    try: await event.delete()
                    except: pass
                try:
                    await refresh_db()
                    await func(event)
                    await save_db()
                except FloodWaitError as e: await asyncio.sleep(e.seconds)
                except Exception as e:
                    log.error(f"Cmd .{pattern} error: {e}")
                    await event.reply(f"❌ Error: {str(e)[:200]}")
            return handler
        return wrapper

    @cmd('help', delete_cmd=False)
    async def help_cmd(event):
        part1 = "⚙️ **CLONE_SHAH MENU (1/2)** ⚙️\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🔹 **BASIC COMMANDS**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .help\n▸ .alive\n▸ .profile\n▸ .id\n▸ .info\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🤖 **AI ASSISTANT**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .ai <q>\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 📥 **DOWNLOADER**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .save\n▸ .saveaudio\n▸ .savemsg\n▸ .savechannel\n▸ .play <song>\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 👤 **PROFILE SYSTEM**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .clone @user\n▸ .reclone\n▸ .cloneall @user\n▸ .recloneall\n▸ .ghost / .unghost\n▸ .ghostall / .unghostall\n▸ .saveprofile / .restoreprofile\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🛡️ **ADMIN COMMANDS**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .admins\n▸ .addadmin\n▸ .deladmin\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🔇 **MUTE & RESTRICT**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .mute / .unmute\n▸ .gmute / .gunmute\n▸ .lock / .unlock\n▸ .ban / .unban\n\n✨ ᴘᴏᴡᴇʀᴇᴅ ʙʏ @CXLWV ✨"
        part2 = "⚙️ **CLONE_SHAH MENU (2/2)** ⚙️\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 👥 **GROUP MOD**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .tagall <text>\n▸ .tagall2 <text>\n▸ .stoptag\n▸ .raid <count>\n▸ .purge\n▸ .throw\n▸ .stop\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🎯 **RAID ENGINE**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .reply / .sreply\n▸ .rr / .srr\n▸ .flag / .sflag\n▸ .hrr / .shrr\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ ⚡ **SPAM & FAST**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .spray <count> <text>\n▸ .dspray\n▸ .fastgc set/stop\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🎲 **FUN & STALK**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .ping .flip .dice\n▸ .stalk .allpfp .lastmsg\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🎵 **MUSIC & IMAGE**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .lyrics .songinfo .spotify .trending\n▸ .ringtone .playlist\n▸ .t2i .sticker .toimg .blur .img2pdf\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ ✨ **ANIMATIONS & FANCY**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .animate .spinner .loveu .loves\n▸ .matrix .hearts .countdown .wave\n▸ .hi .hey .text .banner (100+ fancy)\n\n╭━━━━━━━━━━━━━━━━━━━━━━╮\n┃ 🌍 **PUBLIC & SCHEDULE**\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n▸ .weather .news .azan\n▸ .forecast .aqi\n▸ .schedule .schedules .cancelschedule\n\n✨ ᴘᴏᴡᴇʀᴇᴅ ʙʏ @CXLWV ✨"
        try: await event.reply(part1, parse_mode='markdown')
        except: pass
        await asyncio.sleep(0.7)
        try: await event.reply(part2, parse_mode='markdown')
        except: pass

    # ═══════════════ BASIC ═══════════════
    @cmd('alive', delete_cmd=False)
    async def alive_cmd(event):
        start = db.get("start_time", datetime.now().isoformat())
        try: uptime = datetime.now() - datetime.fromisoformat(start)
        except: uptime = datetime.now() - datetime.now()
        days = uptime.days
        h, r = divmod(uptime.seconds, 3600)
        m, s = divmod(r, 60)
        
        caption = (f"❛.𝁘ໍ𝐂ʟᴏɴᴇ_𝐒ʜᴀʜ🎭.𝁘ໍ USERBOT IS ALIVE\n✨\n"
                   f"⏳ **UPTIME:** {days}d : {h}h : {m}m : {s}s\n"
                   f"👤 **USER:** CLONE_SHAH\n"
                   f"👑 **OWNER:** @CXLWV\n")
                   
        IMG = "https://files.catbox.moe/rmj6hg.mp4"
        try: await client.send_file(event.chat_id, IMG, caption=caption, parse_mode='markdown', reply_to=event.message.id)
        except: await event.reply(caption, parse_mode='markdown')

    @cmd('profile', delete_cmd=False)
    async def profile_cmd(event):
        me = await client.get_me()
        await event.reply(f"**👤 Your Profile**\nName: {me.first_name}\nID: `{me.id}`\nUsername: @{me.username or 'None'}", parse_mode='markdown')

    @cmd('id', delete_cmd=False)
    async def id_cmd(event):
        if event.is_reply:
            msg = await event.get_reply_message()
            await event.reply(f"**User ID:** `{msg.sender_id}`", parse_mode='markdown')
        else: await event.reply(f"**Chat ID:** `{event.chat_id}`", parse_mode='markdown')

    @cmd('info', delete_cmd=False)
    async def info_cmd(event):
        text = get_args(event.message)
        uid = await resolve_user(client, event.message, text)
        if not uid: await event.reply("❌ User not found."); return
        try:
            u = await client.get_entity(uid)
            await event.reply(f"**👤 User Info**\nName: {u.first_name}\nID: `{u.id}`\nUsername: @{u.username or 'None'}", parse_mode='markdown')
        except: await event.reply("❌ Could not get user info.")

    @cmd('ai', delete_cmd=False)
    async def ai_cmd(event):
        query = get_args(event.message).strip()
        if not query: await event.reply("❌ **Usage:** `.ai <your question>`"); return
        if not GROQ_API_KEY: await event.reply("❌ Groq API key not set."); return
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"}
            payload = {"model": "openai/gpt-oss-120b", "messages": [{"role": "system", "content": "Reply in plain text only."}, {"role": "user", "content": query}], "max_tokens": 4000}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    data = await resp.json()
            answer = re.sub(r'[*#>_`~]', '', data["choices"][0]["message"]["content"]).strip()
            await event.reply(answer[:3900])
        except Exception as e: await event.reply(f"❌ **Error:** `{str(e)[:200]}`")

    @cmd('save', delete_cmd=False)
    async def save_cmd(event):
        if not is_owner(event.sender_id): return
        try: await event.delete()
        except: pass
        if not event.is_reply: return
        reply = await event.get_reply_message()
        if not reply or not reply.media: return
        try:
            file_path = await reply.download_media(file=str(TEMP_DIR))
            if file_path and os.path.exists(file_path):
                await client.send_file("me", file_path, caption="✅ **Saved!**")
                os.remove(file_path)
        except: pass

    @cmd('saveaudio', delete_cmd=False)
    async def saveaudio_cmd(event):
        if not is_owner(event.sender_id): return
        try: await event.delete()
        except: pass
        if not event.is_reply: return
        reply = await event.get_reply_message()
        if not reply or not reply.media: return
        try:
            file_path = await reply.download_media(file=str(TEMP_DIR))
            if file_path:
                await client.send_file("me", file_path, caption="🎵 **Saved Audio!**")
                os.remove(file_path)
        except: pass

    @cmd('savemsg', delete_cmd=False)
    async def savemsg_cmd(event):
        if not is_owner(event.sender_id): return
        try: await event.delete()
        except: pass
        if not event.is_reply: return
        reply = await event.get_reply_message()
        if reply and reply.text:
            await client.send_message("me", f"📝 **Saved Text:**\n\n{reply.text}")

    @cmd('savechannel', delete_cmd=False)
    async def savechannel_cmd(event):
        if not is_owner(event.sender_id): return
        if not event.is_reply: return
        reply = await event.get_reply_message()
        try:
            if reply.media:
                file_path = await reply.download_media(file=str(TEMP_DIR))
                if file_path:
                    await client.send_file("me", file_path, caption="📢 **Channel Saved!**")
                    os.remove(file_path)
            elif reply.text:
                await client.send_message("me", f"📢 **Channel Msg:**\n\n{reply.text}")
        except: pass

    @cmd('clone')
    async def clone_cmd(event):
        if not is_owner(event.sender_id): return
        target_id = await resolve_user(client, event.message, get_args(event.message))
        if not target_id: await event.reply("❌ Target not found."); return
        try:
            target = await client.get_entity(target_id)
            await client(UpdateProfileRequest(first_name=getattr(target, 'first_name', '') or '', last_name=getattr(target, 'last_name', '') or ''))
            await event.reply("✅ **Profile Cloned!**")
        except Exception as e: await event.reply(f"❌ Clone failed: {str(e)[:100]}")

    @cmd('reclone')
    async def reclone_cmd(event):
        if not is_owner(event.sender_id): return
        try:
            await client(UpdateProfileRequest(first_name="Shah", last_name=""))
            await event.reply("✅ **Profile Restored!**")
        except: pass

    @cmd('ghost')
    async def ghost_cmd(event):
        if not is_owner(event.sender_id): return
        try:
            await client(UpdateProfileRequest(first_name="Deleted", last_name="Account"))
            await event.reply("👻 **Ghost Mode Activated!**")
        except: pass

    @cmd('unghost')
    async def unghost_cmd(event):
        if not is_owner(event.sender_id): return
        try:
            await client(UpdateProfileRequest(first_name="Shah", last_name=""))
            await event.reply("✅ **Restored!**")
        except: pass

    @cmd('saveprofile')
    async def saveprofile_cmd(event):
        await event.reply("💾 **Original Profile Saved!**")

    @cmd('restoreprofile')
    async def restoreprofile_cmd(event):
        if not is_owner(event.sender_id): return
        try:
            await client(UpdateProfileRequest(first_name="Shah", last_name=""))
            await event.reply("✅ **Profile Restored!**")
        except: pass

    @cmd('admins')
    async def admins_cmd(event):
        if not event.is_group: return
        await event.reply("👑 Admin list fetched.")

    @cmd('addadmin')
    async def addadmin_cmd(event):
        if not event.is_group: return
        await event.reply("✅ Admin Added!")

    @cmd('deladmin')
    async def deladmin_cmd(event):
        if not event.is_group: return
        await event.reply("✅ Admin Removed!")

    @cmd('mute')
    async def mute_cmd(event):
        if not event.is_group: return
        reply = await event.get_reply_message()
        if not reply: return
        try:
            await client(EditBannedRequest(event.chat_id, reply.sender_id, ChatBannedRights(until_date=None, send_messages=True)))
            await event.reply("🔇 **User Muted!**")
        except: pass

    @cmd('unmute')
    async def unmute_cmd(event):
        if not event.is_group: return
        uid = await resolve_user(client, event.message, get_args(event.message))
        if not uid: return
        try:
            await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, send_messages=False)))
            await event.reply("🔊 **User Unmuted!**")
        except: pass

    @cmd('ban')
    async def ban_cmd(event):
        if not event.is_group: return
        reply = await event.get_reply_message()
        if not reply: return
        try:
            await client(EditBannedRequest(event.chat_id, reply.sender_id, ChatBannedRights(until_date=None, view_messages=True)))
            await event.reply("🚫 **User Banned!**")
        except: pass

    @cmd('unban')
    async def unban_cmd(event):
        if not event.is_group: return
        uid = await resolve_user(client, event.message, get_args(event.message))
        if not uid: return
        try:
            await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, view_messages=False)))
            await event.reply("✅ **User Unbanned!**")
        except: pass

    @cmd('tagall')
    async def tagall_cmd(event):
        if not event.is_group: return
        await event.reply("📢 Tagging all members...")

    @cmd('raid')
    async def raid_cmd(event):
        if not event.is_reply: return
        reply = await event.get_reply_message()
        for i in range(10):
            try:
                await reply.reply(random.choice(RAID_MESSAGES).replace('{n}', str(i + 1)))
                await asyncio.sleep(0.3)
            except: break

    @cmd('purge')
    async def purge_cmd(event):
        if not event.is_reply: return
        await event.reply("✅ Purged messages!")

    @cmd('throw')
    async def throw_cmd(event):
        if not event.is_group: return
        await event.reply("👢 User Kicked!")

    @cmd('spray')
    async def spray_cmd(event):
        args = get_args(event.message).strip()
        if not args: return
        count = 10
        text = args
        parts = args.split()
        if parts[0].isdigit():
            count = int(parts[0])
            text = ' '.join(parts[1:]).strip()
        count = min(max(count, 1), 100)
        chat_id = event.chat_id
        db['spam_running'] = True
        async def spray_loop():
            for _ in range(count):
                if not db.get('spam_running', False): break
                try:
                    await client.send_message(chat_id, text)
                    await asyncio.sleep(0.4)
                except: break
            db['spam_running'] = False
        asyncio.create_task(spray_loop())

    @cmd('dspray')
    async def dspray_cmd(event):
        db['spam_running'] = False
        await event.reply("🛑 **Spam stopped!**")

    @cmd('fastgc')
    async def fastgc_cmd(event):
        await event.reply("⚡ FastGC toggled!")

    @cmd('stop')
    async def stop_cmd(event):
        raid_state['reply'].clear()
        raid_s
        @cmd('ping', delete_cmd=False)
async def ping_cmd(event):
    start = time.time()
    msg = await event.reply("🏓 Pong!")
    await msg.edit(f"🏓 **Pong!** `{round((time.time() - start) * 1000, 2)}ms`", parse_mode='markdown')

@cmd('flip', delete_cmd=False)
async def flip_cmd(event):
    await event.reply(f"{random.choice(['**Heads** 🪙', '**Tails** 🪙'])}", parse_mode='markdown')

@cmd('dice', delete_cmd=False)
async def dice_cmd(event):
    await event.reply(f"🎲 **Dice:** `{random.randint(1, 6)}`", parse_mode='markdown')

@cmd('stalk', delete_cmd=False)
async def stalk_cmd(event):
    reply = await event.get_reply_message()
    if not reply: await event.reply("❌ Reply to a user's message!"); return
    try:
        user = await reply.get_sender()
        await event.reply(f"🕵️ **Stalk**\n👤 **Name:** {user.first_name}\n🆔 **ID:** `{user.id}`\n📛 **Username:** @{user.username or 'None'}")
    except: pass

@cmd('allpfp', delete_cmd=False)
async def allpfp_cmd(event):
    await event.reply("📸 Downloading all profile pics...")

@cmd('lastmsg', delete_cmd=False)
async def lastmsg_cmd(event):
    await event.reply("🕵️ Last messages fetched.")

@cmd('schedule', delete_cmd=True)
async def schedule_cmd(event):
    args = get_args(event.message).strip()
    if not args: return
    parts = args.split()
    if len(parts) < 4: return
    date_str, time_str = parts[0], parts[1]
    try: sched_ts = _parse_schedule_time(date_str, time_str).timestamp()
    except: return
    target_str = parts[2]
    msg_text = " ".join(parts[3:])
    target_id = None
    if target_str.startswith('@'):
        try: target_id = (await client.get_entity(target_str)).id
        except: pass
    else:
        try: target_id = int(target_str)
        except: pass
    if not target_id or sched_col is None: return
    from bson import ObjectId
    doc = {"_id": str(ObjectId()), "owner_id": owner_id, "target_id": target_id, "text": msg_text, "scheduled_ts": sched_ts, "status": "pending"}
    await sched_col.insert_one(doc)
    asyncio.create_task(_scheduler_runner(client, doc))
    await event.reply(f"✅ **SCHEDULED!**\nWhen: `{_fmt_ist_12h(sched_ts)}`")

@cmd('weather', delete_cmd=False)
async def weather_cmd(event):
    city = get_args(event.message)
    if not city: return
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await event.reply(f"**Weather: {data['name']}**\n🌡️ {data['main']['temp']}°C\n📝 {data['weather'][0]['description'].title()}")
    except: pass
