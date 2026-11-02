import os
import asyncio
import logging
from aiohttp import web

log = logging.getLogger("CN_HEALTH")


async def health_server():
    async def handle(request):
        return web.Response(text="✅ Codernova Multi-User Userbot Running")

    app = web.Application()
    app.router.add_get('/', handle)
    app.router.add_get('/health', handle)

    port = int(os.getenv('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    log.info(f"✅ Health on port {port}")
    await asyncio.Event().wait()
