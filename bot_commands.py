from database import user_data_colimport os
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
    MessageMediaWebPage, MessageMediaUnsupported,
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
from telethon.tl.types import ReactionEmoji

from config import (
    TEMP_DIR, DATA_DIR, OWNER_ID, GROQ_API_KEY, WEATHER_API_KEY,
    NEWS_API_KEY, IST_TZ,
)
from database import (
    get_user_data, save_user_data, user_data_cache, user_data_col,
    log_command_usage,
)
from helpers import get_ghost_image_path
from userbot_manager import user_bots, raid_state
from scheduler import (
    _parse_schedule_time, _fmt_ist_12h, _fmt_ist_full,
    _scheduler_runner,
)
from database import sched_col

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
    if "warn_limit" not in db.get("pmguard", {}):
        db["pmguard"]["warn_limit"] = 5
    if "custom_enabled" not in db.get("pmguard", {}):
        db["pmguard"]["custom_enabled"] = False
    if "custom_limit" not in db.get("pmguard", {}):
        db["pmguard"]["custom_limit"] = None
    if "approved_users" not in db.get("auto_reply", {}):
        db["auto_reply"]["approved_users"] = []
    if "ai_reply" not in db:
        db["ai_reply"] = {"enabled": False, "approved_users": []}
    asyncio.create_task(save_user_data(owner_id, db))

    # ─── Helpers ───
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
        except Exception as e:
            log.warning(f"refresh_db: {e}")

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
            return await client.send_message(
                event.chat_id, text, reply_to=event.reply_to_msg_id, parse_mode=parse_mode)
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

    # ─── Constants ───
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
        "📢 Hey there!\n🌀 Message wave incoming!",
        "⚠️ Raid mode!\n💥 Brace yourself, it's raining!",
        "🌀 Flooding the chat!\n🚀 Can't be stopped!",
    ]
    SPAM_EMOJIS = ['🌟', '✨', '🔥', '💥', '⚡', '🌀', '🚀', '🎯', '💫', '⭐']
    DEFAULT_SPAM_TEXTS = [
        "🔥 Spam attack!", "🚀 Flooding the chat!", "💥 Here comes the spam!",
        "🌀 Spam mode activated!", "⚡ Lightning spam!", "🎯 Target acquired!",
        "💫 Spam spam spam!", "🌟 Spam with style!", "✨ Spam is life!",
        "🔥 Spam till you drop!",
    ]

    # ─── Command decorator ───
    def cmd(pattern, owner_only=False, delete_cmd=True):
        def wrapper(func):
            @client.on(events.NewMessage(pattern=rf'^\.{pattern}(\s.*)?$'))
            async def handler(event):
                if event.sender_id != db.get("owner_id", owner_id):
                    return
                if owner_only and not is_owner(event.sender_id):
                    return
                asyncio.create_task(log_command_usage(event.sender_id, pattern))
                if delete_cmd:
                    try:
                        await event.delete()
                    except Exception:
                        pass
                try:
                    await refresh_db()
                    await func(event)
                    await save_db()
                except FloodWaitError as e:
                    log.warning(f"Flood wait {e.seconds}s")
                    await event.reply(f"⏳ Flood wait {e.seconds} sec...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    log.error(f"Cmd .{pattern} error: {e}")
                    await event.reply(f"❌ Error: {str(e)[:200]}")
            return handler
        return wrapper

    # ═══════════════ HELP (2 PARTS) ═══════════════
    @cmd('help', delete_cmd=False)
    async def help_cmd(event):
        part1 = """╭━━━━━━━━━━━━━━━━━━━━╮
⚙️ 𝐔𝐒𝐄𝐑𝐁𝐎𝐓 𝐌𝐄𝐍𝐔 (𝟏/𝟐) ⚙️
╰━━━━━━━━━━━━━━━━━━━━╯

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🔹 𝐁𝐀𝐒𝐈𝐂 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .help — Show menu
▸ .alive — Check status
▸ .profile — Your profile
▸ .id — Get ID
▸ .info — Get user info

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🤖 𝐀𝐈 𝐀𝐒𝐒𝐈𝐒𝐓𝐀𝐍𝐓
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .ai <question> — Ask anything to AI

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 📥 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃𝐄𝐑
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .save — Save media silently (reply)
▸ .saveaudio — Extract audio from video (reply)
▸ .savemsg — Save text silently (reply)
▸ .savechannel <link> — Save channel post
▸ .play <song> — YouTube search

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 👤 𝐏𝐑𝐎𝐅𝐈𝐋𝐄 𝐒𝐘𝐒𝐓𝐄𝐌
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .clone @user — Add 1 pic, others safe
▸ .reclone — Remove 1 pic, others safe
▸ .cloneall @user — Full clone
▸ .recloneall — Full restore
▸ .ghost — Add 1 ghost pic
▸ .unghost — Remove 1 ghost pic
▸ .ghostall — Hide all pics, add 1
▸ .unghostall — Restore all pics
▸ .saveprofile — Save original profile
▸ .restoreprofile — Restore saved original

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🛡️ 𝐀𝐃𝐌𝐈𝐍 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .admins — Group admin list
▸ .addadmin reply/@id — Add admin
▸ .deladmin reply/@id — Remove admin

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🔇 𝐌𝐔𝐓𝐄 & 𝐑𝐄𝐒𝐓𝐑𝐈𝐂𝐓
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .mute reply/@id — Local mute
▸ .unmute reply/@id — Unmute
▸ .gmute reply/@id — Global mute
▸ .gunmute reply/@id — Global unmute
▸ .lock — Lock group
▸ .unlock — Unlock group
▸ .ban reply/@id — Ban user
▸ .unban reply/@id — Unban user

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 👥 𝐆𝐑𝐎𝐔𝐏 𝐌𝐎𝐃
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .tagall <text> — Tag all members
▸ .tagall2 <text> — Tag one by one
▸ .stoptag — Stop tagall
▸ .raid <count> — Raid
▸ .purge — Delete all below replied
▸ .throw reply/@id — Kick user
▸ .stop — Stop all loops

✨ ᴘᴏᴡᴇʀᴇᴅ ʙʏ @iVILLAINi ✨"""

        part2 = """╭━━━━━━━━━━━━━━━━━━━━╮
⚙️ 𝐔𝐒𝐄𝐑𝐁𝐎𝐓 𝐌𝐄𝐍𝐔 (𝟐/𝟐) ⚙️
╰━━━━━━━━━━━━━━━━━━━━╯

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🤖 𝐀𝐈 𝐑𝐄𝐏𝐋𝐘
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .aireply on/off — AI auto-reply
▸ .aireply approve <reply/@id>
▸ .aireply remove <reply/@id>
▸ .aireply list
▸ .aireply status

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ ⚙️ 𝐀𝐔𝐓𝐎 𝐒𝐘𝐒𝐓𝐄𝐌
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .autoreact on/off — DM reactions
▸ .autoreactg on/off — Group reactions
▸ .autoreply on/off
▸ .autoreply set <text>
▸ .autoreply reset
▸ .autoreply approve reply/@id
▸ .autoreply remove reply/@id
▸ .autoreply list
▸ .pmguard on/off
▸ .pmguard set <2/3/4/6>
▸ .pmguard set off
▸ .pmguard status
▸ .approve reply/@user/id
▸ .disapprove reply/@user/id
▸ .approvelist
▸ .blacklist reply/@id
▸ .removeblacklist reply/@id

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🎯 𝐑𝐀𝐈𝐃 𝐄𝐍𝐆𝐈𝐍𝐄
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .reply reply/@id — Reply raid
▸ .sreply — Stop reply raid
▸ .rr reply/@id — 🤣 Raid
▸ .srr — Stop RR
▸ .flag reply/@id — Flag raid
▸ .sflag — Stop flag
▸ .hrr reply/@id — Heart raid
▸ .shrr — Stop heart

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ ⚡ 𝐒𝐏𝐀𝐌 & 𝐅𝐀𝐒𝐓
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .spray <count> <text> — Silent spam
▸ .dspray — Stop spam
▸ .fastgc set <text> — Start fastgc
▸ .fastgc stop — Stop fastgc

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🎲 𝐅𝐔𝐍
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .ping — Check latency
▸ .flip — Coin flip
▸ .dice — Roll dice

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🕵️ 𝐒𝐓𝐀𝐋𝐊 𝐓𝐎𝐎𝐋𝐒
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .stalk — Deep profile info (reply)
▸ .allpfp — All profile pics
▸ .lastmsg <n> — Last N messages

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🎵 𝐌𝐔𝐒𝐈𝐂
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .lyrics <song>
▸ .songinfo <song>
▸ .spotify <query>
▸ .trending
▸ .ringtone <song>
▸ .playlist <mood>

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🎨 𝐀𝐈 𝐈𝐌𝐀𝐆𝐄
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .t2i <prompt> — Text to image

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ ✨ 𝐀𝐍𝐈𝐌𝐀𝐓𝐈𝐎𝐍𝐒
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .animate <text>
▸ .spinner [sec]
▸ .loveu / .loves
▸ .matrix [sec]
▸ .hearts <text>
▸ .countdown [n]
▸ .wave <text>

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ ✨ 𝐅𝐀𝐍𝐂𝐘 𝐓𝐄𝐗𝐓
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .hi .hey .bye .welcome
▸ .ok .yes .wow .cool .omg .lol
▸ .love .hate .sad
▸ .good .bad .best
▸ .go .fire .boss
▸ .text <anything>
▸ .banner <word> [font]

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🎨 𝐓𝐄𝐗𝐓 𝐀𝐑𝐓
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .gm .gn .hbd .wlc .hello2 .love2
▸ .heyy .gg .flower .gum .howdy .cool2
▸ .hug .hug2 .thnx .purpose
▸ .hii .om .sm .il

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🌍 𝐏𝐔𝐁𝐋𝐈𝐂 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .weather <city>
▸ .news [query]
▸ .azan <city>

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🖼️ 𝐈𝐌𝐀𝐆𝐄 𝐓𝐎𝐎𝐋𝐒
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .sticker — Image to sticker
▸ .toimg — Sticker to image
▸ .blur — Blur an image
▸ .img2pdf — Image to PDF

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ 🌤️ 𝐅𝐎𝐑𝐄𝐂𝐀𝐒𝐓 & 𝐀𝐐𝐈
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .forecast <city>
▸ .aqi <city>

╭━━━━━━━━━━━━━━━━━━━━━━╮
┃ ⏰ 𝐒𝐂𝐇𝐄𝐃𝐔𝐋𝐄𝐑
╰━━━━━━━━━━━━━━━━━━━━━━╯
▸ .schedule <date> <time> <target> <msg>
▸ .schedulech <date> <time> <link> <msg>
▸ .schedules — Pending list
▸ .cancelschedule <id> — Cancel
▸ .sync — Auto-tune timing

✨ ᴘᴏᴡᴇʀᴇᴅ ʙʏ @iVILLAINi ✨"""

        try:
            await event.reply(part1)
        except Exception as e:
            log.error(f"help part1 failed: {e}")
        await asyncio.sleep(0.7)
        try:
            await event.reply(part2)
        except Exception as e:
            log.error(f"help part2 failed: {e}")

    # ═══════════════ BASIC ═══════════════
    @cmd('alive', delete_cmd=False)
    async def alive_cmd(event):
        start = db.get("start_time", datetime.now().isoformat())
        try:
            uptime = datetime.now() - datetime.fromisoformat(start)
        except Exception:
            uptime = datetime.now() - datetime.now()
        days = uptime.days
        h, r = divmod(uptime.seconds, 3600)
        m, s = divmod(r, 60)
        me = await client.get_me()
        caption = (f"❛.𝁘ໍ𝗖lØn𝛜X🎭.𝁘ໍ USERBOT IS ALIVE\n✨\n"
                   f"⏳ **UPTIME:** {days}d : {h}h : {m}m : {s}s\n"
                   f"👤 **USER:** {me.first_name or 'User'}\n"
                   f"👑 **OWNER:** @iVILLAINi\n")
        IMG = "https://files.catbox.moe/rmj6hg.mp4"
        try:
            await client.send_file(event.chat_id, IMG, caption=caption,
                                   parse_mode='markdown', reply_to=event.message.id)
        except Exception:
            await event.reply(caption, parse_mode='markdown')

    @cmd('profile', delete_cmd=False)
    async def profile_cmd(event):
        me = await client.get_me()
        await event.reply(
            f"**👤 Your Profile**\nName: {me.first_name}\n"
            f"ID: `{me.id}`\nUsername: @{me.username or 'None'}",
            parse_mode='markdown')

    @cmd('id', delete_cmd=False)
    async def id_cmd(event):
        if event.is_reply:
            msg = await event.get_reply_message()
            await event.reply(f"**User ID:** `{msg.sender_id}`", parse_mode='markdown')
        else:
            await event.reply(f"**Chat ID:** `{event.chat_id}`", parse_mode='markdown')

    @cmd('info', delete_cmd=False)
    async def info_cmd(event):
        text = get_args(event.message)
        uid = await resolve_user(client, event.message, text)
        if not uid:
            await event.reply("❌ User not found."); return
        try:
            u = await client.get_entity(uid)
            await event.reply(
                f"**👤 User Info**\nName: {u.first_name}\nID: `{u.id}`\n"
                f"Username: @{u.username or 'None'}",
                parse_mode='markdown')
        except Exception:
            await event.reply("❌ Could not get user info.")

    # ═══════════════ AI COMMAND ═══════════════
    @cmd('ai', delete_cmd=False)
    async def ai_cmd(event):
        query = get_args(event.message).strip()
        reply_msg = await event.get_reply_message() if event.is_reply else None
        reply_text = ""
        if reply_msg:
            reply_text = (reply_msg.text or "").strip()
            if not reply_text and hasattr(reply_msg, 'message'):
                reply_text = (reply_msg.message or "").strip()
            if not reply_text and hasattr(reply_msg, 'caption'):
                reply_text = (reply_msg.caption or "").strip()
        if not query and not reply_text:
            await event.reply(
                "❌ **Usage:** `.ai <your question>`\n\n"
                "**Example:** `.ai What is Python?`\n"
                "**Reply method:** kisi message pe reply karke `.ai` bhejo")
            return
        if not GROQ_API_KEY:
            await event.reply("❌ Groq API key not set. Contact owner."); return
        try:
            MAX_INPUT_CHARS = 12000
            if len(reply_text) > MAX_INPUT_CHARS:
                reply_text = reply_text[:MAX_INPUT_CHARS] + "\n...[input truncated]"
            if reply_text and query:
                final_prompt = (
                    f"User ne ek message pe reply kiya hai. Us message ka content ye hai:\n\n"
                    f"{reply_text}\n\n"
                    f"Ab user ka sawaal/instruction ye hai:\n{query}\n\n"
                    f"Upar wale message ke context me jawab do.")
            elif reply_text and not query:
                final_prompt = (
                    f"Is message ko samjho aur user ko batao ki isme kya likha hai:\n\n"
                    f"{reply_text}\n\n"
                    f"Agar ye kisi aur language me hai to Hinglish me translate karo.")
            else:
                final_prompt = query
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}",
            }
            payload = {
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": (
                        "You are a helpful assistant. Reply in the same language as the user's message "
                        "(Hindi/Hinglish/English). If user gives you a message to translate or explain, "
                        "do it ACCURATELY and COMPLETELY.\n\n"
                        "STRICT FORMATTING RULES:\n"
                        "- Use PLAIN TEXT only. NO markdown symbols.\n"
                        "- NO headers, bullets, quotes, bold, italic.\n"
                        "- Just clean, natural text."
                    )},
                    {"role": "user", "content": final_prompt},
                ],
                "max_tokens": 8000,
                "temperature": 0.3,
            }
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        await event.reply(f"❌ **Groq API Error:** `{resp.status}`\n`{error_text[:200]}`")
                        return
                    data = await resp.json()
                        if action == 'on':
        if not GROQ_API_KEY:
            await event.reply("❌ Groq API key not set. Contact owner."); return
        if db.get('auto_reply', {}).get('enabled', False):
            await event.reply(
                "⚠️ **Autoreply ON hai**\n\nPehle `.autoreply off` karo.",
                parse_mode='markdown')
            return
        db['ai_reply']['enabled'] = True
        await save_db()
        await event.reply("✅ **AI Reply ON**", parse_mode='markdown')
    elif action == 'off':
        db['ai_reply']['enabled'] = False
        await save_db()
        await event.reply("✅ **AI Reply OFF**")
    else:
        await event.reply(
            "**Usage:**\n`.aireply on/off`\n`.aireply status`\n"
            "`.aireply approve <reply/@id>`\n`.aireply remove <reply/@id>`\n`.aireply list`",
            parse_mode='markdown')

