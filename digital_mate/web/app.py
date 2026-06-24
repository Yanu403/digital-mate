"""FastAPI application for Digital Mate web dashboard.

Provides REST API endpoints for bot management, settings,
brand profile editing, and real-time log streaming via WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

# Project root (where .env lives)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).parent / "static"


class BotProcessManager:
    """Manages the bot subprocess lifecycle."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._start_time: float | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def pid(self) -> int | None:
        if self._process is not None and self._process.returncode is None:
            return self._process.pid
        return None

    @property
    def uptime(self) -> float | None:
        if self._start_time and self.is_running:
            return time.time() - self._start_time
        return None

    async def start(self) -> dict[str, Any]:
        if self.is_running:
            return {"status": "already_running", "pid": self.pid}

        python = sys.executable
        env = os.environ.copy()

        self._process = await asyncio.create_subprocess_exec(
            python, "-m", "digital_mate",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        self._start_time = time.time()
        logger.info("Bot process started (pid=%s)", self._process.pid)
        return {"status": "started", "pid": self._process.pid}

    async def stop(self) -> dict[str, Any]:
        if not self.is_running or self._process is None:
            return {"status": "not_running"}

        pid = self._process.pid
        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass

        self._process = None
        self._start_time = None
        logger.info("Bot process stopped (pid=%s)", pid)
        return {"status": "stopped", "pid": pid}

    def status(self) -> dict[str, Any]:
        if self.is_running:
            uptime = self.uptime
            return {
                "status": "running",
                "pid": self.pid,
                "uptime_seconds": round(uptime, 1) if uptime else None,
            }
        return {"status": "stopped"}


class LogBuffer:
    """Ring buffer for log messages, also broadcasts to WebSocket clients."""

    def __init__(self, max_size: int = 500) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._subscribers: list[WebSocket] = []

    def add(self, level: str, message: str, logger_name: str = "") -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "logger": logger_name,
            "message": message,
        }
        self._buffer.append(entry)
        for ws in list(self._subscribers):
            try:
                asyncio.get_event_loop().create_task(ws.send_json(entry))
            except Exception:
                self._subscribers.remove(ws)

    def get_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        items = list(self._buffer)
        return items[-limit:]

    def subscribe(self, ws: WebSocket) -> None:
        self._subscribers.append(ws)

    def unsubscribe(self, ws: WebSocket) -> None:
        if ws in self._subscribers:
            self._subscribers.remove(ws)


# Module-level singletons
bot_manager = BotProcessManager()
log_buffer = LogBuffer()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance.
    """
    from digital_mate.web.settings_service import SettingsService
    from digital_mate.web.brand_service import BrandService
    from digital_mate.web.stats_service import StatsService

    settings_service = SettingsService(PROJECT_ROOT)
    _brand_service: BrandService | None = None
    _stats_service: StatsService | None = None

    app = FastAPI(
        title="Digital Mate Dashboard",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.on_event("startup")
    async def _startup() -> None:
        nonlocal _brand_service, _stats_service
        db_path = settings_service.get("DB_PATH", "data/digital_mate.db")
        abs_db_path = PROJECT_ROOT / db_path
        if abs_db_path.exists():
            from digital_mate.memory.database import init_db

            db = await init_db(str(abs_db_path))
            _brand_service = BrandService(db)
            _stats_service = StatsService(db)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if _stats_service is not None:
            await _stats_service.close()
        if _brand_service is not None:
            await _brand_service.close()

    # --- Static files & index ---
    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Dashboard not found</h1>", status_code=500)

    # --- Health ---
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}

    # --- Bot status ---
    @app.get("/api/status")
    async def get_status():
        return bot_manager.status()

    # --- Bot start/stop ---
    @app.post("/api/bot/start")
    async def start_bot():
        result = await bot_manager.start()
        return result

    @app.post("/api/bot/stop")
    async def stop_bot():
        result = await bot_manager.stop()
        return result

    # --- Settings ---
    @app.get("/api/settings")
    async def get_settings():
        return settings_service.get_all_redacted()

    @app.post("/api/settings")
    async def save_settings(data: dict[str, Any]):
        try:
            settings_service.save(data)
            return {"status": "saved"}
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={"error": str(exc)},
            )

    # --- Stats ---
    @app.get("/api/stats")
    async def get_stats():
        if _stats_service is None:
            return {
                "total_messages": 0,
                "active_users": 0,
                "plans_created": 0,
                "feedback_score": 0.0,
                "recent_activity": [],
            }
        return await _stats_service.get_stats()

    # --- Brand profiles ---
    @app.get("/api/brand")
    async def get_brand(chat_id: int = 0):
        if _brand_service is None:
            return {"profiles": []}
        if chat_id:
            profile = await _brand_service.get(chat_id)
            return profile if profile else {}
        return {"profiles": await _brand_service.list_all()}

    @app.post("/api/brand")
    async def save_brand(data: dict[str, Any]):
        if _brand_service is None:
            return JSONResponse(
                status_code=503,
                content={"error": "Database not initialized"},
            )
        try:
            await _brand_service.create_or_update(data)
            return {"status": "saved"}
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={"error": str(exc)},
            )

    # --- Logs ---
    @app.get("/api/logs")
    async def get_logs(limit: int = 100):
        return log_buffer.get_recent(limit)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        log_buffer.subscribe(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            log_buffer.unsubscribe(ws)

    return app
