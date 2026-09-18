"""Teams (CRUD + Round 1-style spreadsheet import) and admin accounts."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, load_event, load_team, require_super
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.core.timeutil import iso
from app.database import get_db
from app.models import Admin, AdminRole, Event, EventStatus, Team, TeamStatus
from app.schemas.schemas import (
    AdminAccountIn,
    ImportCommitIn,
    ImportCommitOut,
    PasswordResetIn,
    TeamCreateIn,
    TeamPatchIn,
)
from app.services import audit, export_service, team_import_service
from app.services.event_settings import event_settings

router = APIRouter(prefix="/admin", tags=["admin-teams"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Access-Control-Expose-Headers": "Content-Disposition"},
    )


def team_out(t: Team) -> dict:
    return {
        "id": t.id,
        "team_code": t.team_code,
        "team_name": t.team_name,
        "leader_name": t.leader_name,
        "leader_phone": t.leader_phone,
        "leader_email": t.leader_email,
        "sentence": t.sentence,
        "status": t.status,
        "power_points": t.power_points,
        "foul_count": t.foul_count,
        "progress": t.progress,
        "route_length": len(t.route),
        "start_offset_s": t.start_offset_s,
        "created_at": iso(t.created_at),
    }


def _draft_only(event: Event, what: str) -> None:
    if event.status != EventStatus.DRAFT:
        raise ConflictError(f"{what} only while the event is in DRAFT.")


# --- teams --------------------------------------------------------------------


@router.get("/events/{event_id}/teams")
def list_teams(event_id: str, _admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    return [team_out(t) for t in db.scalars(select(Team).where(Team.event_id == event.id).order_by(Team.team_name))]


@router.post("/events/{event_id}/teams", status_code=status.HTTP_201_CREATED)
def create_team(event_id: str, payload: TeamCreateIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Single team (Round 1's "New Team" form). The password is given, or
    derived from the leader's phone like an import."""
    event = load_event(db, event_id)
    _draft_only(event, "Teams can be added")
    password = (payload.password or "").strip() or team_import_service.password_from_phone(payload.leader_phone)
    if not password:
        raise AppError("Give a password or the leader's phone number (its first 4 digits become the password).")
    taken = set(db.scalars(select(Team.team_code).where(Team.event_id == event.id)))
    code = team_import_service.clean_team_code(payload.team_code) or team_import_service.generate_team_code(taken)
    team = Team(
        event_id=event.id,
        team_code=code,
        team_name=payload.team_name.strip(),
        password_hash=hash_password(password),
        leader_name=(payload.leader_name or "").strip() or None,
        leader_phone=team_import_service.normalise_phone(payload.leader_phone) or None,
        leader_email=(payload.leader_email or "").strip() or None,
        sentence=(payload.sentence or "").strip() or None,
        status=TeamStatus.NOT_STARTED,
        power_points=int(event_settings(event)["starting_power_points"]),
    )
    db.add(team)
    db.flush()
    audit.log_admin(db, admin, event.id, "TEAM_CREATED", f"{team.team_code} {team.team_name}", team.id)
    db.commit()
    return {**team_out(team), "password": password}