# ═══════════════ SAVE MEDIA ═══════════════
@cmd('save', delete_cmd=False)
async def save_cmd(event):
    if not is_owner(event.sender_id):
        return
    try:
        await event.delete()
    except Exception:
        pass
    if not event.is_reply:
        return
    reply = await event.get_reply_message()
    if not reply or not reply.media:
        return
    media_list = []
    if getattr(reply, 'grouped_id', None):
        try:
            all_msgs = await client.get_messages(
                reply.chat_id, min_id=reply.id - 20, max_id=reply.id + 20, limit=50)
            for m in all_msgs:
                if getattr(m, 'grouped_id', None) == reply.grouped_id and m.media:
                    media_list.append(m)
            media_list.sort(key=lambda x: x.id)
            if not media_list:
                media_list = [reply]
        except Exception:
            media_list = [reply]
    else:
        media_list = [reply]
    sender = await reply.get_sender()
    sender_name = "Unknown"
    if sender:
        sender_name = ((getattr(sender, 'first_name', '') or "")
                       + (" " + getattr(sender, 'last_name', '') if getattr(sender, 'last_name', None) else "")
                       ).strip() or "Unknown"
    sender_username = f"@{sender.username}" if sender and getattr(sender, 'username', None) else "None"
    total = len(media_list)
    for idx, media in enumerate(media_list, 1):
        file_path = None
        try:
            file_path = await media.download_media(file=str(TEMP_DIR))
            if not file_path or not os.path.exists(file_path):
                continue
            filesize = os.path.getsize(file_path)
            filesize_mb = filesize / (1024 * 1024)
            if filesize > 2000 * 1024 * 1024:
                try:
                    os.remove(file_path)
                except Exception:
                    pass
                continue
            original_caption = media.text or ""
            caption = (f"👤 **From:** {sender_name}\n"
                       f"📛 **Username:** {sender_username}\n"
                       f"📦 **Size:** {filesize_mb:.2f} MB\n")
            if original_caption:
                caption += f"\n📝 **Caption:** {original_caption[:300]}"
            await client.send_file("me", file_path, caption=caption,
                                   parse_mode='markdown', supports_streaming=True)
            try:
                os.remove(file_path)
            except Exception:
                pass
            if total > 1:
                await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"Save error (item {idx}): {e}")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

