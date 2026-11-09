from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()


async def _keep_alive_loop() -> None:
    """Periodically pings the public external URL to prevent free-tier hosts

    (e.g. Render, Railway) from spinning down or sleeping after inactivity.
    Render automatically provides RENDER_EXTERNAL_URL in its environment.
    """
    external_url = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("SELF_URL")
        or os.environ.get("SERVER_PUBLIC_URL")
    )
    if not external_url:
        return

    target = f"{external_url.rstrip('/')}/api/v1/system/health"
    # Initial pause after container boot
    await asyncio.sleep(120)

    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.get(target)
        except Exception:
            pass
        # Ping every 8 minutes (480s) to comfortably beat Render's 15-minute idle limit
        await asyncio.sleep(480)


@asynccontextmanager
async def lifespan(app: FastAPI):
    keep_alive_task = asyncio.create_task(_keep_alive_loop())
    try:
        yield
    finally:
        keep_alive_task.cancel()
        try:
            await keep_alive_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="SatQuery AI",
    description="Agentic vision-language assistant for multimodal remote-sensing analysis.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def root() -> dict:
    return {"name": "SatQuery AI", "demo_mode": settings.demo_mode, "docs": "/docs"}
