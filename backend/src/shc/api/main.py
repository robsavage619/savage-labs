from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shc.api.middleware import HostOriginMiddleware
from shc.api.routers import auth, chat, dashboard
from shc.config import settings
from shc.db.schema import init_db
from shc.ingest.apple import start_watcher, stop_watcher
from shc.scheduler.jobs import get_scheduler, register_jobs

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    init_db()
    loop = asyncio.get_running_loop()
    start_watcher(loop)
    scheduler = get_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    log.info("SHC backend started")
    yield
    # ── shutdown ──
    scheduler.shutdown(wait=False)
    stop_watcher()
    log.info("SHC backend stopped")


app = FastAPI(title="Savage Health Center", lifespan=lifespan)

app.add_middleware(HostOriginMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth")
app.include_router(dashboard.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/readyz")
async def readyz() -> JSONResponse:
    from shc.db.schema import get_read_conn

    try:
        conn = get_read_conn()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    status = "ok" if db_ok else "degraded"
    return JSONResponse({"status": status, "db": db_ok}, status_code=200 if db_ok else 503)