@cmd('saveaudio', delete_cmd=False)
async def saveaudio_cmd(event):
    if not is_owner(event.sender_id):
        return
    try:
        await event.delete()
    except Exception:
        pass
    if not event.is_reply:
        return
    reply = await event.get_reply_message()
    if not reply or not reply.media:
        return
    is_video = False
    if getattr(reply, 'video', None):
        is_video = True
    elif getattr(reply, 'document', None):
        mime = getattr(reply.document, 'mime_type', '') or ''
        if mime.startswith('video/'):
            is_video = True
    is_audio = False
    if getattr(reply, 'audio', None) or getattr(reply, 'voice', None):
        is_audio = True
    elif getattr(reply, 'document', None):
        mime = getattr(reply.document, 'mime_type', '') or ''
        if mime.startswith('audio/'):
            is_audio = True
    sender = await reply.get_sender()
    sender_name = "Unknown"
    if sender:
        sender_name = ((getattr(sender, 'first_name', '') or "")
                       + (" " + getattr(sender, 'last_name', '') if getattr(sender, 'last_name', None) else "")
                       ).strip() or "Unknown"
    sender_username = f"@{sender.username}" if sender and getattr(sender, 'username', None) else "None"

    if is_audio and not is_video:
        file_path = None
        try:
            file_path = await reply.download_media(file=str(TEMP_DIR))
            if not file_path or not os.path.exists(file_path):
                return
            filesize_mb = os.path.getsize(file_path) / (1024 * 1024)
            original_caption = reply.text or ""
            caption = (f"🎵 **Saved Audio**\n\n"
                       f"👤 **From:** {sender_name}\n"
                       f"📛 **Username:** {sender_username}\n"
                       f"📦 **Size:** {filesize_mb:.2f} MB\n")
            if original_caption:
                caption += f"\n📝 **Caption:** {original_caption[:300]}"
            await client.send_file("me", file_path, caption=caption, parse_mode='markdown')
        except Exception as e:
            log.error(f"saveaudio (already audio) error: {e}")
        finally:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        return

    if not is_video:
        return

    file_path = None
    audio_path = None
    try:
        file_path = await reply.download_media(file=str(TEMP_DIR))
        if not file_path or not os.path.exists(file_path):
            return
        filesize = os.path.getsize(file_path)
        if filesize > 2000 * 1024 * 1024:
            return
        audio_path = str(TEMP_DIR / f"audio_{int(time.time())}_{random.randint(1, 9999)}.mp3")
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", file_path,
            "-vn", "-acodec", "libmp3lame",
            "-ab", "192k", "-ar", "44100",
            "-y", audio_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            return
        audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        original_caption = reply.text or ""
        caption = (f"🎵 **Saved Audio (Extracted)**\n\n"
                   f"👤 **From:** {sender_name}\n"
                   f"📛 **Username:** {sender_username}\n"
                   f"📦 **Size:** {audio_size_mb:.2f} MB\n")
        if original_caption:
            caption += f"\n📝 **Caption:** {original_caption[:300]}"
        await client.send_file("me", audio_path, caption=caption, parse_mode='markdown')
    except Exception as e:
        log.error(f"saveaudio error: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass

@cmd('savemsg', delete_cmd=False)
async def savemsg_cmd(event):
    if not is_owner(event.sender_id):
        return
    try:
        await event.delete()
    except Exception:
        pass
    if not event.is_reply:
        return
    reply = await event.get_reply_message()
    if not reply or not reply.text:
        return
    try:
        sender = await reply.get_sender()
        sender_name = "Unknown"
        if sender:
            sender_name = ((getattr(sender, 'first_name', '') or "")
                           + (" " + getattr(sender, 'last_name', '') if getattr(sender, 'last_name', None) else "")
                           ).strip() or "Unknown"
        sender_username = f"@{sender.username}" if sender and getattr(sender, 'username', None) else "None"
        original_text = reply.text or ""
        saved_text = (f"👤 **From:** {sender_name}\n"
                      f"📛 **Username:** {sender_username}\n\n"
                      f"📝 **Message:**\n{original_text}")
        await client.send_message("me", saved_text, parse_mode='markdown')
    except Exception as e:
        log.error(f"SaveMsg error: {e}")

@cmd('savechannel', delete_cmd=False)
async def savechannel_cmd(event):
    if not is_owner(event.sender_id):
        return
    args = get_args(event.message).strip()

    async def save_single_msg(msg, chat_title, link_str):
        try:
            is_link_preview = isinstance(msg.media, MessageMediaWebPage) if msg.media else False
            is_unsupported = isinstance(msg.media, MessageMediaUnsupported) if msg.media else False
            sender_name = "Unknown"
            sender_username = "None"
            try:
                sender = await msg.get_sender()
                if sender:
                    sender_name = ((getattr(sender, 'first_name', '') or "")
                                   + (" " + getattr(sender, 'last_name', '') if getattr(sender, 'last_name', None) else "")
                                   ).strip() or "Unknown"
                    sender_username = f"@{sender.username}" if getattr(sender, 'username', None) else "None"
            except Exception:
                pass
            if msg.media and not is_link_preview and not is_unsupported:
                file_path = await msg.download_media(file=str(TEMP_DIR))
                if file_path and os.path.exists(file_path):
                    caption = (f"📢 **From:** {chat_title}\n"
                               f"👤 **Sender:** {sender_name}\n"
                               f"📛 **Username:** {sender_username}")
                    if msg.text:
                        caption += f"\n\n📝 **Caption:** {msg.text[:500]}"
                    caption += f"\n\n🔗 **Link:** {link_str}"
                    await client.send_file("me", file_path, caption=caption,
                                           parse_mode='markdown', supports_streaming=True)
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                    return True
            elif msg.text:
                saved_text = (f"📢 **From:** {chat_title}\n"
                              f"👤 **Sender:** {sender_name}\n"
                              f"📛 **Username:** {sender_username}\n"
                              f"📝 **Message:**\n{msg.text}\n\n"
                              f"🔗 **Link:** {link_str}")
                await client.send_message("me", saved_text, parse_mode='markdown')
                return True
        except Exception as e:
            log.error(f"save_single_msg error: {e}")
        return False

    async def save_grouped_album(msg, chat_title, base_link):
        grouped_id = getattr(msg, 'grouped_id', None)
        if not grouped_id:
            return None
        try:
            min_id = max(1, msg.id - 15)
            max_id = msg.id + 15
            all_msgs = await client.get_messages(
                msg.chat_id if hasattr(msg, 'chat_id') else msg.peer_id,
                min_id=min_id, max_id=max_id, limit=50)
            album_msgs = [m for m in all_msgs if getattr(m, 'grouped_id', None) == grouped_id]
            album_msgs.sort(key=lambda x: x.id)
            if not album_msgs:
                return None
            total = len(album_msgs)
            success_count = 0
            for idx, alb_msg in enumerate(album_msgs, 1):
                link_str = f"{base_link.rsplit('/', 1)[0]}/{alb_msg.id}"
                ok = await save_single_msg(alb_msg, chat_title, link_str)
                if ok:
                    success_count += 1
                await asyncio.sleep(0.5)
            return (success_count, total)
        except Exception as e:
            log.error(f"save_grouped_album error: {e}")
            return None

    if event.is_reply:
        reply = await event.get_reply_message()
        if reply:
            try:
                chat = await reply.get_chat()
                chat_title = getattr(chat, 'title', 'Unknown')
                chat_username = getattr(chat, 'username', None)
                base_link = (f"https://t.me/{chat_username}/{reply.id}"
                             if chat_username else f"Chat ID: {reply.chat_id}")
                if getattr(reply, 'grouped_id', None):
                    result = await save_grouped_album(reply, chat_title, base_link)
                    if result:
                        await event.reply("✅ **Album Saved!**")
                        return
                ok = await save_single_msg(reply, chat_title, base_link)
                if ok:
                    await event.reply("✅ **Saved to Saved Messages!**")
                    return
            except Exception as e:
                log.error(f"savechannel reply error: {e}")
            return

    if not args:
        await event.reply(
            "❌ **Usage:**\n"
            "**1. Reply:** message pe reply karo → `.savechannel`\n"
            "**2. Link:** `.savechannel https://t.me/channelname/123`\n"
            "`.savechannel -1001234567890 123`")
        return

    try:
        target_chat = None
        target_msg_id = None
        link_match = re.search(r't\.me/(?:c/)?([^/]+)/(\d+)', args)
        if link_match:
            chat_part = link_match.group(1)
            target_msg_id = int(link_match.group(2))
            try:
                target_chat = int(chat_part) if (chat_part.startswith('-100') or chat_part.isdigit()) else chat_part
            except Exception:
                target_chat = chat_part
            if chat_part.isdigit() and not chat_part.startswith('-100'):
                target_chat = int(f"-100{chat_part}")
        else:
            parts = args.split()
            if len(parts) >= 2:
                try:
                    target_chat = int(parts[0])
                    target_msg_id = int(parts[1])
                except Exception:
                    await event.reply("❌ Invalid format.")
                    return
            else:
                await event.reply("❌ Invalid format.")
                return
        messages = await client.get_messages(target_chat, ids=target_msg_id)
        if not messages:
            await event.reply("❌ Message not found."); return
        msg = messages[0] if isinstance(messages, list) else messages
        if not msg:
            await event.reply("❌ Message not found."); return
        chat = await msg.get_chat() if hasattr(msg, 'get_chat') else None
        chat_title = getattr(chat, 'title', 'Channel') if chat else 'Channel'
        if getattr(msg, 'grouped_id', None):
            status_msg = await event.reply("📦 **Album detected!** Save kar raha hun...")
            result = await save_grouped_album(msg, chat_title, args)
            if result:
                await status_msg.edit("✅ **Album Saved!**")
                return
            else:
                await status_msg.edit("⚠️ Album fetch failed, trying single media...")
        ok = await save_single_msg(msg, chat_title, args)
        if ok:
            await event.reply("✅ **Saved!**")
        else:
            await event.reply("❌ Nothing to save (no media/text).")
    except Exception as e:
        log.error(f"savechannel error: {e}")
        await event.reply(f"❌ Error: `{str(e)[:200]}`")
        # ═══════════════ CLONE ═══════════════
@cmd('clone')
async def clone_cmd(event):
    if not is_owner(event.sender_id):
        return
    text = get_args(event.message)
    target_id = await resolve_user(client, event.message, text)
    if not target_id:
        await event.reply("❌ Target not found."); return
    me = await client.get_me()
    db['clone_data']['orig_first_name'] = me.first_name or ''
    db['clone_data']['orig_last_name'] = me.last_name or ''
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['clone_data']['orig_bio'] = full_me.full_user.about or ''
    except Exception:
        db['clone_data']['orig_bio'] = ''
    await save_db()
    await asyncio.sleep(0.3)
    try:
        target = await client.get_entity(target_id)
        await client(UpdateProfileRequest(
            first_name=getattr(target, 'first_name', '') or '',
            last_name=getattr(target, 'last_name', '') or ''))
        try:
            full_target = await client(functions.users.GetFullUserRequest(id=target_id))
            await client(functions.account.UpdateProfileRequest(
                about=getattr(full_target.full_user, 'about', '') or ''))
        except Exception:
            pass
        try:
            target_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=target_id, offset=0, max_id=0, limit=1))
            if target_photos.photos:
                photo_path = str(TEMP_DIR / "clone_temp.jpg")
                await client.download_media(target_photos.photos[0], photo_path)
                if os.path.exists(photo_path):
                    uploaded = await client(functions.photos.UploadProfilePhotoRequest(
                        file=await client.upload_file(photo_path)))
                    db['clone_data']['clone_photo_id'] = uploaded.photo.id
                    await save_db()
                    os.remove(photo_path)
        except Exception:
            pass
        await event.reply("✅ **Profile Cloned!**")
    except Exception as e:
        await event.reply(f"❌ Clone failed: {str(e)[:100]}")

@cmd('reclone')
async def reclone_cmd(event):
    if not is_owner(event.sender_id):
        return
    cd = db.get("clone_data", {})
    if not cd.get('orig_first_name'):
        cd = await get_fresh_data('clone_data') or {}
    if not cd.get('orig_first_name'):
        await event.reply("❌ No clone data."); return
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=cd.get('orig_first_name', ''),
            last_name=cd.get('orig_last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=cd.get('orig_bio', '')))
    except Exception:
        pass
    try:
        clone_photo_id = cd.get('clone_photo_id')
        if clone_photo_id:
            photos_obj = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            for p in photos_obj.photos:
                if p.id == clone_photo_id:
                    await client(functions.photos.DeletePhotosRequest(id=[p]))
                    break
    except Exception:
        pass
    db['clone_data'] = {}
    await save_db()
    await event.reply("✅ **Profile Restored!**")

@cmd('cloneall')
async def cloneall_cmd(event):
    if not is_owner(event.sender_id):
        return
    text = get_args(event.message)
    target_id = await resolve_user(client, event.message, text)
    if not target_id:
        await event.reply("❌ Target not found."); return
    me = await client.get_me()
    db['cloneall_data'] = {
        'orig_first_name': me.first_name or '',
        'orig_last_name': me.last_name or '',
        'orig_bio': '', 'orig_photo_paths': [],
    }
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['cloneall_data']['orig_bio'] = full_me.full_user.about or ''
    except Exception:
        pass
    try:
        photo_dir = DATA_DIR / f"user_{owner_id}" / "cloneall_photos"
        shutil.rmtree(photo_dir, ignore_errors=True)
        photo_dir.mkdir(parents=True, exist_ok=True)
        all_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        photos_list = list(all_photos.photos)
        photos_list.reverse()
        saved_paths = []
        for i, photo in enumerate(photos_list):
            photo_path = str(photo_dir / f"orig_{i:03d}.jpg")
            if await client.download_media(photo, photo_path):
                saved_paths.append(photo_path)
        db['cloneall_data']['orig_photo_paths'] = saved_paths
    except Exception:
        pass
    await save_db()
    await asyncio.sleep(0.3)
    try:
        target = await client.get_entity(target_id)
        await client(UpdateProfileRequest(
            first_name=getattr(target, 'first_name', '') or '',
            last_name=getattr(target, 'last_name', '') or ''))
        try:
            full_target = await client(functions.users.GetFullUserRequest(id=target_id))
            await client(functions.account.UpdateProfileRequest(
                about=getattr(full_target.full_user, 'about', '') or ''))
        except Exception:
            pass
        try:
            current_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            if current_photos.photos:
                await client(DeletePhotosRequest(id=current_photos.photos))
        except Exception:
            pass
        try:
            target_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=target_id, offset=0, max_id=0, limit=1))
            if target_photos.photos:
                photo_path = str(TEMP_DIR / "cloneall_temp.jpg")
                await client.download_media(target_photos.photos[0], photo_path)
                if os.path.exists(photo_path):
                    await client(functions.photos.UploadProfilePhotoRequest(
                        file=await client.upload_file(photo_path)))
                    os.remove(photo_path)
        except Exception:
            pass
        await event.reply("✅ **Full Clone Done!**")
    except Exception as e:
        await event.reply(f"❌ Clone failed: {str(e)[:100]}")

