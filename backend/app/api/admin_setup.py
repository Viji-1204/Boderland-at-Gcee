"""Event setup.

Two routers:

* ``library`` (``/admin/checkpoints``): the checkpoints - GPS points, photos,
  QR codes - and the built-in puzzles overview and QR sheet. One library
  shared by every event, so a new event reuses the same spots and the
  stickers already on the walls.
* ``router`` (``/admin/events/{event_id}``): what belongs to one event -
  power prices and the routes (with each team's face cards).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, load_event, load_team
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.timeutil import iso, utcnow
from app.database import get_db
from app.models import Admin, Event, EventStatus, Location, LocationPhoto, Power, PowerKind, Team
from app.schemas.schemas import LocationIn, LocationPatch, PowerPriceIn, RouteIn
from app.services import audit, event_service, puzzles, route_service

router = APIRouter(prefix="/admin/events/{event_id}", tags=["admin-setup"])
library = APIRouter(prefix="/admin/checkpoints", tags=["admin-checkpoints"])

IN_USE = (EventStatus.CONFIGURED, EventStatus.LIVE, EventStatus.PAUSED)


def event_using_checkpoints(db: Session) -> Event | None:
    """The event whose routes currently depend on the library, if any: a
    locked or running one. While it exists the set of checkpoints can't
    change (names, GPS points and photos always can)."""
    return db.scalar(select(Event).where(Event.status.in_(IN_USE)).order_by(Event.created_at.desc()))


def _structure_free(db: Session, what: str) -> None:
    event = event_using_checkpoints(db)
    if event is not None:
        raise ConflictError(
            f"{what} can't change while '{event.name}' is {event.status} - its routes are built on these checkpoints. "
            "End the event, or unlock it back to DRAFT, first."
        )


def _load_location(db: Session, location_id: str) -> Location:
    loc = db.get(Location, location_id)
    if loc is None:
        raise NotFoundError("Checkpoint not found.")
    return loc


def location_out(loc: Location) -> dict:
    return {
        "id": loc.id,
        "code": loc.code,
        "name": loc.name,
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "geofence_radius_m": loc.geofence_radius_m,
        "is_selected": loc.is_selected,
        "qr_token": loc.qr_token,
        "puzzle_type": puzzles.kind_for_code(loc.code),
        "puzzle_label": puzzles.label(puzzles.kind_for_code(loc.code)),
        "has_photo": loc.photo is not None,
        "photo_updated_at": iso(loc.photo.uploaded_at) if loc.photo is not None else None,
    }


# --- the checkpoint library ---------------------------------------------------------


@library.get("")
def list_checkpoints(_admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return [location_out(l) for l in db.scalars(select(Location).order_by(Location.code))]


@library.get("/in-use")
def checkpoints_in_use(_admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Which event (if any) currently locks the set of checkpoints."""
    event = event_using_checkpoints(db)
    return {"event": {"id": event.id, "name": event.name, "status": event.status} if event else None}