@router.patch("/events/{event_id}/teams/{team_id}")
def update_team(event_id: str, team_id: str, payload: TeamPatchIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    team = load_team(db, event, team_id)
    changes = payload.model_dump(exclude_unset=True)
    if "sentence" in changes and (changes["sentence"] or None) != team.sentence:
        _draft_only(event, "Sentences can change")  # fragments are cut when the event is locked
    for key, value in changes.items():
        if key == "leader_phone":
            value = team_import_service.normalise_phone(value) or None
        elif isinstance(value, str):
            value = value.strip() or None
        if key == "team_name" and not value:
            raise AppError("Team name can't be empty.")
        setattr(team, key, value)
    audit.log_admin(db, admin, event.id, "TEAM_UPDATED", ", ".join(changes), team.id)
    audit.team_changed(db, event.id, team.id, leaderboard="team_name" in changes)
    db.commit()
    return team_out(team)


@router.patch("/events/{event_id}/teams/{team_id}/password")
def reset_team_password(event_id: str, team_id: str, payload: PasswordResetIn, admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    team = load_team(db, event, team_id)
    team.password_hash = hash_password(payload.new_password)
    audit.log_admin(db, admin, event.id, "TEAM_PASSWORD_RESET", None, team.id)
    db.commit()
    return team_out(team)


@router.delete("/events/{event_id}/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(event_id: str, team_id: str, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    event = load_event(db, event_id)
    _draft_only(event, "Teams can be deleted (use Disqualify during the game)")
    team = load_team(db, event, team_id)
    audit.log_admin(db, admin, event.id, "TEAM_DELETED", f"{team.team_code} {team.team_name}")
    db.delete(team)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- spreadsheet import (Round 1 flow) ------------------------------------------


@router.get("/teams/import/template")
def import_template(_admin: Admin = Depends(require_super)):
    return _xlsx(export_service.build_import_template(), "team-import-template.xlsx")


@router.post("/events/{event_id}/teams/import/preview")
async def import_preview(
    event_id: str,
    file: UploadFile = File(...),
    team_name_column: str | None = Form(None),
    leader_name_column: str | None = Form(None),
    leader_phone_column: str | None = Form(None),
    leader_email_column: str | None = Form(None),
    team_code_column: str | None = Form(None),
    sentence_column: str | None = Form(None),
    _admin: Admin = Depends(require_super),
    db: Session = Depends(get_db),
):
    """Parse and validate - writes nothing."""
    data = await file.read()
    if len(data) > team_import_service.MAX_UPLOAD_BYTES:
        raise AppError("File is larger than 5 MB.")
    event = load_event(db, event_id)
    preview = team_import_service.parse_upload(
        db,
        event,
        data=data,
        filename=file.filename or "",
        overrides={
            "team_name": team_name_column,
            "leader_name": leader_name_column,
            "leader_phone": leader_phone_column,
            "leader_email": leader_email_column,
            "team_code": team_code_column,
            "sentence": sentence_column,
        },
    )
    rows = [vars(r) for r in preview.rows]
    importable = sum(1 for r in preview.rows if r.is_importable)
    return {
        "headers": preview.headers,
        "column_map": preview.column_map,
        "unmapped_required": preview.unmapped_required,
        "header_row_number": preview.header_row_number,
        "sheet_name": preview.sheet_name,
        "existing_team_count": preview.existing_team_count,
        "capacity_remaining": preview.capacity_remaining,
        "rows": rows,
        "importable_count": importable,
        "skipped_count": len(rows) - importable,
        "event_status": event.status,
    }


@router.post("/events/{event_id}/teams/import", status_code=status.HTTP_201_CREATED, response_model=ImportCommitOut)
def import_commit(event_id: str, payload: ImportCommitIn, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    """Create the reviewed teams, all or nothing. Returns each password once."""
    event = load_event(db, event_id)
    created = team_import_service.commit_import(db, event, rows=[r.model_dump() for r in payload.rows])
    audit.log_admin(db, admin, event.id, "TEAMS_IMPORTED", f"{len(created)} team(s)")
    db.commit()
    return {"created_count": len(created), "teams": created}


@router.post("/teams/credentials-export")
def credentials_export(payload: ImportCommitOut, _admin: Admin = Depends(require_super)):
    content = export_service.build_credentials_workbook(
        teams=[t.model_dump() for t in payload.teams], generated_at=datetime.now(timezone.utc)
    )
    return _xlsx(content, "team-logins.xlsx")


# --- admin accounts (Round 1 screen, SUPER_ADMIN only) ---------------------------


def admin_out(a: Admin) -> dict:
    return {"admin_id": a.id, "username": a.username, "role": a.role, "is_active": a.is_active, "created_at": iso(a.created_at)}


@router.get("/admins")
def list_admins(_admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    return [admin_out(a) for a in db.scalars(select(Admin).order_by(Admin.username))]


@router.post("/admins", status_code=status.HTTP_201_CREATED)
def create_admin(payload: AdminAccountIn, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    new = Admin(username=payload.username.strip(), password_hash=hash_password(payload.password), role=payload.role, is_active=True)
    db.add(new)
    db.flush()
    audit.log_admin(db, admin, None, "ADMIN_CREATED", f"{new.username} ({new.role})")
    db.commit()
    return admin_out(new)


@router.patch("/admins/{admin_id}/password")
def reset_admin_password(admin_id: str, payload: PasswordResetIn, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    target = db.get(Admin, admin_id)
    if target is None:
        raise NotFoundError("Admin not found.")
    if len(payload.new_password) < 6:
        raise AppError("Admin passwords need at least 6 characters.")
    target.password_hash = hash_password(payload.new_password)
    audit.log_admin(db, admin, None, "ADMIN_PASSWORD_RESET", target.username)
    db.commit()
    return admin_out(target)


@router.delete("/admins/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_admin(admin_id: str, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    target = db.get(Admin, admin_id)
    if target is None:
        raise NotFoundError("Admin not found.")
    if target.id == admin.id:
        raise ConflictError("You can't deactivate yourself.")
    if target.role == AdminRole.SUPER_ADMIN:
        others = db.scalars(select(Admin).where(Admin.role == AdminRole.SUPER_ADMIN, Admin.is_active.is_(True), Admin.id != target.id)).all()
        if not others:
            raise ConflictError("Keep at least one active SUPER_ADMIN.")
    target.is_active = False
    audit.log_admin(db, admin, None, "ADMIN_DEACTIVATED", target.username)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/admins/{admin_id}/activate")
def activate_admin(admin_id: str, admin: Admin = Depends(require_super), db: Session = Depends(get_db)):
    target = db.get(Admin, admin_id)
    if target is None:
        raise NotFoundError("Admin not found.")
    target.is_active = True
    audit.log_admin(db, admin, None, "ADMIN_ACTIVATED", target.username)
    db.commit()
    return admin_out(target)