@cmd('recloneall')
async def recloneall_cmd(event):
    if not is_owner(event.sender_id):
        return
    cd = db.get("cloneall_data", {})
    if not cd.get('orig_first_name'):
        cd = await get_fresh_data('cloneall_data') or {}
    if not cd.get('orig_first_name'):
        await event.reply("❌ No cloneall data."); return
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=cd.get('orig_first_name', ''),
            last_name=cd.get('orig_last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=cd.get('orig_bio', '') or ''))
    except Exception:
        pass
    try:
        current_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        if current_photos.photos:
            await client(DeletePhotosRequest(id=current_photos.photos))
    except Exception:
        pass
    orig_paths = cd.get('orig_photo_paths', [])
    orig_paths.sort()
    for photo_path in orig_paths:
        if os.path.exists(photo_path):
            try:
                await client(functions.photos.UploadProfilePhotoRequest(
                    file=await client.upload_file(photo_path)))
                await asyncio.sleep(0.5)
            except Exception:
                pass
    db['cloneall_data'] = {}
    await save_db()
    await event.reply("✅ **Full Profile Restored!**")

@cmd('saveprofile')
async def saveprofile_cmd(event):
    if not is_owner(event.sender_id):
        return
    me = await client.get_me()
    sp = {'first_name': me.first_name or '', 'last_name': me.last_name or '', 'bio': ''}
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        sp['bio'] = full_me.full_user.about or ''
    except Exception:
        pass
    try:
        current_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        sp['photo_ids'] = [p.id for p in current_photos.photos]
        sp['photo_count'] = len(sp['photo_ids'])
    except Exception:
        sp['photo_ids'] = []
        sp['photo_count'] = 0
    try:
        photo_dir = DATA_DIR / f"user_{owner_id}" / "saved_profile_photos"
        shutil.rmtree(photo_dir, ignore_errors=True)
        photo_dir.mkdir(parents=True, exist_ok=True)
        all_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        photos_list = list(all_photos.photos)
        photos_list.reverse()
        saved_paths = []
        for i, photo in enumerate(photos_list):
            photo_path = str(photo_dir / f"saved_{i:03d}.jpg")
            if await client.download_media(photo, photo_path):
                saved_paths.append(photo_path)
        sp['photo_paths'] = saved_paths
        sp['saved_at'] = datetime.now().strftime("%d %b %Y, %I:%M %p")
    except Exception:
        sp['photo_paths'] = []
    db['saved_profile'] = sp
    await save_db()
    await event.reply("💾 **Original Profile Saved!**")

@cmd('restoreprofile')
async def restoreprofile_cmd(event):
    if not is_owner(event.sender_id):
        return
    sp = db.get('saved_profile', {})
    if not sp or not sp.get('first_name'):
        sp = await get_fresh_data('saved_profile') or {}
    if not sp or not sp.get('first_name'):
        await event.reply("❌ Koi saved profile nahi hai!\n\nPehle `.saveprofile` use karein.")
        return
    saved_count = sp.get('photo_count', 0)
    if saved_count == 0:
        await event.reply("⚠️ Saved profile me photo nahi thi!"); return
    me = await client.get_me()
    msg = await event.reply("⏳ Restoring...")
    try:
        await client(UpdateProfileRequest(
            first_name=sp.get('first_name', ''),
            last_name=sp.get('last_name', '')))
        try:
            await client(functions.account.UpdateProfileRequest(
                about=sp.get('bio', '') or ''))
        except Exception:
            pass
        try:
            current_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            current_count = len(current_photos.photos)
            if current_count > saved_count:
                extra = current_count - saved_count
                photos_sorted = sorted(list(current_photos.photos),
                                       key=lambda p: p.id, reverse=True)
                await client(functions.photos.DeletePhotosRequest(id=photos_sorted[:extra]))
            elif current_count < saved_count:
                photo_dir = DATA_DIR / f"user_{owner_id}" / "saved_profile_photos"
                if photo_dir.exists():
                    saved_files = sorted(photo_dir.glob("saved_*.jpg"))
                    to_upload_count = saved_count - current_count
                    if len(saved_files) >= to_upload_count:
                        for f in saved_files[-to_upload_count:]:
                            try:
                                await client(functions.photos.UploadProfilePhotoRequest(
                                    file=await client.upload_file(str(f))))
                                await asyncio.sleep(0.7)
                            except Exception:
                                break
            await msg.edit("✅ **Original Profile Restored!**")
        except Exception:
            await msg.edit("✅ Restored!")
    except Exception as e:
        await msg.edit(f"❌ Restore failed: `{str(e)[:200]}`")

# ═══════════════ GHOST ═══════════════
@cmd('ghost')
async def ghost_cmd(event):
    if not is_owner(event.sender_id):
        return
    if db.get("ghost_on"):
        await event.reply("👻 Ghost already active!"); return
    me = await client.get_me()
    db['ghost_data'] = {'first_name': me.first_name or '', 'last_name': me.last_name or '', 'bio': ''}
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['ghost_data']['bio'] = full_me.full_user.about or ''
    except Exception:
        db['ghost_data']['bio'] = ''
    await save_db()
    await asyncio.sleep(0.3)
    try:
        await client(UpdateProfileRequest(first_name="Deleted", last_name="Account"))
        await client(functions.account.UpdateProfileRequest(about="This account has been deleted"))
        ghost_img_path = await get_ghost_image_path()
        if ghost_img_path and os.path.exists(ghost_img_path):
            uploaded = await client(functions.photos.UploadProfilePhotoRequest(
                file=await client.upload_file(ghost_img_path)))
            db['ghost_data']['ghost_photo_id'] = uploaded.photo.id
            await save_db()
        db['ghost_on'] = True
        await save_db()
        await event.reply("👻 **Ghost Mode Activated!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

@cmd('unghost')
async def unghost_cmd(event):
    if not is_owner(event.sender_id):
        return
    if not db.get("ghost_on"):
        await event.reply("❌ Ghost not active!"); return
    gd = db.get("ghost_data", {})
    if not gd.get('first_name'):
        gd = await get_fresh_data('ghost_data') or {}
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=gd.get('first_name', ''),
            last_name=gd.get('last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=gd.get('bio', '') or ''))
    except Exception:
        pass
    try:
        gid = gd.get('ghost_photo_id')
        if gid:
            photos_obj = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            for p in photos_obj.photos:
                if p.id == gid:
                    await client(functions.photos.DeletePhotosRequest(id=[p]))
                    break
    except Exception:
        pass
    db['ghost_on'] = False
    db['ghost_data'] = {}
    await save_db()
    await event.reply("✅ **Ghost Mode Deactivated!**")

@cmd('ghostall')
async def ghostall_cmd(event):
    if not is_owner(event.sender_id):
        return
    if db.get("ghostall_on"):
        await event.reply("👻 Ghost All already active!"); return
    me = await client.get_me()
    db['ghostall_data'] = {
        'first_name': me.first_name or '', 'last_name': me.last_name or '',
        'bio': '', 'photo_paths': []}
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['ghostall_data']['bio'] = full_me.full_user.about or ''
    except Exception:
        pass
    try:
        photo_dir = DATA_DIR / f"user_{owner_id}" / "ghostall_photos"
        shutil.rmtree(photo_dir, ignore_errors=True)
        photo_dir.mkdir(parents=True, exist_ok=True)
        all_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        photos_list = list(all_photos.photos)
        photos_list.reverse()
        saved_paths = []
        for i, photo in enumerate(photos_list):
            photo_path = str(photo_dir / f"orig_{i:03d}.jpg")
            if await client.download_media(photo, photo_path):
                saved_paths.append(photo_path)
        db['ghostall_data']['photo_paths'] = saved_paths
    except Exception:
        pass
    await save_db()
    await asyncio.sleep(0.3)
    try:
        await client(UpdateProfileRequest(first_name="Deleted", last_name="Account"))
        await client(functions.account.UpdateProfileRequest(about="This account has been deleted"))
        try:
            current_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            if current_photos.photos:
                await client(DeletePhotosRequest(id=current_photos.photos))
        except Exception:
            pass
        ghost_img_path = await get_ghost_image_path()
        if ghost_img_path and os.path.exists(ghost_img_path):
            await client(functions.photos.UploadProfilePhotoRequest(
                file=await client.upload_file(ghost_img_path)))
        db['ghostall_on'] = True
        await save_db()
        await event.reply("👻 **Ghost Mode Activated!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

@cmd('unghostall')
async def unghostall_cmd(event):
    if not is_owner(event.s
                    # ═══════════════ CLONE ═══════════════
@cmd('clone')
async def clone_cmd(event):
    if not is_owner(event.sender_id):
        return
    text = get_args(event.message)
    target_id = await resolve_user(client, event.message, text)
    if not target_id:
        await event.reply("❌ Target not found."); return
    me = await client.get_me()
    db['clone_data']['orig_first_name'] = me.first_name or ''
    db['clone_data']['orig_last_name'] = me.last_name or ''
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['clone_data']['orig_bio'] = full_me.full_user.about or ''
    except Exception:
        db['clone_data']['orig_bio'] = ''
    await save_db()
    await asyncio.sleep(0.3)
    try:
        target = await client.get_entity(target_id)
        await client(UpdateProfileRequest(
            first_name=getattr(target, 'first_name', '') or '',
            last_name=getattr(target, 'last_name', '') or ''))
        try:
            full_target = await client(functions.users.GetFullUserRequest(id=target_id))
            await client(functions.account.UpdateProfileRequest(
                about=getattr(full_target.full_user, 'about', '') or ''))
        except Exception:
            pass
        try:
            target_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=target_id, offset=0, max_id=0, limit=1))
            if target_photos.photos:
                photo_path = str(TEMP_DIR / "clone_temp.jpg")
                await client.download_media(target_photos.photos[0], photo_path)
                if os.path.exists(photo_path):
                    uploaded = await client(functions.photos.UploadProfilePhotoRequest(
                        file=await client.upload_file(photo_path)))
                    db['clone_data']['clone_photo_id'] = uploaded.photo.id
                    await save_db()
                    os.remove(photo_path)
        except Exception:
            pass
        await event.reply("✅ **Profile Cloned!**")
    except Exception as e:
        await event.reply(f"❌ Clone failed: {str(e)[:100]}")

@cmd('reclone')
async def reclone_cmd(event):
    if not is_owner(event.sender_id):
        return
    cd = db.get("clone_data", {})
    if not cd.get('orig_first_name'):
        cd = await get_fresh_data('clone_data') or {}
    if not cd.get('orig_first_name'):
        await event.reply("❌ No clone data."); return
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=cd.get('orig_first_name', ''),
            last_name=cd.get('orig_last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=cd.get('orig_bio', '')))
    except Exception:
        pass
    try:
        clone_photo_id = cd.get('clone_photo_id')
        if clone_photo_id:
            photos_obj = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            for p in photos_obj.photos:
                if p.id == clone_photo_id:
                    await client(functions.photos.DeletePhotosRequest(id=[p]))
                    break
    except Exception:
        pass
    db['clone_data'] = {}
    await save_db()
    await event.reply("✅ **Profile Restored!**")

@cmd('cloneall')
async def cloneall_cmd(event):
    if not is_owner(event.sender_id):
        return
    text = get_args(event.message)
    target_id = await resolve_user(client, event.message, text)
    if not target_id:
        await event.reply("❌ Target not found."); return
    me = await client.get_me()
    db['cloneall_data'] = {
        'orig_first_name': me.first_name or '',
        'orig_last_name': me.last_name or '',
        'orig_bio': '', 'orig_photo_paths': [],
    }
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['cloneall_data']['orig_bio'] = full_me.full_user.about or ''
    except Exception:
        pass
    try:
        photo_dir = DATA_DIR / f"user_{owner_id}" / "cloneall_photos"
        shutil.rmtree(photo_dir, ignore_errors=True)
        photo_dir.mkdir(parents=True, exist_ok=True)
        all_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        photos_list = list(all_photos.photos)
        photos_list.reverse()
        saved_paths = []
        for i, photo in enumerate(photos_list):
            photo_path = str(photo_dir / f"orig_{i:03d}.jpg")
            if await client.download_media(photo, photo_path):
                saved_paths.append(photo_path)
        db['cloneall_data']['orig_photo_paths'] = saved_paths
    except Exception:
        pass
    await save_db()
    await asyncio.sleep(0.3)
    try:
        target = await client.get_entity(target_id)
        await client(UpdateProfileRequest(
            first_name=getattr(target, 'first_name', '') or '',
            last_name=getattr(target, 'last_name', '') or ''))
        try:
            full_target = await client(functions.users.GetFullUserRequest(id=target_id))
            await client(functions.account.UpdateProfileRequest(
                about=getattr(full_target.full_user, 'about', '') or ''))
        except Exception:
            pass
        try:
            current_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            if current_photos.photos:
                await client(DeletePhotosRequest(id=current_photos.photos))
        except Exception:
            pass
        try:
            target_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=target_id, offset=0, max_id=0, limit=1))
            if target_photos.photos:
                photo_path = str(TEMP_DIR / "cloneall_temp.jpg")
                await client.download_media(target_photos.photos[0], photo_path)
                if os.path.exists(photo_path):
                    await client(functions.photos.UploadProfilePhotoRequest(
                        file=await client.upload_file(photo_path)))
                    os.remove(photo_path)
        except Exception:
            pass
        await event.reply("✅ **Full Clone Done!**")
    except Exception as e:
        await event.reply(f"❌ Clone failed: {str(e)[:100]}")

@cmd('recloneall')
async def recloneall_cmd(event):
    if not is_owner(event.sender_id):
        return
    cd = db.get("cloneall_data", {})
    if not cd.get('orig_first_name'):
        cd = await get_fresh_data('cloneall_data') or {}
    if not cd.get('orig_first_name'):
        await event.reply("❌ No cloneall data."); return
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=cd.get('orig_first_name', ''),
            last_name=cd.get('orig_last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=cd.get('orig_bio', '') or ''))
    except Exception:
        pass
    try:
        current_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        if current_photos.photos:
            await client(DeletePhotosRequest(id=current_photos.photos))
    except Exception:
        pass
    orig_paths = cd.get('orig_photo_paths', [])
    orig_paths.sort()
    for photo_path in orig_paths:
        if os.path.exists(photo_path):
            try:
                await client(functions.photos.UploadProfilePhotoRequest(
                    file=await client.upload_file(photo_path)))
                await asyncio.sleep(0.5)
            except Exception:
                pass
    db['cloneall_data'] = {}
    await save_db()
    await event.reply("✅ **Full Profile Restored!**")

@cmd('saveprofile')
async def saveprofile_cmd(event):
    if not is_owner(event.sender_id):
        return
    me = await client.get_me()
    sp = {'first_name': me.first_name or '', 'last_name': me.last_name or '', 'bio': ''}
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        sp['bio'] = full_me.full_user.about or ''
    except Exception:
        pass
    try:
        current_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        sp['photo_ids'] = [p.id for p in current_photos.photos]
        sp['photo_count'] = len(sp['photo_ids'])
    except Exception:
        sp['photo_ids'] = []
        sp['photo_count'] = 0
    try:
        photo_dir = DATA_DIR / f"user_{owner_id}" / "saved_profile_photos"
        shutil.rmtree(photo_dir, ignore_errors=True)
        photo_dir.mkdir(parents=True, exist_ok=True)
        all_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        photos_list = list(all_photos.photos)
        photos_list.reverse()
        saved_paths = []
        for i, photo in enumerate(photos_list):
            photo_path = str(photo_dir / f"saved_{i:03d}.jpg")
            if await client.download_media(photo, photo_path):
                saved_paths.append(photo_path)
        sp['photo_paths'] = saved_paths
        sp['saved_at'] = datetime.now().strftime("%d %b %Y, %I:%M %p")
    except Exception:
        sp['photo_paths'] = []
    db['saved_profile'] = sp
    await save_db()
    await event.reply("💾 **Original Profile Saved!**")

@cmd('restoreprofile')
async def restoreprofile_cmd(event):
    if not is_owner(event.sender_id):
        return
    sp = db.get('saved_profile', {})
    if not sp or not sp.get('first_name'):
        sp = await get_fresh_data('saved_profile') or {}
    if not sp or not sp.get('first_name'):
        await event.reply("❌ Koi saved profile nahi hai!\n\nPehle `.saveprofile` use karein.")
        return
    saved_count = sp.get('photo_count', 0)
    if saved_count == 0:
        await event.reply("⚠️ Saved profile me photo nahi thi!"); return
    me = await client.get_me()
    msg = await event.reply("⏳ Restoring...")
    try:
        await client(UpdateProfileRequest(
            first_name=sp.get('first_name', ''),
            last_name=sp.get('last_name', '')))
        try:
            await client(functions.account.UpdateProfileRequest(
                about=sp.get('bio', '') or ''))
        except Exception:
            pass
        try:
            current_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            current_count = len(current_photos.photos)
            if current_count > saved_count:
                extra = current_count - saved_count
                photos_sorted = sorted(list(current_photos.photos),
                                       key=lambda p: p.id, reverse=True)
                await client(functions.photos.DeletePhotosRequest(id=photos_sorted[:extra]))
            elif current_count < saved_count:
                photo_dir = DATA_DIR / f"user_{owner_id}" / "saved_profile_photos"
                if photo_dir.exists():
                    saved_files = sorted(photo_dir.glob("saved_*.jpg"))
                    to_upload_count = saved_count - current_count
                    if len(saved_files) >= to_upload_count:
                        for f in saved_files[-to_upload_count:]:
                            try:
                                await client(functions.photos.UploadProfilePhotoRequest(
                                    file=await client.upload_file(str(f))))
                                await asyncio.sleep(0.7)
                            except Exception:
                                break
            await msg.edit("✅ **Original Profile Restored!**")
        except Exception:
            await msg.edit("✅ Restored!")
    except Exception as e:
        await msg.edit(f"❌ Restore failed: `{str(e)[:200]}`")

# ═══════════════ GHOST ═══════════════
@cmd('ghost')
async def ghost_cmd(event):
    if not is_owner(event.sender_id):
        return
    if db.get("ghost_on"):
        await event.reply("👻 Ghost already active!"); return
    me = await client.get_me()
    db['ghost_data'] = {'first_name': me.first_name or '', 'last_name': me.last_name or '', 'bio': ''}
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['ghost_data']['bio'] = full_me.full_user.about or ''
    except Exception:
        db['ghost_data']['bio'] = ''
    await save_db()
    await asyncio.sleep(0.3)
    try:
        await client(UpdateProfileRequest(first_name="Deleted", last_name="Account"))
        await client(functions.account.UpdateProfileRequest(about="This account has been deleted"))
        ghost_img_path = await get_ghost_image_path()
        if ghost_img_path and os.path.exists(ghost_img_path):
            uploaded = await client(functions.photos.UploadProfilePhotoRequest(
                file=await client.upload_file(ghost_img_path)))
            db['ghost_data']['ghost_photo_id'] = uploaded.photo.id
            await save_db()
        db['ghost_on'] = True
        await save_db()
        await event.reply("👻 **Ghost Mode Activated!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

@cmd('unghost')
async def unghost_cmd(event):
    if not is_owner(event.sender_id):
        return
    if not db.get("ghost_on"):
        await event.reply("❌ Ghost not active!"); return
    gd = db.get("ghost_data", {})
    if not gd.get('first_name'):
        gd = await get_fresh_data('ghost_data') or {}
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=gd.get('first_name', ''),
            last_name=gd.get('last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=gd.get('bio', '') or ''))
    except Exception:
        pass
    try:
        gid = gd.get('ghost_photo_id')
        if gid:
            photos_obj = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            for p in photos_obj.photos:
                if p.id == gid:
                    await client(functions.photos.DeletePhotosRequest(id=[p]))
                    break
    except Exception:
        pass
    db['ghost_on'] = False
    db['ghost_data'] = {}
    await save_db()
    await event.reply("✅ **Ghost Mode Deactivated!**")

@cmd('ghostall')
async def ghostall_cmd(event):
    if not is_owner(event.sender_id):
        return
    if db.get("ghostall_on"):
        await event.reply("👻 Ghost All already active!"); return
    me = await client.get_me()
    db['ghostall_data'] = {
        'first_name': me.first_name or '', 'last_name': me.last_name or '',
        'bio': '', 'photo_paths': []}
    try:
        full_me = await client(functions.users.GetFullUserRequest(id=me.id))
        db['ghostall_data']['bio'] = full_me.full_user.about or ''
    except Exception:
        pass
    try:
        photo_dir = DATA_DIR / f"user_{owner_id}" / "ghostall_photos"
        shutil.rmtree(photo_dir, ignore_errors=True)
        photo_dir.mkdir(parents=True, exist_ok=True)
        all_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        photos_list = list(all_photos.photos)
        photos_list.reverse()
        saved_paths = []
        for i, photo in enumerate(photos_list):
            photo_path = str(photo_dir / f"orig_{i:03d}.jpg")
            if await client.download_media(photo, photo_path):
                saved_paths.append(photo_path)
        db['ghostall_data']['photo_paths'] = saved_paths
    except Exception:
        pass
    await save_db()
    await asyncio.sleep(0.3)
    try:
        await client(UpdateProfileRequest(first_name="Deleted", last_name="Account"))
        await client(functions.account.UpdateProfileRequest(about="This account has been deleted"))
        try:
            current_photos = await client(functions.photos.GetUserPhotosRequest(
                user_id=me.id, offset=0, max_id=0, limit=100))
            if current_photos.photos:
                await client(DeletePhotosRequest(id=current_photos.photos))
        except Exception:
            pass
        ghost_img_path = await get_ghost_image_path()
        if ghost_img_path and os.path.exists(ghost_img_path):
            await client(functions.photos.UploadProfilePhotoRequest(
                file=await client.upload_file(ghost_img_path)))
        db['ghostall_on'] = True
        await save_db()
        await event.reply("👻 **Ghost Mode Activated!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

@cmd('unghostall')
async def unghostall_cmd(event):
    if not is_owner(event.s
                                if not is_owner(event.sender_id):
        return
    if not db.get("ghostall_on"):
        await event.reply("❌ Ghost All not active!"); return
    gd = db.get("ghostall_data", {})
    if not gd.get('first_name'):
        gd = await get_fresh_data('ghostall_data') or {}
    me = await client.get_me()
    try:
        await client(UpdateProfileRequest(
            first_name=gd.get('first_name', ''),
            last_name=gd.get('last_name', '')))
        await client(functions.account.UpdateProfileRequest(
            about=gd.get('bio', '') or ''))
    except Exception:
        pass
    try:
        current_photos = await client(functions.photos.GetUserPhotosRequest(
            user_id=me.id, offset=0, max_id=0, limit=100))
        if current_photos.photos:
            await client(DeletePhotosRequest(id=current_photos.photos))
    except Exception:
        pass
    orig_paths = gd.get('photo_paths', [])
    orig_paths.sort()
    for photo_path in orig_paths:
        if os.path.exists(photo_path):
            try:
                await client(functions.photos.UploadProfilePhotoRequest(
                    file=await client.upload_file(photo_path)))
                await asyncio.sleep(0.5)
            except Exception:
                pass
    db['ghostall_on'] = False
    db['ghostall_data'] = {}
    await save_db()
    await event.reply("✅ **Ghost Mode Deactivated!**")

# ═══════════════ ADMIN ═══════════════
@cmd('admins')
async def admins_cmd(event):
    if not event.is_group:
        await event.reply(f"👑 Owner: `{db.get('owner_id', owner_id)}`\n**Admins:** {db['admins']}", parse_mode='markdown'); return
    try:
        admins = []
        async for participant in client.iter_participants(event.chat_id, filter=ChannelParticipantsAdmins):
            if participant.bot: continue
            name = ((participant.first_name or "") + (" " + participant.last_name if participant.last_name else "")).strip() or "Unknown"
            username = f"@{participant.username}" if participant.username else "None"
            admins.append(f"👤 **{name}**\n   🆔 `{participant.id}`\n   📛 {username}")
        if not admins:
            await event.reply("❌ Koi admin nahi mila."); return
        text = f"👑 **Group Admins ({len(admins)})**\n" + "═" * 25 + "\n\n"
        text += "\n\n".join(admins)
        await event.reply(text, parse_mode='markdown')
    except Exception as e:
        await event.reply(f"❌ Failed: `{str(e)[:150]}`")

@cmd('addadmin')
async def addadmin_cmd(event):
    if not is_owner(event.sender_id): return
    if not event.is_group:
        await event.reply("❌ Group me use karo."); return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        rights = ChatAdminRights(change_info=True, post_messages=True, edit_messages=True, delete_messages=True, ban_users=True, invite_users=True, pin_messages=True, add_admins=False, anonymous=False, manage_call=True, other=True, manage_topics=True)
        await client(EditAdminRequest(channel=event.chat_id, user_id=uid, admin_rights=rights, rank="Admin"))
        if uid not in db['admins']:
            db['admins'].append(uid)
            await save_db()
        await event.reply("✅ **Admin Added with Full Rights!**")
    except Exception as e:
        await event.reply(f"❌ Failed: `{str(e)[:150]}`")

@cmd('deladmin')
async def deladmin_cmd(event):
    if not is_owner(event.sender_id): return
    if not event.is_group:
        await event.reply("❌ Group me use karo."); return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        empty_rights = ChatAdminRights(change_info=False, post_messages=False, edit_messages=False, delete_messages=False, ban_users=False, invite_users=False, pin_messages=False, add_admins=False, anonymous=False, manage_call=False, other=False, manage_topics=False)
        await client(EditAdminRequest(channel=event.chat_id, user_id=uid, admin_rights=empty_rights, rank=""))
        if uid in db['admins']:
            db['admins'].remove(uid)
            await save_db()
        await event.reply("✅ **Admin Demoted!**")
    except Exception as e:
        await event.reply(f"❌ Failed: `{str(e)[:150]}`")

# ═══════════════ MUTE & RESTRICT ═══════════════
@cmd('mute', delete_cmd=False)
async def mute_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, send_messages=True)))
        await event.reply("🔇 **User Muted!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

@cmd('unmute', delete_cmd=False)
async def unmute_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, send_messages=False)))
        await event.reply("🔊 **User Unmuted!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

@cmd('gmute')
async def gmute_cmd(event):
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    db['gmuted'][str(uid)] = True
    await save_db()
    await event.reply("🌐 **User Globally Muted!**")

@cmd('gunmute')
async def gunmute_cmd(event):
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    if str(uid) in db['gmuted']:
        del db['gmuted'][str(uid)]
        await save_db()
    await event.reply("🌐 **User Globally Unmuted!**")

def get_base_banned_rights():
    return ChatBannedRights(until_date=None, send_messages=False, send_media=False, send_stickers=True, send_gifs=True, send_games=False, send_inline=False, send_polls=False, embed_links=True, send_photos=False, send_videos=False, send_audios=False, send_voices=False, send_docs=False, pin_messages=True, change_info=True, invite_users=False)

@cmd('lock')
async def lock_cmd(event):
    if not event.is_group:
        await event.reply("❌ Not a group."); return
    try:
        base = get_base_banned_rights()
        base.send_messages = True; base.send_media = True; base.send_photos = True; base.send_videos = True
        base.send_audios = True; base.send_voices = True; base.send_docs = True; base.send_polls = True
        base.send_games = True; base.send_inline = True
        await client(EditChatDefaultBannedRightsRequest(peer=event.chat_id, banned_rights=base))
        await event.reply("🔒 Group Locked!")
    except Exception as e:
        await event.reply(f"❌ Lock failed: {str(e)[:100]}")

@cmd('unlock')
async def unlock_cmd(event):
    if not event.is_group:
        await event.reply("❌ Not a group."); return
    try:
        base = get_base_banned_rights()
        base.send_messages = False; base.send_media = False; base.send_photos = False; base.send_videos = False
        base.send_audios = False; base.send_voices = False; base.send_docs = False; base.send_polls = False
        base.send_games = False; base.send_inline = False
        await client(EditChatDefaultBannedRightsRequest(peer=event.chat_id, banned_rights=base))
        await event.reply("🔓 Group Unlocked!")
    except Exception as e:
        await event.reply(f"❌ Unlock failed: {str(e)[:100]}")

@cmd('ban')
async def ban_cmd(event):
    if not event.is_group:
        await event.reply("❌ Group me use karo."); return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, view_messages=True)))
        await event.reply("🚫 **User Banned!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:150]}")

