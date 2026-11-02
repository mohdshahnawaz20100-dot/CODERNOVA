import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_ID       = int(os.getenv("API_ID", "0"))
API_HASH     = os.getenv("API_HASH", "")
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
OWNER_ID     = int(os.getenv("OWNER_ID", "0"))
MONGO_URI    = os.getenv("MONGO_URI", "")

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
NEWS_API_KEY    = os.getenv("NEWS_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")

DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/clonex_data"))
DATA_DIR.mkdir(exist_ok=True, parents=True)
TEMP_DIR = DATA_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True, parents=True)

SESSION_DIR = Path("/tmp/clonex_session")
SESSION_DIR.mkdir(exist_ok=True, parents=True)

GHOST_IMG_LOCAL = DATA_DIR / "ghost_cached.jpg"
GHOST_IMG_URL = "https://i.ibb.co/MDZVcWjh/IMG-20260921-203641-296.jpg"

CLEANUP_DAYS = 45
PING_OFFSET = 0.090

try:
    from zoneinfo import ZoneInfo
    IST_TZ = ZoneInfo("Asia/Kolkata")
except ImportError:
    from backports.zoneinfo import ZoneInfo
    IST_TZ = ZoneInfo("Asia/Kolkata")

if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
    raise SystemExit("❌ BOT_TOKEN missing in .env")
if not API_ID or not API_HASH:
    raise SystemExit("❌ API_ID/API_HASH missing in .env")
if not OWNER_ID:
    raise SystemExit("❌ OWNER_ID missing in .env")
