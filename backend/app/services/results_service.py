"""Winner determination (spec section 21).

Ranking: (1) found the Joker, (2) fewest fouls, (3) fastest time.
Teams that didn't finish rank below every finisher, by checkpoints reached.

The public view shows rank, team name and time - never fouls. The
coordinator view adds everything needed to settle disputes. Both are built
from the same ranking, so they can't disagree.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import iso
from app.models import Event, FaceCard, PowerUsage, Team, TeamStatus


def elapsed_seconds(team: Team) -> int | None:
    if team.completed_at is None or team.started_at is None:
        return None
    return max(0, int((team.completed_at - team.started_at).total_seconds()))


def ranked_teams(db: Session, event: Event) -> list[Team]:
    teams = list(db.scalars(select(Team).where(Team.event_id == event.id)))
    far = datetime.max

    def key(t: Team):
        if t.status == TeamStatus.DISQUALIFIED:
            return (2, 0, 0, far, t.team_name.casefold())
        if t.status == TeamStatus.COMPLETED:
            return (0, t.foul_count, elapsed_seconds(t) or 0, far, t.team_name.casefold())
        return (1, -t.progress, t.foul_count, t.last_checkpoint_at or far, t.team_name.casefold())

    return sorted(teams, key=key)


def public_results(db: Session, event: Event) -> list[dict]:
    # HARD RULE: no foul information on the public results (spec sections 16/17/21).
    rows = []
    rank = 0
    for team in ranked_teams(db, event):
        if team.status == TeamStatus.DISQUALIFIED:
            continue
        rank += 1
        finished = team.status == TeamStatus.COMPLETED
        rows.append(
            {
                "rank": rank,
                "team_name": team.team_name,
                "finished": finished,
                "elapsed_s": elapsed_seconds(team) if finished else None,
                "checkpoints": team.progress,
            }
        )
    return rows


def coordinator_results(db: Session, event: Event) -> list[dict]:
    usage = Counter(
        (u.team_id, u.kind) for u in db.scalars(select(PowerUsage).where(PowerUsage.event_id == event.id))
    )
    rows = []
    for rank, team in enumerate(ranked_teams(db, event), start=1):
        rows.append(
            {
                "rank": rank,
                "team_id": team.id,
                "team_code": team.team_code,
                "team_name": team.team_name,
                "status": team.status,
                "finished": team.status == TeamStatus.COMPLETED,
                "elapsed_s": elapsed_seconds(team),
                "foul_count": team.foul_count,
                "checkpoints": team.progress,
                "total_checkpoints": len(team.route),
                "face_cards": {f: iso(getattr(team, f"{f.lower()}_found_at")) for f in FaceCard.ORDER},
                "attacks_used": usage.get((team.id, "ATTACK"), 0),
                "defences_used": usage.get((team.id, "DEFENCE"), 0),
                "help_used": usage.get((team.id, "HELP"), 0),
                "started_at": iso(team.started_at),
                "completed_at": iso(team.completed_at),
                "leader_name": team.leader_name,
                "leader_phone": team.leader_phone,
                "leader_email": team.leader_email,
                "disqualified_reason": team.disqualified_reason,
            }
        )
    return rows


def format_elapsed(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