@cmd('unban')
async def unban_cmd(event):
    if not event.is_group:
        await event.reply("❌ Group me use karo."); return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, view_messages=False)))
        await event.reply("✅ **User Unbanned!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:150]}")

@cmd('tagall')
async def tagall_cmd(event):
    if not event.is_group:
        await event.reply("❌ Not a group."); return
    text = get_args(event.message)
    chat_id = event.chat_id
    all_users_list = []
    try:
        async for user in client.iter_participants(chat_id):
            if not user.deleted and not user.bot: all_users_list.append(user)
    except Exception as e:
        await event.reply(f"❌ Failed: {str(e)[:100]}"); return
    if not all_users_list:
        await event.reply("❌ No members found."); return
    db['tagall_running'] = True
    chunk_size = 5
    for i in range(0, len(all_users_list), chunk_size):
        if not db.get('tagall_running', False):
            break
        chunk = all_users_list[i:i + chunk_size]
        mentions = []
        for user in chunk:
            name = user.first_name or "User"
            name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            mentions.append(f'<a href="tg://user?id={user.id}">{name}</a>')
        mention_str = ' '.join(mentions)
        msg = f"{text}\n{mention_str}" if text else mention_str
        await event.respond(msg, parse_mode='html', reply_to=event.reply_to_msg_id if event.is_reply else None)
        await asyncio.sleep(2.5)
    db['tagall_running'] = False

