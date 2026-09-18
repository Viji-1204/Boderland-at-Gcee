from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_team, load_event, run_team_action
from app.core.timeutil import utcnow
from app.database import get_db
from app.models import Team
from app.schemas.schemas import AnswerIn, PuzzlePlayIn
from app.services import scan_service

router = APIRouter(prefix="/puzzle", tags=["team"])


@router.get("/current")
def current(team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    event = load_event(db, team.event_id)
    return {"puzzle": scan_service.current_puzzle(db, event, team, utcnow())}


@router.post("/play")
def play(payload: PuzzlePlayIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """A move on the open built-in puzzle. There is no puzzle id in the
    request: the server knows which puzzle is open for this team."""
    move = payload.model_dump(exclude={"idempotency_key"}, exclude_none=True)
    return run_team_action(
        db,
        team,
        payload.idempotency_key,
        "puzzle",
        lambda event, now: scan_service.play_puzzle(db, event, team, move, now),
    )


@router.post("/answer")
def answer(payload: AnswerIn, team: Team = Depends(get_current_team), db: Session = Depends(get_db)):
    """A typed answer (scrambled words, riddle) - same as /play with an answer."""
    return run_team_action(
        db,
        team,
        payload.idempotency_key,
        "puzzle",
        lambda event, now: scan_service.answer_puzzle(db, event, team, payload.answer, now),
    )
