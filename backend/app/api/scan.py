from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, run_team_action
from app.database import get_db
from app.models import Team
from app.schemas.schemas import ScanIn
from app.services import scan_service

router = APIRouter(tags=["team"])


@router.post("/scan")
def scan(payload: ScanIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """Submit a scanned QR (spec section 10). GPS is optional and only used
    for the geofence check."""
    return run_team_action(
        db,
        team,
        payload.idempotency_key,
        "scan",
        lambda event, now: scan_service.process_scan(
            db, event, team, payload.code, now, payload.lat, payload.lng, payload.accuracy
        ),
    )
