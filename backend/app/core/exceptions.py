"""Application errors and their HTTP mapping (same shape as Round 1).

Services raise these; the handlers turn them into ``{"detail": "..."}``
responses. Database constraint violations are translated into friendly
messages and never leak SQL text to the client.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

logger = logging.getLogger("round2.errors")


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str, status_code: int | None = None, extra: dict | None = None):
        self.detail = detail
        self.extra = extra or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


# Postgres reports the constraint name; SQLite reports the column list.
# Both spellings are listed so the message is the same on either database.
_CONSTRAINT_MESSAGES: list[tuple[tuple[str, ...], str]] = [
    (("uq_team_event_code", "teams.event_id, teams.team_code"), "That team code is already used in this event."),
    (("uq_team_event_name", "teams.event_id, teams.team_name"), "That team name is already used in this event."),
    (("uq_location_event_code", "locations.event_id, locations.code"), "That location code is already used in this event."),
    (("uq_location_qr_token", "locations.qr_token"), "QR token collision - please try again."),
    (("uq_admin_username", "admins.username"), "That username is already taken."),
    (("uq_route_team_face_card", "route_stops.team_id, route_stops.face_card"), "That team already holds that face card on another checkpoint."),
    (("uq_route_team_seq", "uq_route_team_location", "route_stops."), "That route conflicts with an existing route entry."),
    (("uq_idempotency_team_key", "idempotency_keys."), "This request was already processed."),
    (("uq_power_event_kind", "powers.event_id, powers.kind"), "That power is already configured."),
]


def _integrity_message(exc: IntegrityError) -> str:
    text = str(getattr(exc, "orig", exc))
    for needles, message in _CONSTRAINT_MESSAGES:
        if any(n in text for n in needles):
            return message
    if "unique" in text.lower():
        return "This conflicts with an existing record."
    if "foreign key" in text.lower():
        return "This refers to something that no longer exists."
    return "The request violates a database constraint."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        body = {"detail": exc.detail}
        body.update(exc.extra)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError):
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": _integrity_message(exc)})

    @app.exception_handler(DBAPIError)
    async def _dbapi(request: Request, exc: DBAPIError):
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The database is busy or unavailable. Please retry."},
        )
