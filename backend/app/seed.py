"""Idempotent seeding. Never drops or wipes anything.

* ``ensure_super_admin`` - creates the first SUPER_ADMIN from ADMIN_USERNAME /
  ADMIN_PASSWORD if it doesn't exist yet (Round 1's seed_admin).
* ``seed_demo_event`` - a complete, ready-to-lock demo event: the shared
  checkpoint library (10 spots, 8 in the game, created once), 6 teams with
  Round 1-style logins, routes generated (each with its own Jack/Queen/King).
  It runs automatically only on a
  brand-new database in development, or on request:

    python -m app.seed            # just make sure the admin exists
    python -m app.seed --demo     # add another demo event
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import Admin, AdminRole, Event, EventStatus, Location, Power, PowerKind, Team, TeamPower, TeamStatus
from app.services import route_service
from app.services.event_service import DEFAULT_POWER_PRICES, new_qr_token, the_event

logger = logging.getLogger("round2.seed")

DEMO_LOCATIONS = [
    # code, name, lat, lng, in the game. Puzzles are built in by checkpoint
    # number (app/services/puzzles): L01 scrambled words, L02 picture, L03 rock
    # paper scissors, L04 X/O, L05 riddle, L06 crossword, L07 ... The Jack,
    # Queen and King are dealt per team when the routes are generated.
    ("L01", "Main Gate", 13.08270, 80.27070, True),
    ("L02", "Clock Tower", 13.08350, 80.27150, True),
    ("L03", "Library Steps", 13.08420, 80.27220, True),
    ("L04", "Science Block", 13.08500, 80.27300, True),
    ("L05", "Canteen", 13.08580, 80.27380, True),
    ("L06", "Auditorium", 13.08650, 80.27450, True),
    ("L07", "Sports Pavilion", 13.08720, 80.27520, True),
    ("L08", "Tech Lab", 13.08800, 80.27600, True),
    ("L09", "Innovation Hub", 13.08880, 80.27680, False),
    ("L10", "Admin Block", 13.08950, 80.27750, False),
]

DEMO_TEAMS = [
    # team code, team name, leader, phone (password = first 4 digits), sentence
    ("B@GCEE-1001#", "Dragon Warriors", "Arun", "9840012345", "ONLY THE BRAVE FIND THE JOKER AT DAWN"),
    ("B@GCEE-1002#", "Border Runners", "Divya", "9841012345", "EVERY BORDER HIDES A DOOR FOR THE CLEVER"),
    ("B@GCEE-1003#", "Joker's Wild", "Karthik", "9842012345", "THE GAME ENDS WHEN THE LAST CARD FALLS"),
    ("B@GCEE-1004#", "Queen's Gambit", "Meena", "9843012345", "TRUST YOUR TEAM AND FOLLOW THE RADAR NORTH"),
    ("B@GCEE-1005#", "Heart Breakers", "Rahul", "9844012345", "HEARTS BREAK BUT SPADES DIG THE WAY OUT"),
    ("B@GCEE-1006#", "Spade Squad", "Sneha", "9845012345", "A VISA EXTENDED IS A LIFE WON BACK"),
]


def ensure_super_admin(db: Session) -> bool:
    existing = db.scalar(select(Admin).where(func.lower(Admin.username) == settings.admin_username.lower()))
    if existing is not None:
        return False
    db.add(
        Admin(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role=AdminRole.SUPER_ADMIN,
            is_active=True,
        )
    )
    logger.info("Created SUPER_ADMIN '%s' (password from ADMIN_PASSWORD).", settings.admin_username)
    return True


def ensure_checkpoints(db: Session) -> bool:
    """The demo checkpoint library, created only if the library is empty.
    Checkpoints are shared by every event, so a second demo event (or a real
    one) reuses them - and their QR stickers."""
    if db.scalar(select(func.count(Location.id))):
        return False
    for code, loc_name, lat, lng, selected in DEMO_LOCATIONS:
        db.add(
            Location(
                code=code,
                name=loc_name,
                latitude=lat,
                longitude=lng,
                geofence_radius_m=40,
                is_selected=selected,
                qr_token=new_qr_token(db),
            )
        )
    db.flush()
    return True


def seed_demo_event(db: Session, name: str = "Round 2 - Demo Hunt") -> Event:
    event = Event(
        name=name,
        status=EventStatus.DRAFT,
        settings={
            "freeze_duration_s": 60,
            "attack_response_window_s": 15,
            "staggered_start_offset_s": 60,
            "radar_near_radius_m": 30,
            "geofence_mode": "off",
            "starting_power_points": 100,
        },
        final_location_name="Coordinator's Bench",
        final_latitude=13.08200,
        final_longitude=80.27000,
    )
    db.add(event)
    db.flush()
    for kind, (cost, cap) in DEFAULT_POWER_PRICES.items():
        db.add(Power(event_id=event.id, kind=kind, cost=cost, max_per_team=cap, active=True))

    ensure_checkpoints(db)

    for team_code, team_name, leader, phone, sentence in DEMO_TEAMS:
        team = Team(
            event_id=event.id,
            team_code=team_code,
            team_name=team_name,
            password_hash=hash_password(phone[:4]),
            leader_name=leader,
            leader_phone=phone,
            sentence=sentence,
            status=TeamStatus.NOT_STARTED,
            power_points=100,
        )
        db.add(team)
        db.flush()
        for kind in PowerKind.ALL:  # one of each so every attack/defence can be tried at once
            db.add(TeamPower(team_id=team.id, kind=kind, owned=1, used=0))
    db.flush()
    route_service.generate_routes(db, event)
    logger.info("Seeded demo event '%s' with %d teams.", name, len(DEMO_TEAMS))
    return event


def startup_seed() -> None:
    with SessionLocal() as db:
        ensure_super_admin(db)
        if (db.scalar(select(func.count(Event.id))) or 0) == 0:
            if settings.should_seed_demo:
                seed_demo_event(db)  # development: a ready-to-play game
            else:
                the_event(db)  # production: an empty game, ready for setup
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Round 2 database (never deletes anything).")
    parser.add_argument("--demo", action="store_true", help="create the demo game (only if no game exists yet)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from app.migrate import run_migrations

    run_migrations()
    with SessionLocal() as db:
        ensure_super_admin(db)
        if args.demo:
            if db.scalar(select(func.count(Event.id))):
                print("A game already exists - the app runs a single event, so no demo was added.")
            else:
                seed_demo_event(db)
        db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    main()