@cmd('tagall2')
async def tagall2_cmd(event):
    if not event.is_group:
        await event.reply("❌ Not a group."); return
    text = get_args(event.message)
    if not text:
        await event.reply("❌ Usage: `.tagall2 <text>`"); return
    chat_id = event.chat_id
    all_users_list = []
    try:
        async for user in client.iter_participants(chat_id):
            if not user.deleted and not user.bot: all_users_list.append(user)
    except Exception as e:
        await event.reply(f"❌ Failed: {str(e)[:100]}"); return
    if not all_users_list:
        await event.reply("❌ No members found."); return
    db['tagall_running'] = True
    count = 0
    for user in all_users_list:
        if not db.get('tagall_running', False):
            break
        try:
            name = user.first_name or "User"
            name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            msg = f'<a href="tg://user?id={user.id}">{name}</a> {text}'
            await event.respond(msg, parse_mode='html', reply_to=event.reply_to_msg_id if event.is_reply else None)
            count += 1
            await asyncio.sleep(1.2)
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 2)
        except Exception as e:
            log.warning(f"tagall2 error: {e}")
            continue
    db['tagall_running'] = False
    await event.respond(f"✅ Done! {count} members have been tagged.", reply_to=event.reply_to_msg_id if event.is_reply else None)

@cmd('stoptag')
async def stoptag_cmd(event):
    db['tagall_running'] = False
    await event.reply("🛑 **Tagall stopped!**")

@cmd('raid')
async def raid_cmd(event):
    if not event.is_reply:
        await event.reply("❌ Reply to a user."); return
    count_str = get_args(event.message)
    try: count = int(count_str) if count_str else 10
    except: count = 10
    count = min(count, 50)
    reply = await event.get_reply_message()
    for i in range(count):
        try:
            msg_template = random.choice(RAID_MESSAGES).replace('{n}', str(i + 1))
            await reply.reply(msg_template)
            await asyncio.sleep(0.3)
        except: break

@cmd('purge', delete_cmd=True)
async def purge_cmd(event):
    if not event.is_reply:
        await event.reply("❌ Reply to a message."); return
    reply_msg = await event.get_reply_message()
    if not reply_msg:
        await event.reply("❌ Could not fetch."); return
    chat_id = event.chat_id
    start_id = reply_msg.id
    all_ids = []
    last_id = start_id
    while True:
        try:
            msgs = await client.get_messages(chat_id, min_id=last_id, limit=100, reverse=False)
            if not msgs: break
            ids = [m.id for m in msgs]
            all_ids.extend(ids)
            last_id = min(ids) if ids else start_id
            if len(msgs) < 100: break
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)[:100]}"); return
    if not all_ids:
        await event.reply("✅ No messages below replied."); return
    total_deleted = 0
    for i in range(0, len(all_ids), 100):
        chunk = all_ids[i:i + 100]
        try:
            await client.delete_messages(chat_id, chunk)
            total_deleted += len(chunk)
            await asyncio.sleep(0.5)
        except Exception as e:
            await event.reply(f"❌ Delete failed: {str(e)[:100]}"); return
    await event.reply(f"✅ Purged **{total_deleted}** messages.")

@cmd('throw')
async def throw_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    try:
        await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, view_messages=True)))
        await asyncio.sleep(0.5)
        await client(EditBannedRequest(event.chat_id, uid, ChatBannedRights(until_date=None, view_messages=False)))
        await event.reply("👢 **User Kicked!**")
    except Exception as e:
        await event.reply(f"❌ {str(e)[:100]}")

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

# ═══════════════ FAST GC ═══════════════
async def fast_gc_loop(chat_id):
    while True:
        data = db['fast_gc_data'].get(chat_id)
        if not data or not data.get('enabled', False): break
        template = data.get('template', 'FastGC')
        counter = data.get('counter', 0) + 1
        new_title = f"{template} [{counter}]"
        try:
            entity = await client.get_entity(chat_id)
            if hasattr(entity, 'broadcast') and entity.broadcast:
                await client(EditTitleRequest(channel=entity, title=new_title))
            else:
                await client(EditChatTitleRequest(chat_id=chat_id, title=new_title))
            data['counter'] = counter
            await save_db()
        except Exception as e:
            log.warning(f"FastGC error: {e}")
            db['fast_gc_data'][chat_id]['enabled'] = False
            await save_db()
            break
        await asyncio.sleep(1.5)

