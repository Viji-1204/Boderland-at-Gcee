"""Authenticated WebSockets (the old ones accepted anyone).

    /ws/team?token=<team jwt>                      -> team:{id} + event:{event}
    /ws/admin?token=<admin jwt>&event_id=<event>   -> coord:{event} + event:{event}

A bad token is closed with code 4001, which Round 1's ws.js treats as
"don't retry".
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.security import decode_token, password_fingerprint
from app.core.timeutil import iso, utcnow
from app.database import SessionLocal
from app.models import Admin, Event, Team
from app.services.websocket_service import coord_channel, event_channel, hub, team_channel

router = APIRouter()

WS_AUTH_FAILED = 4001


def _team_channels(token: str) -> list[str] | None:
    try:
        claims = decode_token(token)
    except ValueError:
        return None
    if claims.get("type") != "team":
        return None
    with SessionLocal() as db:
        team = db.get(Team, claims.get("sub"))
        if team is None or claims.get("pwv") != password_fingerprint(team.password_hash):
            return None
        return [team_channel(team.id), event_channel(team.event_id)]


def _admin_channels(token: str, event_id: str) -> list[str] | None:
    try:
        claims = decode_token(token)
    except ValueError:
        return None
    if claims.get("type") != "admin":
        return None
    with SessionLocal() as db:
        admin = db.get(Admin, claims.get("sub"))
        if admin is None or not admin.is_active or claims.get("pwv") != password_fingerprint(admin.password_hash):
            return None
        if db.get(Event, event_id) is None:
            return None
        return [coord_channel(event_id), event_channel(event_id)]


async def _serve(websocket: WebSocket, channels: list[str] | None) -> None:
    await websocket.accept()
    if not channels:
        await websocket.close(code=WS_AUTH_FAILED, reason="Invalid or expired token")
        return
    hub.register(websocket, channels)
    try:
        await websocket.send_json({"type": "hello", "server_now": iso(utcnow())})
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(websocket)


@router.websocket("/ws/team")
async def team_socket(websocket: WebSocket, token: str = ""):
    await _serve(websocket, await run_in_threadpool(_team_channels, token))


@router.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket, token: str = "", event_id: str = ""):
    await _serve(websocket, await run_in_threadpool(_admin_channels, token, event_id))
