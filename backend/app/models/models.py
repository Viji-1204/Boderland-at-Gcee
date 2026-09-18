"""Round 2 data model (spec section 24), portable across SQLite and Postgres.

Simplifications versus the spec's representative schema, all deliberate:

* A location's QR token lives on the ``locations`` row (the spec's
  ``qr_codes`` table was strictly 1:1 with it).
* The Jack, Queen and King are dealt per team: each sits on one of the
  team's ``route_stops`` (chosen at random when routes are generated), so
  two teams meet them at different checkpoints. A team's Jack/Queen/King
  progress lives on the ``teams`` row.
* A freeze is a timestamp (``teams.frozen_until``), not a status. The team
  keeps its real status underneath, so being frozen while a puzzle is open
  can't lose the puzzle lock. The API reports status ``FROZEN`` while it
  lasts.
* A sentence fragment is "revealed" when its route position has been
  verified (``seq <= teams.progress``), so no revealed flag can drift.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutil import utcnow
from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


class EventStatus:
    DRAFT = "DRAFT"
    CONFIGURED = "CONFIGURED"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class TeamStatus:
    NOT_STARTED = "NOT_STARTED"
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    PUZZLE_LOCKED = "PUZZLE_LOCKED"
    FINAL = "FINAL"  # every checkpoint done - heading to the Joker
    COMPLETED = "COMPLETED"
    DISQUALIFIED = "DISQUALIFIED"
    FROZEN = "FROZEN"  # derived from frozen_until, never stored

    PLAYING = (ACTIVE, PUZZLE_LOCKED, FINAL)


class AdminRole:
    SUPER_ADMIN = "SUPER_ADMIN"
    COORDINATOR = "COORDINATOR"
    ALL = (SUPER_ADMIN, COORDINATOR)


class FaceCard:
    JACK = "JACK"
    QUEEN = "QUEEN"
    KING = "KING"
    ORDER = (JACK, QUEEN, KING)


class PowerKind:
    HELP = "HELP"
    ATTACK = "ATTACK"
    DEFENCE = "DEFENCE"
    ALL = (HELP, ATTACK, DEFENCE)


class UsageStatus:
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"  # attack accepted - target frozen
    CANCELLED = "CANCELLED"  # attack blocked with Defence
    EXPIRED = "EXPIRED"  # no response in time - target frozen
    USED = "USED"  # a Defence / Help use, logged for the coordinator


class HelpStatus:
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    OPEN = (PENDING, ACKNOWLEDGED)


class ScanResult:
    VALID = "VALID"
    WRONG_QR = "WRONG_QR"
    REPEAT = "REPEAT"
    INVALID = "INVALID"  # not a code of this game - no foul
    LOCKED = "LOCKED"  # a puzzle must be solved first - no foul
    BLOCKED = "BLOCKED"  # geofence (block mode) rejected the scan - no foul


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default=EventStatus.DRAFT, index=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    final_location_name: Mapped[str] = mapped_column(String(120), default="Coordinator's Bench")
    final_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    config_locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    teams: Mapped[list["Team"]] = relationship(back_populates="event", cascade="all, delete-orphan", passive_deletes=True)
    locations: Mapped[list["Location"]] = relationship(back_populates="event", cascade="all, delete-orphan", passive_deletes=True)


class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (UniqueConstraint("username", name="uq_admin_username"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=AdminRole.COORDINATOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("event_id", "code", name="uq_location_event_code"),
        UniqueConstraint("qr_token", name="uq_location_qr_token"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(10))  # L01..L15
    name: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float, default=0.0)
    longitude: Mapped[float] = mapped_column(Float, default=0.0)
    geofence_radius_m: Mapped[float] = mapped_column(Float, default=40.0)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True)
    qr_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    event: Mapped[Event] = relationship(back_populates="locations")
    puzzle: Mapped["Puzzle | None"] = relationship(back_populates="location", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    photo: Mapped["LocationPhoto | None"] = relationship(back_populates="location", uselist=False, cascade="all, delete-orphan", passive_deletes=True)


class LocationPhoto(Base):
    """Optional reference photo of a checkpoint, taken on site by a
    coordinator (Setup Routes). Admin-only: teams never see it, since it
    would give the spot away. Stored in the database so it is kept and
    backed up with the event. The image bytes load only when asked for."""

    __tablename__ = "location_photos"
    __table_args__ = (UniqueConstraint("location_id", name="uq_location_photo_location"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    content_type: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    thumb_content_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    thumb: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    location: Mapped[Location] = relationship(back_populates="photo")


class Puzzle(Base):
    """Legacy: admin-written puzzles, replaced by the built-in ones
    (app/services/puzzles). Kept so old data isn't dropped; the game no
    longer reads it."""

    __tablename__ = "puzzles"
    __table_args__ = (UniqueConstraint("location_id", name="uq_puzzle_location"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="text")  # math|word|pattern|riddle|logic|mcq|text|custom
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(String(255))
    alt_answers: Mapped[list] = mapped_column(JSON, default=list)
    options: Mapped[list] = mapped_column(JSON, default=list)  # multiple choice only
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    location: Mapped[Location] = relationship(back_populates="puzzle")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("event_id", "team_code", name="uq_team_event_code"),
        UniqueConstraint("event_id", "team_name", name="uq_team_event_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_code: Mapped[str] = mapped_column(String(40))
    team_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    leader_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    leader_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    leader_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sentence: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=TeamStatus.NOT_STARTED, index=True)
    prev_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # restored on reinstate
    power_points: Mapped[int] = mapped_column(Integer, default=100)
    foul_count: Mapped[int] = mapped_column(Integer, default=0)  # denormalised; fouls table is the record
    progress: Mapped[int] = mapped_column(Integer, default=0)  # checkpoints verified == route index
    start_offset_s: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # this team's own start time
    last_checkpoint_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    frozen_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    jack_found_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queen_found_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    king_found_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disqualified_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    event: Mapped[Event] = relationship(back_populates="teams")
    route: Mapped[list["RouteStop"]] = relationship(
        back_populates="team", order_by="RouteStop.seq", cascade="all, delete-orphan", passive_deletes=True
    )


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("team_id", "seq", name="uq_route_team_seq"),
        UniqueConstraint("team_id", "location_id", name="uq_route_team_location"),
        UniqueConstraint("team_id", "face_card", name="uq_route_team_face_card"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # 1-based; seq 1 is the team's starting checkpoint
    # JACK / QUEEN / KING when this stop holds one of the team's face cards.
    # Dealt at random per team (route_service), always in visit order.
    face_card: Mapped[str | None] = mapped_column(String(10), nullable=True)

    team: Mapped[Team] = relationship(back_populates="route")
    location: Mapped[Location] = relationship()


class SentenceFragment(Base):
    __tablename__ = "sentence_fragments"
    __table_args__ = (UniqueConstraint("team_id", "seq", name="uq_fragment_team_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # route position that reveals it
    text: Mapped[str] = mapped_column(Text)


class Power(Base):
    """Per-event price list for Help / Attack / Defence."""

    __tablename__ = "powers"
    __table_args__ = (UniqueConstraint("event_id", "kind", name="uq_power_event_kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    cost: Mapped[int] = mapped_column(Integer, default=10)
    max_per_team: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TeamPower(Base):
    __tablename__ = "team_powers"
    __table_args__ = (UniqueConstraint("team_id", "kind", name="uq_team_power_kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    owned: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def remaining(self) -> int:
        return max(0, self.owned - self.used)


class PowerUsage(Base):
    """Every power use. For ATTACK rows, ``status`` is the attack's lifecycle."""

    __tablename__ = "power_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    target_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(12), default=UsageStatus.PENDING, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class HelpRequest(Base):
    __tablename__ = "help_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(14), default=HelpStatus.PENDING, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handled_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Foul(Base):
    __tablename__ = "fouls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="SYSTEM")  # SYSTEM | ADMIN
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    code: Mapped[str] = mapped_column(String(120))
    result: Mapped[str] = mapped_column(String(12))
    geofence_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PuzzleSession(Base):
    """One team's built-in puzzle at one checkpoint (app/services/puzzles):
    the version it was dealt and its progress. Created when the checkpoint's
    QR is verified."""

    __tablename__ = "puzzle_sessions"
    __table_args__ = (UniqueConstraint("team_id", "location_id", name="uq_puzzle_session_team_location"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # checked answers / submissions
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PuzzleAttempt(Base):
    """Legacy (answers to admin-written puzzles, before the built-in ones). Kept
    so old data isn't dropped; nothing reads or writes it any more."""

    __tablename__ = "puzzle_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    puzzle_id: Mapped[str] = mapped_column(ForeignKey("puzzles.id", ondelete="CASCADE"), index=True)
    answer: Mapped[str] = mapped_column(String(255))
    correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IdempotencyRecord(Base):
    """Stored responses of mutating team requests, keyed by the client's
    idempotency key, so a retried request returns the original result."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("team_id", "key", name="uq_idempotency_team_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    endpoint: Mapped[str] = mapped_column(String(40))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GameEvent(Base):
    """Automatic log of normal play (spec section 23)."""

    __tablename__ = "game_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AdminAction(Base):
    """Audit trail of manual coordinator overrides, kept apart from game_events."""

    __tablename__ = "admin_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    admin_id: Mapped[str | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    admin_username: Mapped[str] = mapped_column(String(80))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