@cmd('fastgc')
async def fastgc_cmd(event):
    args = get_args(event.message).split()
    if not args:
        await event.reply("Usage: `.fastgc set <text>` | `.fastgc stop`"); return
    chat_id = event.chat_id
    action = args[0].lower()
    if action == 'set' and len(args) > 1:
        template = ' '.join(args[1:])
        db['fast_gc_data'][chat_id] = {'enabled': True, 'template': template, 'counter': 0}
        await save_db()
        asyncio.create_task(fast_gc_loop(chat_id))
        await event.reply(f"⚡ **Fast GC started!**")
    elif action == 'stop':
        if chat_id in db['fast_gc_data']:
            db['fast_gc_data'][chat_id]['enabled'] = False
            await save_db()
            await event.reply("🛑 **Fast GC stopped!**")
        else:
            await event.reply("❌ No fast GC running.")
    else:
        await event.reply("Usage: `.fastgc set <text>` | `.fastgc stop`")

# ═══════════════ AUTO REACT ═══════════════
@cmd('autoreact')
async def autoreact_cmd(event):
    arg = get_args(event.message).lower()
    if arg == 'on':
        db['auto_react_dm_enabled'] = True
        await save_db()
        await event.reply("✅ **DM Auto‑React ON**")
    elif arg == 'off':
        db['auto_react_dm_enabled'] = False
        await save_db()
        await event.reply("✅ **DM Auto‑React OFF**")
    else:
        await event.reply("**Usage:** `.autoreact on/off`")

@cmd('autoreactg')
async def autoreactg_cmd(event):
    arg = get_args(event.message).lower()
    if arg == 'on':
        db['auto_react_group_enabled'] = True
        await save_db()
        await event.reply("✅ **Group Auto‑React ON**")
    elif arg == 'off':
        db['auto_react_group_enabled'] = False
        await save_db()
        await event.reply("✅ **Group Auto‑React OFF**")
    else:
        await event.reply("**Usage:** `.autoreactg on/off`")

# ═══════════════ AUTO REPLY & PMGUARD ═══════════════
@cmd('autoreply')
async def autoreply_cmd(event):
    text = get_args(event.message)
    parts = text.split(' ', 1)
    DEFAULT_REPLY = "The owner is busy with some personal work at the moment😌Please wait until they are back online🥀"
    if not parts or not parts[0]:
        await event.reply("**Usage:**\n`.autoreply on/off`\n`.autoreply set <text>`\n`.autoreply reset`\n`.autoreply status`\n`.autoreply approve <reply/@id>`\n`.autoreply remove <reply/@id>`\n`.autoreply list`", parse_mode='markdown')
        return
    action = parts[0].lower()

    if action == 'status':
        ar = db.get('auto_reply', {})
        await event.reply(
            f"⚙️ **Auto Reply Status**\n\nEnabled: `{ar.get('enabled', False)}`\nMode: `{ar.get('mode', 'always')}`\nText: `{ar.get('text', 'N/A')[:100]}`\nReplied users: `{len(ar.get('replied_users', []))}`\nApproved users: `{len(ar.get('approved_users', []))}`",
            parse_mode='markdown')
        return

    if action in ['approve', 'remove', 'list']:
        if action == 'list':
            approved = db['auto_reply'].get('approved_users', [])
            if not approved:
                await event.reply("📭 Koi approved user nahi hai."); return
            text_out = f"✅ **Auto-Reply Approved Users ({len(approved)})**\n" + "═" * 25 + "\n\n"
            for i, uid in enumerate(approved, 1):
                name = "Unknown"
                username = "Unknown"
                try:
                    u = await client.get_entity(int(uid))
                    name = ((u.first_name or "") + (" " + u.last_name if getattr(u, 'last_name', None) else "")).strip() or "Unknown"
                    username = f"@{u.username}" if u.username else "None"
                except: pass
                text_out += f"{i}. 👤 `{name}`\n   🆔 `{uid}`\n   📛 {username}\n\n"
            await event.reply(text_out, parse_mode='markdown')
            return

        target_id = None
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            target_id = reply_msg.sender_id
        else:
            arg = parts[1] if len(parts) > 1 else ""
            if arg.startswith("@"):
                try: u = await client.get_entity(arg); target_id = u.id
                except: await event.reply(f"❌ `{arg}` not found."); return
            else:
                try: target_id = int(arg)
                except: await event.reply("❌ Invalid user."); return
        if target_id == db.get("owner_id", owner_id):
            await event.reply("❌ Aap khud ko approve nahi kar sakte."); return
        approved = db['auto_reply'].get('approved_users', [])
# ═══════════════ RAID ENGINE ═══════════════
@cmd('reply')
async def reply_raid_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    chat_id = event.chat_id
    async def send_reply():
        msg = random.choice(REPLY_MESSAGES)
        await client.send_message(chat_id, msg)
    asyncio.create_task(raid_loop(event, uid, "reply", send_reply, 1.5))
    await event.reply(f"⚔️ **Reply raid started!**")

@cmd('sreply')
async def sreply_raid_cmd(event):
    chat_id = str(event.chat_id)
    if chat_id in raid_state['reply']:
        raid_state['reply'][chat_id].clear()
        await event.reply("🛑 **Reply raid stopped!**")

@cmd('rr')
async def rr_raid_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    chat_id = event.chat_id
    async def send_rr():
        await client.send_message(chat_id, f"🤣 {user_link(uid)}", parse_mode='markdown')
    asyncio.create_task(raid_loop(event, uid, "rr", send_rr, 1))
    await event.reply(f"🤣 **RR raid started!**")

@cmd('srr')
async def srr_raid_cmd(event):
    chat_id = str(event.chat_id)
    if chat_id in raid_state['rr']:
        raid_state['rr'][chat_id].clear()
        await event.reply("🛑 **RR raid stopped!**")

@cmd('flag')
async def flag_raid_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    chat_id = event.chat_id
    flags = ['🇮🇳', '🇺🇸', '🇬🇧', '🇩🇪', '🇫🇷', '🇯🇵', '🇨🇳', '🇷🇺', '🇧🇷', '🇦🇪']
    async def send_flag():
        await client.send_message(chat_id, f"{random.choice(flags)} {user_link(uid)}", parse_mode='markdown')
    asyncio.create_task(raid_loop(event, uid, "flag", send_flag, 1.2))
    await event.reply(f"🚩 **Flag raid started!**")

@cmd('sflag')
async def sflag_raid_cmd(event):
    chat_id = str(event.chat_id)
    if chat_id in raid_state['flag']:
        raid_state['flag'][chat_id].clear()
        await event.reply("🛑 **Flag raid stopped!**")

@cmd('hrr')
async def heart_raid_cmd(event):
    if not event.is_group: return
    uid = await resolve_user(client, event.message, get_args(event.message))
    if not uid:
        await event.reply("❌ User not found."); return
    chat_id = event.chat_id
    hearts = ['❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎', '💗']
    async def send_heart():
        await client.send_message(chat_id, f"{random.choice(hearts)} {user_link(uid)}", parse_mode='markdown')
    asyncio.create_task(raid_loop(event, uid, "hrr", send_heart, 1))
    await event.reply(f"💖 **Heart raid started!**")

@cmd('shrr')
async def sheart_raid_cmd(event):
    chat_id = str(event.chat_id)
    if chat_id in raid_state['hrr']:
        raid_state['hrr'][chat_id].clear()
        await event.reply("🛑 **Heart raid stopped!**")

# ═══════════════ SPAM ═══════════════
@cmd('spray')
async def spray_cmd(event):
    args = get_args(event.message).strip()
    if not args: return
    parts = args.split()
    count = 10
    text = args
    if parts[0].isdigit():
        count = int(parts[0])
        text = ' '.join(parts[1:]).strip()
    elif parts[-1].isdigit():
        count = int(parts[-1])
        text = ' '.join(parts[:-1]).strip()
    if not text: return
    count = min(max(count, 1), 100)
    chat_id = event.chat_id
    db['spam_running'] = True
    async def spray_loop():
        for _ in range(count):
            if not db.get('spam_running', False): break
            try:
                await client.send_message(chat_id, text)
                await asyncio.sleep(0.4)
            except FloodWaitError as e: await asyncio.sleep(e.seconds + 2)
            except Exception: break
        db['spam_running'] = False
    asyncio.create_task(spray_loop())

@cmd('dspray')
async def dspray_cmd(event):
    db['spam_running'] = False
    await event.reply("🛑 **Spam stopped!**")

# ═══════════════ FUN & STALK ═══════════════
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
    if not reply:
        await event.reply("❌ Reply to a user's message!"); return
    try:
        user = await reply.get_sender()
        full = await client(functions.users.GetFullUserRequest(user.id))
        fu = full.full_user
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
        username = f"@{user.username}" if user.username else "Hidden"
        bio = fu.about or "No bio"
        photos = await client.get_profile_photos(user)
        status = "Unknown"
        if hasattr(user, 'status') and user.status:
            sn = type(user.status).__name__
            if 'Online' in sn: status = "🟢 Online NOW"
            elif 'Recently' in sn: status = "🟡 Recently"
            elif 'LastWeek' in sn: status = "🟠 Last week"
            elif 'LastMonth' in sn: status = "🔴 Last month"
            else: status = "⚫ Long time ago"
        premium = "⭐ Yes" if getattr(user, 'premium', False) else "No"
        verified = "✅ Yes" if getattr(user, 'verified', False) else "No"
        scam = "⚠️ YES!" if getattr(user, 'scam', False) else "No"
        fake = "⚠️ YES!" if getattr(user, 'fake', False) else "No"
        await event.reply(
            f"🕵️ **Deep Stalk**\n\n👤 **Name:** {name}\n🆔 **ID:** `{user.id}`\n📛 **Username:** {username}\n📝 **Bio:** {bio}\n📊 **Status:** {status}\n📸 **Profile Pics:** {len(photos)}\n⭐ **Premium:** {premium}\n✅ **Verified:** {verified}\n🚫 **Scam:** {scam}\n🎭 **Fake:** {fake}\n💬 **Common Chats:** {fu.common_chats_count}\n\n🔗 [Profile Link](tg://user?id={user.id})",
            parse_mode='markdown')
    except Exception as e:
        await event.reply(f"❌ Error: `{str(e)[:150]}`")

@cmd('allpfp', delete_cmd=False)
async def allpfp_cmd(event):
    reply = await event.get_reply_message()
    if reply: user = await reply.get_sender()
    else: user = await event.get_sender()
    try:
        photos = await client.get_profile_photos(user, limit=100)
        if not photos:
            await event.reply("❌ No profile pictures found!"); return
        total = len(photos)
        msg = await event.reply(f"📸 Downloading all {total} pics...")
        sent = 0
        for i, photo in enumerate(photos):
            try:
                await client.send_file(event.chat_id, photo, caption=f"📸 **{user.first_name or 'User'}'s PFP** ({i + 1}/{total})")
                sent += 1
                await asyncio.sleep(0.4)
            except FloodWaitError as e: await asyncio.sleep(e.seconds + 2)
            except: continue
        await msg.edit(f"✅ Sent all **{sent}/{total}** profile pictures!")
    except Exception as e:
        await event.reply(f"❌ Error: `{str(e)[:150]}`")

@cmd('lastmsg', delete_cmd=False)
async def lastmsg_cmd(event):
    reply = await event.get_reply_message()
    if not reply:
        await event.reply("❌ Reply to a user's message!"); return
    args = get_args(event.message)
    try: count = min(int(args) if args else 5, 20)
    except: count = 5
    try:
        user = await reply.get_sender()
        chat = await event.get_chat()
        msgs = []
        async for m in client.iter_messages(chat, from_user=user, limit=count):
            text = m.text or "[Media]"
            msgs.append(f"• `{text[:60]}{'...' if len(text) > 60 else ''}`")
        if not msgs:
            await event.reply(f"❌ No messages from {user.first_name or 'user'}!"); return
        await event.reply(f"🕵️ **Last {len(msgs)} messages from {user.first_name or 'user'}**\n\n" + "\n".join(msgs))
    except Exception as e:
        await event.reply(f"❌ Error: `{str(e)[:150]}`")

