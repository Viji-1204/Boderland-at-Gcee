"""Request bodies. Responses are plain dicts built by the services."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PowerKindLiteral = Literal["GUIDE", "FREEZE", "JAM", "TRAP", "SHIELD", "REFLECT", "WARD"]
AttackKindLiteral = Literal["FREEZE", "JAM", "TRAP"]
DefenceKindLiteral = Literal["SHIELD", "REFLECT"]
IdemKey = Field(default=None, max_length=80)


# --- auth -------------------------------------------------------------------
class TeamLoginIn(BaseModel):
    team_code: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


# --- team gameplay ---------------------------------------------------------------
class ScanIn(BaseModel):
    code: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = IdemKey
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=100000)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = IdemKey


class PuzzlePlayIn(BaseModel):
    """One move on the open built-in puzzle - only the field its type uses."""

    answer: str | None = Field(default=None, max_length=255)  # scrambled words, riddle
    move: str | int | None = None  # rock-paper-scissors throw, or an X/O square 0-8
    swaps: list[list[int]] | None = Field(default=None, max_length=400)  # picture puzzle
    grid: list[str] | None = Field(default=None, max_length=20)  # crossword rows
    idempotency_key: str | None = IdemKey


class PurchaseIn(BaseModel):
    kind: PowerKindLiteral
    quantity: int = Field(default=1, ge=1, le=10)
    idempotency_key: str | None = IdemKey


class AttackIn(BaseModel):
    kind: AttackKindLiteral = "FREEZE"
    target_team_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str | None = IdemKey


class DefendIn(BaseModel):
    usage_id: str = Field(min_length=1, max_length=36)
    defence: DefenceKindLiteral | None = None  # None = accept the attack
    idempotency_key: str | None = IdemKey


class ActionIn(BaseModel):
    """A power used on yourself (Guide, Ward): nothing to say but the retry key."""

    idempotency_key: str | None = IdemKey


# --- admin: events -------------------------------------------------------------
class EventCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    clone_from_event_id: str | None = None


class RestartIn(BaseModel):
    # True: teams get their starting points back and shop again. False: they
    # keep what they bought, with every use reset.
    refund_powers: bool = False


class EventUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    settings: dict | None = None
    final_location_name: str | None = Field(default=None, max_length=120)
    final_latitude: float | None = Field(default=None, ge=-90, le=90)
    final_longitude: float | None = Field(default=None, ge=-180, le=180)


# --- admin: setup --------------------------------------------------------------
class LocationIn(BaseModel):
    code: str = Field(pattern=r"^L(0[1-9]|1[0-5])$")
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    geofence_radius_m: float = Field(default=40, ge=5, le=500)
    is_selected: bool = True


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: float | None = Field(default=None, ge=5, le=500)
    is_selected: bool | None = None


class PowerPriceIn(BaseModel):
    kind: PowerKindLiteral
    cost: int = Field(ge=0, le=100000)
    max_per_team: int = Field(ge=0, le=20)
    active: bool = True


class RouteIn(BaseModel):
    location_ids: list[str] = Field(min_length=1, max_length=15)
    # JACK / QUEEN / KING -> location id. Left out: keep the team's current
    # cards if it has all three, otherwise deal them at random.
    face_cards: dict[Literal["JACK", "QUEEN", "KING"], str] | None = None


# --- admin: teams --------------------------------------------------------------
class TeamCreateIn(BaseModel):
    team_name: str = Field(min_length=1, max_length=120)
    team_code: str | None = Field(default=None, max_length=40)
    password: str | None = Field(default=None, max_length=128)
    leader_name: str | None = Field(default=None, max_length=120)
    leader_phone: str | None = Field(default=None, max_length=32)
    leader_email: str | None = Field(default=None, max_length=160)
    sentence: str | None = Field(default=None, max_length=1000)


class TeamPatchIn(BaseModel):
    team_name: str | None = Field(default=None, min_length=1, max_length=120)
    leader_name: str | None = Field(default=None, max_length=120)
    leader_phone: str | None = Field(default=None, max_length=32)
    leader_email: str | None = Field(default=None, max_length=160)
    sentence: str | None = Field(default=None, max_length=1000)


class PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)


class ImportRowIn(BaseModel):
    # Same limits as the database columns (Postgres enforces them; SQLite doesn't).
    team_name: str = Field(max_length=120)
    leader_name: str = Field(default="", max_length=120)
    leader_phone: str = Field(default="", max_length=32)
    leader_email: str = Field(default="", max_length=160)
    team_code: str = Field(default="", max_length=40)
    password: str = Field(default="", max_length=128)
    sentence: str = Field(default="", max_length=1000)


class ImportCommitIn(BaseModel):
    rows: list[ImportRowIn] = Field(max_length=200)


class ImportedTeamOut(BaseModel):
    team_id: str
    team_code: str
    team_name: str
    password: str
    leader_name: str | None = None
    leader_phone: str | None = None
    leader_email: str | None = None


class ImportCommitOut(BaseModel):
    created_count: int
    teams: list[ImportedTeamOut]


# --- admin: live controls ---------------------------------------------------------
class FoulIn(BaseModel):
    action: Literal["add", "remove"]
    reason: str = Field(default="", max_length=300)


class FreezeIn(BaseModel):
    duration_s: int = Field(default=120, ge=10, le=3600)


class ReasonIn(BaseModel):
    reason: str = Field(default="", max_length=300)


# --- admin accounts (Round 1 screen) -------------------------------------------------
class AdminAccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=6, max_length=128)
    role: Literal["SUPER_ADMIN", "COORDINATOR"] = "COORDINATOR"
