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
    NEWS_API_KEY, IST_TZ,
)
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
        "auto_reply": {
            "enabled": False, "mode": "always",
            "text": "The owner is busy with some personal work at the moment😌Please wait until they are back online🥀",
            "replied_users": [], "approved_users": [],
        },
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
        if k not in db:
            db[k] = v
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
        except Exception as e:
            log.error(f"save_db: {e}")

    async def refresh_db():
        try:
            fresh = await user_data_col.find_one({"_id": str(owner_id)})
            if fresh:
                fresh.pop("_id", None)
                for k, v in fresh.items():
                    db[k] = v
                db["auto_react_emojis"] = defaults["auto_react_emojis"]
                user_data_cache[str(owner_id)] = dict(db)
        except Exception:
            pass

    async def get_fresh_data(key):
        await refresh_db()
        return db.get(key)

    def get_args(msg):
        t = msg.text or ''
        for m in re.finditer(r'\.\w+\s*(.*)', t):
            return m.group(1).strip()
        return ''

    def is_owner(uid):
        return uid == db.get("owner_id", owner_id)

    async def resolve_user(client, msg, text):
        if msg.is_reply:
            return (await msg.get_reply_message()).sender_id
        if text:
            m = re.search(r'@(\w+)', text)
            if m:
                try:
                    u = await client.get_entity(m.group(1))
                    return u.id
                except Exception:
                    return None
            try:
                u = await client.get_entity(int(text))
                return u.id
            except Exception:
                return None
        return None

    def user_link(uid):
        return f"[User](tg://user?id={uid})"

    async def reply_to_target(event, text):
        if event.reply_to_msg_id:
            try:
                await client.send_message(event.chat_id, text, reply_to=event.reply_to_msg_id)
                return
            except Exception:
                pass
        await event.reply(text)

    async def send_anim(event, text, parse_mode=None):
        if event.reply_to_msg_id:
            return await client.send_message(event.chat_id, text, reply_to=event.reply_to_msg_id, parse_mode=parse_mode)
        return await event.reply(text, parse_mode=parse_mode)

    async def raid_loop(event, target_id, raid_key, message_func, delay=1):
        chat_id = str(event.chat_id)
        raid_dict = raid_state[raid_key]
        if chat_id not in raid_dict:
            raid_dict[chat_id] = set()
        raid_dict[chat_id].add(target_id)
        while target_id in raid_dict.get(chat_id, set()):
            try:
                await message_func()
                await asyncio.sleep(delay)
            except Exception:
                break

    RAID_MESSAGES = [
        "🚀 Raid #{n}!\n🔥 Attack mode on, brace yourself!",
        "💥 Spam #{n}!\n⚡ We can't be stopped now!",
        "🔥 Attack #{n}!\n💫 Unstoppable raid force incoming!",
        "⚡ Raid #{n}\n🚀 Here we go again, hold tight!",
        "🌀 Flood #{n}\n💥 Breaking through everything!",
    ]
    REPLY_MESSAGES = [
        "💬 Spam reply!\n🔥 Raid mode is active!",
        "🤖 Bot attack!\n⚡ Beware the incoming storm!",
    ]

    def cmd(pattern, owner_only=False, delete_cmd=True):
        def wrapper(func):
            @client.on(events.NewMessage(pattern=rf'^\.{pattern}(\s.*)?$'))
            async def handler(event):
                if event.sender_id != db.get("owner_id", owner_id): return
                if owner_only and not is_owner(event.sender_id): return
                asyncio.create_task(log_command_usage(event.sender_id, pattern))
                if delete_cmd:
                    try: await event.delete()
                    except Exception: pass
                try:
                    await refresh_db()
                    await func(event)
                    await save_db()
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    log.error(f"Cmd .{pattern} error: {e}")
                    await event.reply(f"❌ Error: {str(e)[:200]}")
            return handler
        return wrapper

    @cmd('help', delete_cmd=False)
    async def help_cmd(event):
        part1 = "⚙️ **USERBOT MENU**\n\n▸ .help\n▸ .alive\n▸ .clone\n▸ .ghost\n▸ .admin\n▸ .mute\n▸ .tagall\n▸ .schedule\n▸ .weather\n▸ .t2i\n▸ .ai"
        try: await event.reply(part1, parse_mode='markdown')
        except Exception: pass

    @cmd('alive', delete_cmd=False)
    async def alive_cmd(event):
        start = db.get("start_time", datetime.now().isoformat())
        try: uptime = datetime.now() - datetime.fromisoformat(start)
        except Exception: uptime = datetime.now() - datetime.now()
        days = uptime.days
        h, r = divmod(uptime.seconds, 3600)
        m, s = divmod(r, 60)
        me = await client.get_me()
        caption = (f"❛.𝁘ໍ𝗖lØn𝛜X🎭.𝁘ໍ USERBOT IS ALIVE\n✨\n⏳ **UPTIME:** {days}d : {h}h : {m}m : {s}s\n👤 **USER:** {me.first_name or 'User'}\n👑 **OWNER:** @iVILLAINi\n")
        IMG = "https://files.catbox.moe/rmj6hg.mp4"
        try: await client.send_file(event.chat_id, IMG, caption=caption, parse_mode='markdown', reply_to=event.message.id)
        except Exception: await event.reply(caption, parse_mode='markdown')

    @cmd('ai', delete_cmd=False)
    async def ai_cmd(event):
        query = get_args(event.message).strip()
        reply_msg = await event.get_reply_message() if event.is_reply else None
        reply_text = ""
        if reply_msg:
            reply_text = (reply_msg.text or "").strip()
            if not reply_text and hasattr(reply_msg, 'caption'): reply_text = (reply_msg.caption or "").strip()
        if not query and not reply_text:
            await event.reply("❌ **Usage:** `.ai <your question>`\nExample: `.ai What is Python?`"); return
        if not GROQ_API_KEY:
            await event.reply("❌ Groq API key not set."); return
        try:
            final_prompt = query
            if reply_text and query: final_prompt = f"Message: {reply_text}\n\nQuestion: {query}"
            elif reply_text and not query: final_prompt = f"Explain this:\n\n{reply_text}"
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"}
            payload = {"model": "openai/gpt-oss-120b", "messages": [{"role": "system", "content": "You are helpful. Reply in plain text only."}, {"role": "user", "content": final_prompt}], "max_tokens": 8000, "temperature": 0.3}
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        await event.reply(f"❌ **Groq API Error:** `{resp.status}`\n`{error_text[:200]}`"); return
                    data = await resp.json()
            answer = data["choices"][0]["message"]["content"]
            answer = re.sub(r'[*#>_`~]', '', answer).strip()
            reply_target = event.reply_to_msg_id if event.is_reply else event.message.id
            chunks = [answer[i:i+3900] for i in range(0, len(answer), 3900)]
            for i, chunk in enumerate(chunks):
                if i == 0: await client.send_message(event.chat_id, chunk, reply_to=reply_target)
                else: await client.send_message(event.chat_id, chunk)
                if i < len(chunks) - 1: await asyncio.sleep(0.6)
        except Exception as e:
            await event.reply(f"❌ **Error:** `{str(e)[:200]}`")

    @cmd('save', delete_cmd=False)
    async def save_cmd(event):
        if not is_owner(event.sender_id): return
        try: await event.delete()
        except Exception: pass
        if not event.is_reply: return
        reply = await event.get_reply_message()
        if not reply or not reply.media: return
        try:
            file_path = await reply.download_media(file=str(TEMP_DIR))
            if file_path:
                await client.send_file("me", file_path, caption="✅ **Saved!**", parse_mode='markdown')
                os.remove(file_path)
        except Exception as e: log.error(f"Save error: {e}")

    @cmd('clone')
    async def clone_cmd(event):
        if not is_owner(event.sender_id): return
        text = get_args(event.message)
        target_id = await resolve_user(client, event.message, text)
        if not target_id: await event.reply("❌ Target not found."); return
        try:
            target = await client.get_entity(target_id)
            await client(UpdateProfileRequest(first_name=getattr(target, 'first_name', '') or '', last_name=getattr(target, 'last_name', '') or ''))
            await event.reply("✅ **Profile Cloned!**")
        except Exception as e: await event.reply(f"❌ Clone failed: {str(e)[:100]}")

    @cmd('ghost')
    async def ghost_cmd(event):
        if not is_owner(event.sender_id): return
        try:
            await client(UpdateProfileRequest(first_name="Deleted", last_name="Account"))
            await event.reply("👻 **Ghost Mode Activated!**")
        except Exception as e: await event.reply(f"❌ {str(e)[:100]}")

    @cmd('ban')
    async def ban_cmd(event):
        if not event.is_group: return
        uid = await resolve_user(client, event.message, get_args(event.message))
        if not uid: return
        try:
            await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, view_messages=True)))
            await event.reply("🚫 **User Banned!**")
        except Exception as e: await event.reply(f"❌ {str(e)[:150]}")

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
                except Exception: break
            db['spam_running'] = False
        asyncio.create_task(spray_loop())

    @cmd('stop')
    async def stop_cmd(event):
        raid_state['reply'].clear()
        raid_state['rr'].clear()
        raid_state['flag'].clear()
        raid_state['hrr'].clear()
        db['spam_running'] = False
        db['fast_gc_data'].clear()
        db['tagall_running'] = False
        await save_db()
        await event.reply("🛑 **All loops stopped!**")

    @cmd('schedule', delete_cmd=True)
    async def schedule_cmd(event):
        args = get_args(event.message).strip()
        if not args:
            await event.reply("**Format:** `.schedule YYYY-MM-DD HH:MM <target> <msg>`"); return
        parts = args.split()
        if len(parts) < 4: return
        date_str, time_str = parts[0], parts[1]
        try: sched_ts = _parse_schedule_time(date_str, time_str).timestamp()
        except Exception as e: await event.reply(f"❌ **Invalid date** `{e}`"); return
        target_str = parts[2]
        msg_text = " ".join(parts[3:])
        target_id = None
        if target_str.startswith('@'):
            try: target_id = (await client.get_entity(target_str)).id
            except: pass
        else:
            try: target_id = int(target_str)
            except: pass
        if not target_id: return
        if sched_col is None: return
        from bson import ObjectId
        doc = {"_id": str(ObjectId()), "owner_id": owner_id, "target_id": target_id, "text": msg_text, "reply_to_msg_id": None, "comment_to": None, "scheduled_ts": sched_ts, "scheduled_str": _fmt_ist_full(sched_ts), "scheduled_short": _fmt_ist_12h(sched_ts), "chat_id": event.chat_id, "created_at": time.time(), "status": "pending"}
        await sched_col.insert_one(doc)
        asyncio.create_task(_scheduler_runner(client, doc))
        await event.reply(f"✅ **SCHEDULED!**\nID: `{doc['_id'][:8]}`\nWhen: `{doc['scheduled_short']}`")

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
                        await event.reply(f"**Weather: {data['name']}**\n🌡️ Temp: {data['main']['temp']}°C\n📝 {data['weather'][0]['description'].title()}")
        except Exception: pass

    @client.on(events.NewMessage(func=lambda e: e.is_private and not e.out))
    async def auto_reply_handler(event):
        try:
            uid = event.sender_id
            if uid == db.get('owner_id', owner_id): return
            ar = db.get('auto_reply', {})
            if ar.get('enabled', False):
                await asyncio.sleep(0.5)
                await event.reply(ar.get('text', 'Owner is busy.'))
        except Exception: pass
