"""Event setup: locations (+ photos), the built-in puzzles overview, power prices, routes (with each team's face cards), QR sheet."""
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


def _draft_only(event: Event, what: str) -> None:
    if event.status != EventStatus.DRAFT:
        raise ConflictError(f"{what} can only change while the event is in DRAFT. Unlock the configuration first.")


def _not_ended(event: Event) -> None:
    if event.status == EventStatus.ENDED:
        raise ConflictError("The event has ended.")


def _load_location(db: Session, event: Event, location_id: str) -> Location:
    loc = db.get(Location, location_id)
    if loc is None or loc.event_id != event.id:
        raise NotFoundError("Location not found in this event.")
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


# --- locations ------------------------------------------------------------------


@router.get("/locations")
def list_locations(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    return [location_out(l) for l in db.scalars(select(Location).where(Location.event_id == event.id).order_by(Location.code))]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(event_id: str, payload: LocationIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    _draft_only(event, "Locations")
    count = len(db.scalars(select(Location.id).where(Location.event_id == event.id)).all())
    if count >= route_service.MAX_POOL:
        raise ConflictError(f"An event can have at most {route_service.MAX_POOL} locations (L01-L15).")
    loc = Location(
        event_id=event.id,
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
    audit.log_admin(db, admin, event.id, "LOCATION_ADDED", f"{loc.code} {loc.name}")
    db.commit()
    return location_out(loc)


@router.patch("/locations/{location_id}")
def update_location(event_id: str, location_id: str, payload: LocationPatch, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    _not_ended(event)
    loc = _load_location(db, event, location_id)
    changes = payload.model_dump(exclude_unset=True)
    if "is_selected" in changes and changes["is_selected"] != loc.is_selected:
        _draft_only(event, "The checkpoint selection")
    # Names and coordinates may be corrected at any time (e.g. fixing a GPS
    # point on the day); they only affect the radar.
    for key, value in changes.items():
        setattr(loc, key, value.strip() if isinstance(value, str) else value)
    audit.log_admin(db, admin, event.id, "LOCATION_UPDATED", f"{loc.code}: " + ", ".join(f"{k}={v}" for k, v in changes.items()))
    db.commit()
    return location_out(loc)


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(event_id: str, location_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    _draft_only(event, "Locations")
    loc = _load_location(db, event, location_id)
    audit.log_admin(db, admin, event.id, "LOCATION_DELETED", f"{loc.code} {loc.name}")
    db.delete(loc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- location photos --------------------------------------------------------------
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


@router.post("/locations/{location_id}/photo")
def set_location_photo(
    event_id: str,
    location_id: str,
    file: UploadFile = File(...),
    thumb: UploadFile | None = File(None),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Add or replace a checkpoint's photo. Allowed until the event ends - it
    doesn't change the game, so it can be added or fixed on the day."""
    event = load_event(db, event_id)
    _not_ended(event)
    loc = _load_location(db, event, location_id)
    data, kind = _read_image(file, MAX_PHOTO_BYTES, "photo")
    thumb_data, thumb_kind = _read_image(thumb, MAX_THUMB_BYTES, "thumbnail") if thumb is not None else (None, None)
    photo = loc.photo
    if photo is None:
        photo = loc.photo = LocationPhoto()
    photo.content_type, photo.data, photo.size_bytes = kind, data, len(data)
    photo.thumb_content_type, photo.thumb = thumb_kind, thumb_data
    photo.uploaded_at = utcnow()
    audit.log_admin(db, admin, event.id, "LOCATION_PHOTO_SET", f"{loc.code} ({max(1, len(data) // 1024)} KB)")
    db.commit()
    return location_out(loc)


@router.get("/locations/{location_id}/photo")
def get_location_photo(
    event_id: str,
    location_id: str,
    thumb: bool = False,
    _admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    event = load_event(db, event_id)
    photo = _load_location(db, event, location_id).photo
    if photo is None:
        raise NotFoundError("This checkpoint has no photo.")
    body, kind = (photo.thumb, photo.thumb_content_type) if thumb and photo.thumb is not None else (photo.data, photo.content_type)
    # The console asks with ?v=<upload time>, so a replaced photo is a new URL.
    return Response(content=body, media_type=kind, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.delete("/locations/{location_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
def delete_location_photo(event_id: str, location_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    _not_ended(event)
    loc = _load_location(db, event, location_id)
    if loc.photo is not None:
        loc.photo = None  # delete-orphan removes the row
        audit.log_admin(db, admin, event.id, "LOCATION_PHOTO_REMOVED", loc.code)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/locations/{location_id}/regenerate-qr")
def regenerate_qr(event_id: str, location_id: str, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    if event.status not in (EventStatus.DRAFT, EventStatus.CONFIGURED):
        raise ConflictError("QR codes can't change once the game is live - the printed sticker would stop working.")
    loc = _load_location(db, event, location_id)
    loc.qr_token = event_service.new_qr_token(db)
    audit.log_admin(db, admin, event.id, "QR_REGENERATED", loc.code)
    db.commit()
    return location_out(loc)


# --- puzzles (built in - app/services/puzzles) ------------------------------------


@router.get("/puzzles")
def list_puzzles(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Which built-in puzzle each checkpoint has. Nothing to write or edit:
    the type follows the checkpoint number, and every team gets its own version."""
    event = load_event(db, event_id)
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
            for l in db.scalars(select(Location).where(Location.event_id == event.id).order_by(Location.code))
        ],
    }


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
    locs = route_service.selected_locations(db, event.id)
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


# --- QR sheet ---------------------------------------------------------------------


@router.get("/qr-codes")
def qr_codes(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Tokens for the printable sheet. The admin console renders them as QR
    images that link to the team app, so a phone's normal camera works too."""
    event = load_event(db, event_id)
    locs = db.scalars(select(Location).where(Location.event_id == event.id).order_by(Location.code))
    return {
        "event_name": event.name,
        "status": event.status,
        "codes": [{"code": l.code, "name": l.name, "token": l.qr_token, "is_selected": l.is_selected} for l in locs],
    }
