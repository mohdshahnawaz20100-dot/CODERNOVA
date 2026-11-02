import time
import random
import logging
import asyncio
from datetime import datetime
from telethon.errors import FloodWaitError
from config import IST_TZ, PING_OFFSET
from database import sched_col

log = logging.getLogger("CN_SCHED")


def _parse_schedule_time(date_str, time_str):
    date_str = date_str.strip()
    dt_date = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            dt_date = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    if dt_date is None:
        raise ValueError("Date `YYYY-MM-DD` ya `DD-MM-YYYY` format me do")
    time_str = time_str.strip().upper().replace(".", "")
    dt_time = None
    if "AM" in time_str or "PM" in time_str:
        for fmt in ("%I:%M:%S %p", "%I:%M %p", "%I %p"):
            try:
                dt_time = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue
        if dt_time is None:
            raise ValueError("12-hour format: `hh:MM:SS AM/PM` ya `hh:MM AM/PM`")
    else:
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                dt_time = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue
        if dt_time is None:
            raise ValueError("24-hour format: `HH:MM:SS` ya `HH:MM`")
    return dt_date.replace(
        hour=dt_time.hour, minute=dt_time.minute, second=dt_time.second,
        tzinfo=IST_TZ,
    )


def _fmt_ist_12h(ts):
    return datetime.fromtimestamp(ts, IST_TZ).strftime("%I:%M:%S %p IST")


def _fmt_ist_full(ts):
    return datetime.fromtimestamp(ts, IST_TZ).strftime("%d %b %Y, %I:%M:%S %p IST")


async def _scheduler_runner(client, doc):
    try:
        target_ts = float(doc["scheduled_ts"])
        fire_ts = target_ts - PING_OFFSET
        while True:
            diff = fire_ts - time.time()
            if diff <= 2.0:
                break
            if diff > 120:
                await asyncio.sleep(min(60, diff - 10))
            elif diff > 10:
                await asyncio.sleep(2.0)
            elif diff > 2:
                await asyncio.sleep(0.3)
        if sched_col is None:
            return
        fresh = await sched_col.find_one({"_id": doc["_id"]})
        if not fresh or fresh.get("status") != "pending":
            return
        send_text = fresh["text"]
        target = fresh["target_id"]
        comment_to = fresh.get("comment_to")
        reply_to = fresh.get("reply_to_msg_id")
        try:
            from telethon.tl.functions import PingRequest
            await asyncio.wait_for(
                client(PingRequest(ping_id=random.randint(1, 10 ** 9))),
                timeout=1.5,
            )
        except Exception:
            pass

        async def _real_send():
            try:
                if comment_to:
                    try:
                        await client.send_message(target, send_text, comment_to=int(comment_to))
                    except Exception:
                        await client.send_message(target, send_text)
                elif reply_to:
                    try:
                        await client.send_message(target, send_text, reply_to=reply_to)
                    except Exception:
                        await client.send_message(target, send_text)
                else:
                    await client.send_message(target, send_text)
                await sched_col.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"status": "sent", "sent_at": time.time()}},
                )
                log.info(f"⚡ Scheduled msg {doc['_id'][:8]} SENT "
                         f"(drift: {(time.time() - target_ts) * 1000:.1f}ms)")
                cf_chat = fresh.get("confirm_chat_id")
                cf_msg = fresh.get("confirm_msg_id")
                if cf_chat and cf_msg:
                    await client.delete_messages(int(cf_chat), [int(cf_msg)])
            except FloodWaitError as e:
                log.warning(f"⏰ FloodWait {e.seconds}s, retrying...")
                await asyncio.sleep(e.seconds)
                await client.send_message(target, send_text)
            except Exception as e:
                log.error(f"⏰ Send failed: {e}")
                await sched_col.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"status": "failed", "error": str(e)[:200]}},
                )

        while True:
            remaining = fire_ts - time.time()
            if remaining <= 0:
                break
            if remaining > 0.1:
                await asyncio.sleep(0.01)
            else:
                await asyncio.sleep(0)
        asyncio.create_task(_real_send())
    except Exception as e:
        log.error(f"_scheduler_runner error: {e}", exc_info=True)


async def _restore_schedules_on_startup(client, owner_id):
    if sched_col is None:
        return
    try:
        cursor = sched_col.find({
            "owner_id": owner_id,
            "status": "pending",
            "scheduled_ts": {"$gt": time.time() - 300},
        })
        docs = await cursor.to_list(length=200)
        for d in docs:
            asyncio.create_task(_scheduler_runner(client, d))
        if docs:
            log.info(f"⏰ Restored {len(docs)} scheduled message(s) for {owner_id}")
    except Exception as e:
        log.warning(f"_restore_schedules_on_startup: {e}")
