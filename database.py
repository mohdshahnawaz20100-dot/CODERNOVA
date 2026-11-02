import time
import logging
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, CLEANUP_DAYS

log = logging.getLogger("CN_DB")

mongo_client = None
users_col = None
all_users_col = None
user_data_col = None
blocked_col = None
cmd_usage_col = None
cmd_blocked_col = None
sched_col = None

users_db = {}
all_users_db = {}
user_data_cache = {}
blocked_users = set()
command_usage_db = {}
command_blocked_db = {}


async def init_mongo():
    global mongo_client, users_col, all_users_col, user_data_col
    global blocked_col, cmd_usage_col, cmd_blocked_col, sched_col
    if not MONGO_URI:
        log.warning("⚠️ MONGO_URI not set")
        return False
    try:
        mongo_client = AsyncIOMotorClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=45000,
            maxPoolSize=25,
        )
        db = mongo_client["clonex_db"]
        users_col = db["logged_users"]
        all_users_col = db["all_users"]
        user_data_col = db["user_data"]
        blocked_col = db["blocked_users"]
        cmd_usage_col = db["command_usage"]
        cmd_blocked_col = db["command_blocked"]
        sched_col = db["scheduled_messages"]
        await mongo_client.admin.command('ping')
        log.info("✅ MongoDB connected")
        return True
    except Exception as e:
        log.error(f"❌ MongoDB: {e}")
        return False


async def load_all():
    global users_db, all_users_db, user_data_cache, blocked_users
    global command_usage_db, command_blocked_db
    if users_col is None:
        return
    try:
        users_db = {}
        async for d in users_col.find({}):
            uid = d.get("_id"); d.pop("_id", None); users_db[str(uid)] = d
        all_users_db = {}
        async for d in all_users_col.find({}):
            uid = d.get("_id"); d.pop("_id", None); all_users_db[str(uid)] = d
        user_data_cache = {}
        async for d in user_data_col.find({}):
            uid = d.get("_id"); d.pop("_id", None); user_data_cache[str(uid)] = d
        blocked_users = set()
        if blocked_col is not None:
            async for d in blocked_col.find({}):
                blocked_users.add(str(d.get("_id")))
        command_usage_db = {}
        if cmd_usage_col is not None:
            async for d in cmd_usage_col.find({}):
                uid = str(d.get("_id"))
                d.pop("_id", None)
                if "commands" in d:
                    command_usage_db[uid] = {
                        "commands": d.get("commands", {}),
                        "last_update": d.get("last_update", time.time()),
                    }
                else:
                    last_update = d.pop("last_update", time.time())
                    command_usage_db[uid] = {"commands": d, "last_update": last_update}
        command_blocked_db = {}
        if cmd_blocked_col is not None:
            async for d in cmd_blocked_col.find({}):
                uid = str(d.get("_id"))
                command_blocked_db[uid] = d.get("commands", [])
        log.info(f"✅ Loaded {len(users_db)} logged, {len(all_users_db)} all, "
                 f"{len(user_data_cache)} user_data, {len(blocked_users)} blocked")
    except Exception as e:
        log.error(f"load_all: {e}")


async def save_user(uid, data):
    if users_col is None: return
    try:
        d = dict(data); d["_id"] = str(uid)
        await users_col.update_one({"_id": str(uid)}, {"$set": d}, upsert=True)
    except Exception as e:
        log.error(f"save_user: {e}")


async def save_all_user(uid, data):
    if all_users_col is None: return
    try:
        d = dict(data); d["_id"] = str(uid)
        await all_users_col.update_one({"_id": str(uid)}, {"$set": d}, upsert=True)
    except Exception as e:
        log.error(f"save_all_user: {e}")


async def save_user_data(uid, data):
    if user_data_col is None: return
    try:
        d = dict(data); d["_id"] = str(uid)
        await user_data_col.update_one({"_id": str(uid)}, {"$set": d}, upsert=True)
    except Exception as e:
        log.error(f"save_user_data: {e}")


async def block_user_db(uid):
    uid = str(uid)
    blocked_users.add(uid)
    if blocked_col is not None:
        try:
            await blocked_col.update_one(
                {"_id": uid},
                {"$set": {"blocked_at": datetime.now().strftime("%d %b %Y, %I:%M %p")}},
                upsert=True,
            )
        except Exception as e:
            log.error(f"block_user_db: {e}")


async def unblock_user_db(uid):
    uid = str(uid)
    blocked_users.discard(uid)
    if blocked_col is not None:
        try:
            await blocked_col.delete_one({"_id": uid})
        except Exception as e:
            log.error(f"unblock_user_db: {e}")


async def log_command_usage(uid, command):
    uid = str(uid)
    try:
        if uid not in command_usage_db:
            command_usage_db[uid] = {"commands": {}, "last_update": time.time()}
        if "commands" not in command_usage_db[uid] or not isinstance(
            command_usage_db[uid].get("commands"), dict
        ):
            command_usage_db[uid] = {
                "commands": command_usage_db[uid] if isinstance(command_usage_db[uid], dict) else {},
                "last_update": time.time(),
            }
        command_usage_db[uid]["commands"][command] = (
            command_usage_db[uid]["commands"].get(command, 0) + 1
        )
        command_usage_db[uid]["last_update"] = time.time()
        if cmd_usage_col is not None:
            await cmd_usage_col.update_one(
                {"_id": uid},
                {"$inc": {f"commands.{command}": 1},
                 "$set": {"last_update": time.time()}},
                upsert=True,
            )
    except Exception as e:
        log.error(f"log_command_usage: {e}")


async def cleanup_old_command_logs():
    global command_usage_db
    if cmd_usage_col is None: return
    try:
        cutoff_time = time.time() - (CLEANUP_DAYS * 24 * 60 * 60)
        result = await cmd_usage_col.delete_many({"last_update": {"$lt": cutoff_time}})
        if result.deleted_count > 0:
            log.info(f"🧹 Cleaned {result.deleted_count} old command logs")
            to_remove = []
            for uid, data in command_usage_db.items():
                last_update = data.get("last_update", 0) if isinstance(data, dict) else 0
                if not last_update or last_update < cutoff_time:
                    to_remove.append(uid)
            for uid in to_remove:
                command_usage_db.pop(uid, None)
    except Exception as e:
        log.error(f"cleanup_old_command_logs: {e}")


def get_user(uid):
    uid = str(uid)
    if uid not in users_db:
        users_db[uid] = {
            "logged_in": False, "phone": None, "tg_id": None, "tg_name": None,
            "tg_username": None, "session_string": None, "step": None,
            "phone_code_hash": None, "login_time": None,
        }
    return users_db[uid]


def get_user_data(uid):
    uid = str(uid)
    if uid not in user_data_cache:
        user_data_cache[uid] = {}
    return user_data_cache[uid]


async def track_start(uid, name, username):
    uid = str(uid)
    if uid not in all_users_db:
        all_users_db[uid] = {
            "name": name, "username": username, "tg_id": uid,
            "first_seen": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        }
        await save_all_user(uid, all_users_db[uid])
