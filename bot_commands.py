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
    cmd_blocked_col,
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
            from database import track_start
            await track_start(uid, name, s.username or "None")
        except Exception:
            pass
        START_MEDIA = "https://files.catbox.moe/35bl05.mp4"
        if u["logged_in"]:
            caption = ("✅ **ᴀʟʀᴇᴀᴅʏ ʟᴏɢɢᴇᴅ ɪɴ!**\n"
                       "━━━━━━━━━━━━━━━━━━━━━\n\n"
                       "**🔹 ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅs**\n"
                       "• `/help` — ʜᴇʟᴘ ᴍᴇ
