from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_key, get_current_admin, get_current_team
from app.database import get_db
from app.models import Admin, Team
from app.schemas.schemas import AdminLoginIn, TeamLoginIn
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/team/login")
def team_login(payload: TeamLoginIn, request: Request, db: Session = Depends(get_db)):
    """Round 1 login: ``{team_code, password}`` -> JWT."""
    return auth_service.team_login(db, payload.team_code, payload.password, client_key(request))


@router.post("/admin/login")
def admin_login(payload: AdminLoginIn, request: Request, db: Session = Depends(get_db)):
    return auth_service.admin_login(db, payload.username, payload.password, client_key(request))


@router.get("/admin/me")
def admin_me(admin: Admin = Depends(get_current_admin)):
    return {"id": admin.id, "username": admin.username, "role": admin.role}


@router.get("/team/me")
def team_me(team: Team = Depends(get_current_team)):
    return {"team_id": team.id, "team_code": team.team_code, "team_name": team.team_name, "event_id": team.event_id}
