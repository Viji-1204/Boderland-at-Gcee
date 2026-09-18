"""Borderland @ GCEE - Round 2 API + the two static web apps.

    /                  -> /team-app/
    /team-app/         team phone app (Round 1 look & feel)
    /admin-app/        coordinator console
    /shared/           shared css / js / images
    /api/v1/...        REST API (docs at /api/docs)
    /api/v1/health     {"status": "ok", ...} when the server and database are up
    /ws/team, /ws/admin  WebSockets
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.api import admin, admin_setup, admin_teams, auth, leaderboard, power, puzzle, radar, scan, teams
from app.config import settings, validate_settings
from app.core.exceptions import register_exception_handlers
from app.services.sweeper import sweeper_loop
from app.services.websocket_service import hub
from app.websockets import ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("round2")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_settings()
    if settings.auto_migrate:
        from app.migrate import run_migrations

        await run_in_threadpool(run_migrations)
    from app.seed import startup_seed

    await run_in_threadpool(startup_seed)
    hub.bind_loop(asyncio.get_running_loop())
    stop = asyncio.Event()
    sweeper = asyncio.create_task(sweeper_loop(stop))
    db_label = settings.database_url.split("///")[-1] if settings.is_sqlite else settings.database_url.split("@")[-1]
    logger.info("Round 2 ready - database: %s", db_label)
    try:
        yield
    finally:
        stop.set()
        await sweeper


app = FastAPI(
    title="Borderland @ GCEE - Round 2",
    version="2.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url=f"{API_PREFIX}/openapi.json",
)
register_exception_handlers(app)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

for router in (auth, teams, scan, puzzle, radar, power, leaderboard, admin, admin_setup, admin_teams):
    app.include_router(router.router, prefix=API_PREFIX)
app.include_router(ws_router.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/team-app/")


@app.get("/team", include_in_schema=False)
@app.get("/team-app", include_in_schema=False)
def team_redirect():
    return RedirectResponse(url="/team-app/")


@app.get("/admin", include_in_schema=False)
@app.get("/admin-app", include_in_schema=False)
def admin_redirect():
    return RedirectResponse(url="/admin-app/")


class RevalidatingStaticFiles(StaticFiles):
    """Code and pages revalidate on every load (cheap 304s via ETag), so a
    redeploy reaches every phone at once. Images may be cached."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".html", ".js", ".css", ".webmanifest")) or path in ("", "."):
            response.headers["Cache-Control"] = "no-cache"
        return response


frontend = Path(settings.frontend_dir)
if frontend.exists():
    for mount, folder in (("/shared", "shared"), ("/team-app", "team-app"), ("/admin-app", "admin-app")):
        if (frontend / folder).exists():
            app.mount(mount, RevalidatingStaticFiles(directory=frontend / folder, html=True), name=folder)
else:  # pragma: no cover
    logger.warning("Frontend folder not found at %s - serving the API only.", frontend)