@library.post("", status_code=status.HTTP_201_CREATED)
def create_checkpoint(payload: LocationIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    _structure_free(db, "Checkpoints")
    count = len(db.scalars(select(Location.id)).all())
    if count >= route_service.MAX_POOL:
        raise ConflictError(f"The library holds at most {route_service.MAX_POOL} checkpoints (L01-L15).")
    loc = Location(
        code=payload.code,
        name=payload.name.strip(),
        latitude=payload.latitude,
        longitude=payload.longitude,
        geofence_radius_m=payload.geofence_radius_m,
        is_selected=payload.is_selected,
        qr_token=event_service.new_qr_token(db),
    )
    db.add(loc)
    db.flush()
    audit.log_admin(db, admin, None, "LOCATION_ADDED", f"{loc.code} {loc.name}")
    db.commit()
    return location_out(loc)


@library.patch("/{location_id}")
def update_checkpoint(location_id: str, payload: LocationPatch, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    loc = _load_location(db, location_id)
    changes = payload.model_dump(exclude_unset=True)
    if "is_selected" in changes and changes["is_selected"] != loc.is_selected:
        _structure_free(db, "The checkpoint selection")
    # Names and coordinates may be corrected at any time (e.g. fixing a GPS
    # point on the day); they only affect the radar.
    for key, value in changes.items():
        setattr(loc, key, value.strip() if isinstance(value, str) else value)
    audit.log_admin(db, admin, None, "LOCATION_UPDATED", f"{loc.code}: " + ", ".join(f"{k}={v}" for k, v in changes.items()))
    db.commit()
    return location_out(loc)


@library.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_checkpoint(location_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    _structure_free(db, "Checkpoints")
    loc = _load_location(db, location_id)
    audit.log_admin(db, admin, None, "LOCATION_DELETED", f"{loc.code} {loc.name}")
    db.delete(loc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- checkpoint photos --------------------------------------------------------------
# Taken on site in Setup Routes. The console shrinks them before uploading
# (about 1600 px + a small thumbnail), so these limits are generous.

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_THUMB_BYTES = 512 * 1024


def _image_type(data: bytes) -> str | None:
    """Trust the bytes, not the browser's label: only real images are stored
    and served back, always with their true type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _read_image(upload: UploadFile, limit: int, what: str) -> tuple[bytes, str]:
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        size = f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit // 1024} KB"
        raise AppError(f"The {what} is too big (max {size}).")
    kind = _image_type(data)
    if kind is None:
        raise AppError(f"The {what} must be a JPEG, PNG or WebP image.")
    return data, kind


@library.post("/{location_id}/photo")
def set_checkpoint_photo(
    location_id: str,
    file: UploadFile = File(...),
    thumb: UploadFile | None = File(None),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Add or replace a checkpoint's photo. Allowed at any time - it doesn't
    change the game, so it can be added or fixed on the day."""
    loc = _load_location(db, location_id)
    data, kind = _read_image(file, MAX_PHOTO_BYTES, "photo")
    thumb_data, thumb_kind = _read_image(thumb, MAX_THUMB_BYTES, "thumbnail") if thumb is not None else (None, None)
    photo = loc.photo
    if photo is None:
        photo = loc.photo = LocationPhoto()
    photo.content_type, photo.data, photo.size_bytes = kind, data, len(data)
    photo.thumb_content_type, photo.thumb = thumb_kind, thumb_data
    photo.uploaded_at = utcnow()
    audit.log_admin(db, admin, None, "LOCATION_PHOTO_SET", f"{loc.code} ({max(1, len(data) // 1024)} KB)")
    db.commit()
    return location_out(loc)


@library.get("/{location_id}/photo")
def get_checkpoint_photo(location_id: str, thumb: bool = False, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    photo = _load_location(db, location_id).photo
    if photo is None:
        raise NotFoundError("This checkpoint has no photo.")
    body, kind = (photo.thumb, photo.thumb_content_type) if thumb and photo.thumb is not None else (photo.data, photo.content_type)
    # The console asks with ?v=<upload time>, so a replaced photo is a new URL.
    return Response(content=body, media_type=kind, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@library.delete("/{location_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
def delete_checkpoint_photo(location_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    loc = _load_location(db, location_id)
    if loc.photo is not None:
        loc.photo = None  # delete-orphan removes the row
        audit.log_admin(db, admin, None, "LOCATION_PHOTO_REMOVED", loc.code)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library.post("/{location_id}/regenerate-qr")
def regenerate_qr(location_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """A new sticker for one checkpoint. Not while a game is running: the
    printed sticker would stop working under the teams' feet."""
    running = db.scalar(select(Event).where(Event.status.in_((EventStatus.LIVE, EventStatus.PAUSED))))
    if running is not None:
        raise ConflictError(f"QR codes can't change while '{running.name}' is {running.status} - the printed sticker would stop working.")
    loc = _load_location(db, location_id)
    loc.qr_token = event_service.new_qr_token(db)
    audit.log_admin(db, admin, None, "QR_REGENERATED", loc.code)
    db.commit()
    return location_out(loc)


# --- puzzles (built in - app/services/puzzles) ------------------------------------


@library.get("/puzzles")
def list_puzzles(_admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Which built-in puzzle each checkpoint has. Nothing to write or edit:
    the type follows the checkpoint number, and every team gets its own version."""
    return {
        "types": [{"kind": m.KIND, "label": m.LABEL, "instructions": m.INSTRUCTIONS} for m in puzzles.ORDER],
        "checkpoints": [
            {
                "location_id": l.id,
                "code": l.code,
                "name": l.name,
                "is_selected": l.is_selected,
                "kind": puzzles.kind_for_code(l.code),
                "label": puzzles.label(puzzles.kind_for_code(l.code)),
            }
            for l in db.scalars(select(Location).order_by(Location.code))
        ],
    }


# --- QR sheet ---------------------------------------------------------------------


@library.get("/qr-codes")
def qr_codes(_admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Tokens for the printable sheet. The admin console renders them as QR
    images that link to the team app, so a phone's normal camera works too.
    Stickers are permanent: print once, reuse for every event."""
    locs = db.scalars(select(Location).order_by(Location.code))
    return {"codes": [{"code": l.code, "name": l.name, "token": l.qr_token, "is_selected": l.is_selected} for l in locs]}


# --- powers ---------------------------------------------------------------------


def _powers_out(db: Session, event: Event) -> list[dict]:
    prices = {p.kind: p for p in db.scalars(select(Power).where(Power.event_id == event.id))}
    return [
        {
            "kind": k,
            "family": PowerKind.FAMILY[k],
            "label": PowerKind.LABEL[k],
            "cost": prices[k].cost if k in prices else 0,
            "max_per_team": prices[k].max_per_team if k in prices else 0,
            "active": prices[k].active if k in prices else False,
        }
        for k in PowerKind.ALL
    ]


@router.get("/powers")
def get_powers(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _powers_out(db, load_event(db, event_id))


@router.put("/powers")
def set_powers(event_id: str, payload: list[PowerPriceIn], admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    if event.status not in (EventStatus.DRAFT, EventStatus.CONFIGURED):
        raise ConflictError("Power prices are fixed once the game is live.")
    existing = {p.kind: p for p in db.scalars(select(Power).where(Power.event_id == event.id))}
    for item in payload:
        price = existing.get(item.kind)
        if price is None:
            price = Power(event_id=event.id, kind=item.kind)
            db.add(price)
        price.cost, price.max_per_team, price.active = item.cost, item.max_per_team, item.active
    audit.log_admin(db, admin, event.id, "POWERS_SET", ", ".join(f"{i.kind}={i.cost}pt x{i.max_per_team}" for i in payload))
    db.commit()
    return _powers_out(db, event)


# --- routes ---------------------------------------------------------------------


def _routes_out(db: Session, event: Event) -> dict:
    locs = route_service.selected_locations(db)
    teams = list(db.scalars(select(Team).where(Team.event_id == event.id).order_by(Team.team_name)))
    return {
        "status": event.status,
        "selected_locations": [location_out(l) for l in locs],
        "capacity": route_service.capacity_summary(locs, len(route_service.route_teams(db, event.id))) if locs else None,
        "problems": route_service.route_problems(db, event),
        "teams": [
            {
                "team_id": t.id,
                "team_name": t.team_name,
                "team_code": t.team_code,
                "status": t.status,
                "start_offset_s": t.start_offset_s,
                "stops": [
                    {"seq": s.seq, "location_id": s.location_id, "code": s.location.code, "name": s.location.name, "face_card": s.face_card}
                    for s in sorted(t.route, key=lambda s: s.seq)
                ],
            }
            for t in teams
        ],
    }


@router.get("/routes")
def get_routes(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _routes_out(db, load_event(db, event_id))


@router.post("/routes/generate")
def generate_routes(event_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    summary = route_service.generate_routes(db, event)
    audit.log_admin(db, admin, event.id, "ROUTES_GENERATED", summary["message"])
    db.commit()
    return _routes_out(db, event)


@router.put("/teams/{team_id}/route")
def set_route(event_id: str, team_id: str, payload: RouteIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    team = load_team(db, event, team_id)
    route_service.set_manual_route(db, event, team, payload.location_ids, payload.face_cards)
    audit.log_admin(
        db, admin, event.id, "ROUTE_EDITED",
        ", ".join(f"{s.face_card.title()}={s.location.code}" for s in team.route if s.face_card), team.id,
    )
    db.commit()
    return _routes_out(db, event)


