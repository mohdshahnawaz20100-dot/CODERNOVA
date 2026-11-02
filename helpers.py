import asyncio
import logging
import time
import aiohttp
from config import TEMP_DIR, GHOST_IMG_LOCAL, GHOST_IMG_URL
from database import cleanup_old_command_logs

log = logging.getLogger("CN_HELPERS")


async def get_ghost_image_path():
    if GHOST_IMG_LOCAL.exists() and GHOST_IMG_LOCAL.stat().st_size > 1000:
        return str(GHOST_IMG_LOCAL)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(GHOST_IMG_URL) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 1000:
                        with open(GHOST_IMG_LOCAL, "wb") as f:
                            f.write(data)
                        return str(GHOST_IMG_LOCAL)
    except Exception as e:
        log.warning(f"Ghost image download failed: {e}")
    return None


async def cleanup_temp_loop():
    while True:
        try:
            now = time.time()
            for f in TEMP_DIR.glob("*"):
                if f.is_file() and now - f.stat().st_mtime > 3600:
                    try:
                        f.unlink()
                    except Exception:
                        pass
        except Exception as e:
            log.error(f"Temp cleanup: {e}")
        await asyncio.sleep(3600)


async def auto_cleanup_loop():
    while True:
        try:
            await cleanup_old_command_logs()
        except Exception as e:
            log.error(f"auto_cleanup_loop: {e}")
        await asyncio.sleep(24 * 60 * 60)