# ═══════════════ SCHEDULER ═══════════════
@cmd('schedule', delete_cmd=True)
async def schedule_cmd(event):
    args = get_args(event.message).strip()
    if not args:
        await event.reply("**Format:** `.schedule <date> <time> <target> <message>`\nExample: `.schedule 2026-01-15 06:19:00 PM @user Hello`", parse_mode='markdown')
        return
    parts = args.split()
    if len(parts) < 2:
        await event.reply("❌ Invalid format."); return
    date_str, time_str = parts[0], parts[1]
    consumed = 2
    if len(parts) >= 3 and parts[2].upper() in ("AM", "PM"):
        time_str = f"{time_str} {parts[2].upper()}"
        consumed = 3
    rest = " ".join(parts[consumed:]).strip()
    try:
        sched_dt = _parse_schedule_time(date_str, time_str)
        sched_ts = sched_dt.timestamp()
    except Exception as e:
        await event.reply(f"❌ **Invalid date/time**\n`{str(e)[:150]}`"); return
    if sched_ts <= time.time():
        await event.reply("❌ Time past me hai!"); return
    target_id = None
    msg_text = rest
    from_saved = None
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        target_id = reply_msg.sender_id
        from_saved = reply_msg.id
        if not msg_text: msg_text = (reply_msg.message or "").strip()
    else:
        tparts = rest.split(' ', 1)
        target_str = tparts[0]
        msg_text = tparts[1].strip() if len(tparts) > 1 else ""
        if target_str.startswith('@'):
            try: ent = await client.get_entity(target_str); target_id = ent.id
            except Exception: await event.reply(f"❌ `{target_str}` not found."); return
        else:
            try: target_id = int(target_str); await client.get_entity(target_id)
            except Exception: await event.reply(f"❌ Chat `{target_str}` not found."); return
    if not msg_text:
        await event.reply("❌ Message empty hai."); return
    if sched_col is None:
        await event.reply("❌ MongoDB not connected."); return
    from bson import ObjectId
    doc = {
        "_id": str(ObjectId()), "owner_id": owner_id, "target_id": target_id,
        "text": msg_text, "reply_to_msg_id": from_saved, "comment_to": None,
        "scheduled_ts": sched_ts, "scheduled_str": _fmt_ist_full(sched_ts),
        "scheduled_short": _fmt_ist_12h(sched_ts), "chat_id": event.chat_id,
        "created_at": time.time(), "status": "pending",
    }
    await sched_col.insert_one(doc)
    asyncio.create_task(_scheduler_runner(client, doc))
    confirm_msg = await event.reply(f"✅ **SCHEDULED!**\nID: `{doc['_id'][:8]}`\nTarget: `{target_id}`\nWhen: `{doc['scheduled_short']}`", parse_mode='markdown')
    await sched_col.update_one({"_id": doc["_id"]}, {"$set": {"confirm_chat_id": confirm_msg.chat_id, "confirm_msg_id": confirm_msg.id}})

@cmd('schedules', delete_cmd=False)
async def schedules_cmd(event):
    if sched_col is None:
        await event.reply("❌ MongoDB not connected."); return
    cursor = sched_col.find({"owner_id": owner_id, "status": "pending"}).sort("scheduled_ts", 1)
    rows = await cursor.to_list(length=50)
    if not rows:
        await event.reply("📭 Koi pending schedule nahi hai."); return
    text = f"⏰ **PENDING SCHEDULES ({len(rows)})**\n" + "═" * 25 + "\n\n"
    for r in rows:
        eta = int(r["scheduled_ts"] - time.time())
        if eta < 0: eta = 0
        h, rem = divmod(eta, 3600)
        m, s = divmod(rem, 60)
        preview = r["text"][:50] + ("..." if len(r["text"]) > 50 else "")
        when_str = r.get("scheduled_short") or _fmt_ist_12h(r["scheduled_ts"])
        text += f"🆔 `{r['_id'][:8]}`\n🎯 `{r['target_id']}`\n🕐 `{when_str}` (ETA {h}h{m}m{s}s)\n📝 {preview}\n\n"
    text += "Cancel: `.cancelschedule <id>`"
    await event.reply(text, parse_mode='markdown')

@cmd('cancelschedule', delete_cmd=False)
async def cancelschedule_cmd(event):
    if sched_col is None:
        await event.reply("❌ MongoDB not connected."); return
    args = get_args(event.message).strip()
    if not args:
        await event.reply("❌ `.cancelschedule <id_prefix>`\nList: `.schedules`"); return
    prefix = args.split()[0]
    matches = await sched_col.find({"owner_id": owner_id, "status": "pending", "_id": {"$regex": f"^{re.escape(prefix)}"}}).to_list(length=5)
    if not matches:
        await event.reply(f"❌ `{prefix}` se koi schedule nahi mila."); return
    doc = matches[0]
    await sched_col.update_one({"_id": doc["_id"]}, {"$set": {"status": "cancelled"}})
    try:
        cf_chat = doc.get("confirm_chat_id")
        cf_msg = doc.get("confirm_msg_id")
        if cf_chat and cf_msg: await client.delete_messages(int(cf_chat), [int(cf_msg)])
    except: pass
    await event.reply(f"✅ **Cancelled** `{doc['_id'][:8]}`\n📝 {doc['text'][:60]}")

@cmd('sync', delete_cmd=False)
async def sync_cmd(event):
    from config import PING_OFFSET
    import config
    msg = await event.reply("🔄 **Syncing... Calculating network latency...**")
    try:
        from telethon.tl.functions import PingRequest
        times = []
        for _ in range(5):
            start = time.perf_counter()
            await client(PingRequest(ping_id=random.randint(1, 10**9)))
            end = time.perf_counter()
            times.append(end - start)
            await asyncio.sleep(0.1)
        avg_ping = sum(times) / len(times)
        new_offset = avg_ping + 0.005
        config.PING_OFFSET = new_offset
        await msg.edit(f"✅ **Sync Complete!**\n📡 **Average Ping:** `{avg_ping * 1000:.1f} ms`\n⚙️ **New Offset:** `{new_offset * 1000:.1f} ms`", parse_mode='markdown')
    except Exception as e:
        await msg.edit(f"❌ **Sync Failed:** `{str(e)[:200]}`")

# ═══════════════ MUSIC ═══════════════
async def deezer_search(query, limit=1):
    try:
        url = f"https://api.deezer.com/search?q={url_quote(query)}&limit={limit}"
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200: return await resp.json()
    except: pass
    return None

@cmd('lyrics', delete_cmd=False)
async def lyrics_cmd(event):
    query = get_args(event.message)
    if not query:
        await event.reply("❌ Usage: `.lyrics <song name>`"); return
    msg = await event.reply("🎵 Searching lyrics...")
    async def fetch_lyrics(artist, title):
        try:
            url = f"https://api.lyrics.ovh/v1/{url_quote(artist)}/{url_quote(title)}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        return d.get("lyrics")
        except: pass
        return None
    try:
        deezer = await deezer_search(query, 3)
        if deezer and deezer.get("data"):
            for track in deezer["data"]:
                lyr = await fetch_lyrics(track["artist"]["name"], track["title"])
                if lyr:
                    await msg.edit(f"🎶 **{track['title']}** — {track['artist']['name']}\n\n{lyr[:3900]}")
                    return
        await msg.edit("❌ Lyrics not found.")
    except Exception as e:
        await msg.edit(f"❌ Error: `{str(e)[:150]}`")

# ═══════════════ T2I (AI IMAGE) ═══════════════
@cmd('t2i', delete_cmd=False)
async def t2i_cmd(event):
    prompt = get_args(event.message)
    if not prompt:
        await event.reply("❌ **Usage:** `.t2i <prompt>`"); return
    status = await event.reply("🎨 **Generating image...**")
    models_to_try = ["flux", "turbo"]
    img_data = None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
        for model in models_to_try:
            if img_data: break
            try:
                encoded = url_quote(prompt)
                url = f"https://image.pollinations.ai/prompt/{encoded}?nologo=true&width=1024&height=1024&model={model}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if data and len(data) > 5000:
                            img_data = data
                            break
            except: pass
    try:
        if not img_data:
            await status.edit("❌ Image generate nahi hui."); return
        img_path = TEMP_DIR / f"t2i_{int(time.time())}.jpg"
        img_path.write_bytes(img_data)
        try: await status.delete()
        except: pass
        await client.send_file(event.chat_id, str(img_path), reply_to=event.message.id)
        try: os.remove(img_path)
        except: pass
    except Exception as e:
        await status.edit(f"❌ Error: `{str(e)[:200]}`")

# ═══════════════ ANIMATIONS ═══════════════
@cmd('animate', delete_cmd=True)
async def animate_cmd(event):
    text = get_args(event.message)
    if not text:
        await event.reply("❌ Usage: `.animate <text>`"); return
    frames = ["🤍", "🦋", "🌸", "💖", "💝", "🎼", "😇", "✨"]
    msg = await send_anim(event, "🤍")
    try:
        for i in range(1, len(text) + 1):
            await msg.edit(text[:i] + " " + random.choice(frames))
            await asyncio.sleep(0.35)
        await msg.edit(f"💖 **{text}** 💖")
    except: pass

@cmd('matrix', delete_cmd=True)
async def matrix_cmd(event):
    secs = 8
    chars = "01アイウエオカキクケコサシスセソ"
    msg = await send_anim(event, "`01001000`")
    try:
        for i in range(secs * 2):
            line = "".join(random.choice(chars) for _ in range(14))
            await msg.edit(f"🟢 `{line}`")
            await asyncio.sleep(0.5)
        await msg.edit("🎭 **Welcome to the Villain World** 🎭")
    except: pass

# ═══════════════ FANCY TEXT ═══════════════
def _make_banner(word, font="big"):
    try:
        import pyfiglet
        banner = pyfiglet.figlet_format(word.upper(), font=font)
        if len(banner) > 3500: banner = banner[:3500] + "..."
        return f"🦋✨\n`{banner}`\n✨🦋"
    except Exception as e:
        return f"❌ Error: `{str(e)[:100]}`"

@cmd('text', delete_cmd=True)
async def text_cmd(event):
    text = get_args(event.message)
    if not text:
        await event.reply("❌ Usage: `.text <word>`"); return
    await reply_to_target(event, _make_banner(text))

# ═══════════════ WEATHER & AQI ═══════════════
@cmd('weather', owner_only=True, delete_cmd=False)
async def weather_cmd(event):
    city = get_args(event.message)
    if not city:
        await event.reply("❌ **Usage:** `.weather city`"); return
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    temp = data['main']['temp']
                    desc = data['weather'][0]['description'].title()
                    await event.reply(f"**Weather Report: {data['name']}**\n🌡️ Temp: {temp}°C\n📝 Condition: {desc}")
                else:
                    await event.reply(f"❌ City '{city}' not found.")
    except Exception as e:
        await event.reply(f"❌ Error: {str(e)[:100]}")

# ═══════════════ IMAGE TOOLS ═══════════════
@cmd('sticker', delete_cmd=False)
async def sticker_cmd(event):
    reply = await event.get_reply_message()
    if not reply or not reply.photo:
        await event.reply("❌ Reply to an image!"); return
    msg = await e
            answer = data["choices"][0]["message"]["content
