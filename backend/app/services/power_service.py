"""Help / Attack / Defence (spec section 18).

* Powers are bought with power points before the event goes LIVE.
  Purchases close automatically at that transition.
* An attack opens a response window for the target (default 15s), measured
  from a server timestamp. The target can use a Defence to cancel it, or
  accept it. If the window runs out without a response, the target is frozen
  automatically: by whichever comes first, the background sweeper or the
  next request that touches the attack.
* Each attack is resolved with a compare-and-set UPDATE (``WHERE status =
  'PENDING'``), so the defend button and the timeout can race without
  double-freezing or double-charging.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.locks import team_locks
from app.core.timeutil import iso
from app.models import (
    Event,
    EventStatus,
    HelpRequest,
    HelpStatus,
    Power,
    PowerKind,
    PowerUsage,
    Team,
    TeamPower,
    TeamStatus,
    UsageStatus,
)
from app.services import audit
from app.services.event_settings import event_settings
from app.services.scan_service import assert_can_play, is_frozen


def catalog(db: Session, event_id: str) -> list[Power]:
    return list(db.scalars(select(Power).where(Power.event_id == event_id).order_by(Power.kind)))


def inventory(db: Session, team_id: str) -> dict[str, TeamPower]:
    return {tp.kind: tp for tp in db.scalars(select(TeamPower).where(TeamPower.team_id == team_id))}


def _team_power(db: Session, team_id: str, kind: str) -> TeamPower:
    tp = db.scalar(select(TeamPower).where(TeamPower.team_id == team_id, TeamPower.kind == kind))
    if tp is None:
        tp = TeamPower(team_id=team_id, kind=kind, owned=0, used=0)
        db.add(tp)
        db.flush()
    return tp


def purchase_open(event: Event) -> bool:
    return event.status in (EventStatus.DRAFT, EventStatus.CONFIGURED)


def purchase(db: Session, event: Event, team: Team, kind: str, quantity: int) -> dict:
    if not purchase_open(event):
        raise ConflictError("Power purchases closed when the game went live.")
    if team.status == TeamStatus.DISQUALIFIED:
        raise ConflictError("Your team has been disqualified.")
    if kind not in PowerKind.ALL:
        raise AppError("Unknown power.")
    if not isinstance(quantity, int) or quantity < 1:
        raise AppError("Quantity must be at least 1.")  # the old code accepted -50 and paid the team
    price = db.scalar(select(Power).where(Power.event_id == event.id, Power.kind == kind))
    if price is None or not price.active:
        raise ConflictError(f"{kind.title()} isn't available in this event.")
    tp = _team_power(db, team.id, kind)
    if tp.owned + quantity > price.max_per_team:
        raise ConflictError(f"A team can hold at most {price.max_per_team} {kind.title()} power(s).")
    total = price.cost * quantity
    if team.power_points < total:
        raise ConflictError(f"Not enough power points: {total} needed, {team.power_points} left.")
    team.power_points -= total
    tp.owned += quantity
    audit.log_game(db, event.id, team.id, "POWER_PURCHASED", f"{team.team_name} bought {quantity} x {kind} for {total} pts")
    audit.team_changed(db, event.id, team.id)
    return {
        "message": f"Bought {quantity} x {kind.title()}.",
        "power_points": team.power_points,
        "kind": kind,
        "owned": tp.owned,
        "remaining": tp.remaining,
    }


# ---------------------------------------------------------------------------
# Freezes
# ---------------------------------------------------------------------------


def freeze(db: Session, event: Event, team: Team, seconds: int, now: datetime, reason: str) -> None:
    base = team.frozen_until if is_frozen(team, now) else now
    team.frozen_until = base + timedelta(seconds=seconds)
    audit.log_game(db, event.id, team.id, "TEAM_FROZEN", f"{team.team_name} frozen for {seconds}s ({reason})")
    audit.notify_team(db, team.id, {"type": "frozen", "frozen_until": iso(team.frozen_until), "reason": reason})
    audit.team_changed(db, event.id, team.id)


# ---------------------------------------------------------------------------
# Attack / Defence
# ---------------------------------------------------------------------------


def pending_attack_on(db: Session, team_id: str) -> PowerUsage | None:
    return db.scalar(
        select(PowerUsage)
        .where(
            PowerUsage.kind == PowerKind.ATTACK,
            PowerUsage.target_team_id == team_id,
            PowerUsage.status == UsageStatus.PENDING,
        )
        .order_by(PowerUsage.created_at)
        .limit(1)
    )


def attack(db: Session, event: Event, attacker: Team, target: Team, now: datetime) -> dict:
    assert_can_play(event, attacker, now)
    if target.id == attacker.id:
        raise AppError("You can't attack your own team.")
    if target.event_id != event.id:
        raise NotFoundError("Target team not found.")
    # Check the attacker's own inventory first, so a team with nothing to
    # spend can't use the rejection messages below to probe rivals' status.
    tp = _team_power(db, attacker.id, PowerKind.ATTACK)
    if tp.remaining < 1:
        raise ConflictError("You have no Attack power left.")
    if target.status in (TeamStatus.COMPLETED, TeamStatus.DISQUALIFIED) or target.status not in TeamStatus.PLAYING:
        raise ConflictError(f"{target.team_name} is out of play and can't be attacked.")
    if target.started_at is not None and now < target.started_at:
        raise ConflictError(f"{target.team_name} hasn't started yet.")
    settings = event_settings(event)
    if is_frozen(target, now) and not settings["allow_attack_frozen"]:
        raise ConflictError(f"{target.team_name} is already frozen and can't be attacked again.")
    if pending_attack_on(db, target.id) is not None:
        raise ConflictError(f"{target.team_name} is already responding to another attack. Try again shortly.")

    tp.used += 1  # consumed on use (spec)

    window = int(settings["attack_response_window_s"])
    usage = PowerUsage(
        event_id=event.id,
        kind=PowerKind.ATTACK,
        team_id=attacker.id,
        target_team_id=target.id,
        status=UsageStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(seconds=window),
    )
    db.add(usage)
    db.flush()
    audit.log_game(db, event.id, attacker.id, "ATTACK", f"{attacker.team_name} attacked {target.team_name}")
    # The target isn't told who attacked: power use is coordinator-only info.
    audit.notify_team(
        db,
        target.id,
        {"type": "attack_incoming", "usage_id": usage.id, "expires_at": iso(usage.expires_at), "window_s": window},
    )
    audit.team_changed(db, event.id, attacker.id)
    audit.team_changed(db, event.id, target.id)
    return {
        "usage_id": usage.id,
        "status": usage.status,
        "expires_at": iso(usage.expires_at),
        "message": f"Attack sent to {target.team_name}. They have {window}s to respond.",
        "remaining": tp.remaining,
    }


def _resolve(db: Session, usage_id: str, new_status: str, now: datetime) -> bool:
    """Compare-and-set PENDING -> new_status. True only for the winner."""
    result = db.execute(
        update(PowerUsage)
        .where(PowerUsage.id == usage_id, PowerUsage.status == UsageStatus.PENDING)
        .values(status=new_status, resolved_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def respond(db: Session, event: Event, target: Team, usage_id: str, use_defence: bool, now: datetime) -> dict:
    usage = db.get(PowerUsage, usage_id)
    if usage is None or usage.kind != PowerKind.ATTACK or usage.target_team_id != target.id:
        raise NotFoundError("That attack doesn't exist.")
    db.refresh(usage)
    if usage.status != UsageStatus.PENDING:
        return {"status": usage.status, "message": "This attack has already been resolved.", "frozen_until": iso(target.frozen_until)}
    if event.status != EventStatus.LIVE:
        raise ConflictError("The game isn't running right now.")

    settings = event_settings(event)
    freeze_s = int(settings["freeze_duration_s"])
    attacker = db.get(Team, usage.team_id)

    if usage.expires_at is not None and now >= usage.expires_at:
        if _resolve(db, usage.id, UsageStatus.EXPIRED, now):
            freeze(db, event, target, freeze_s, now, "attack not answered in time")
            if attacker:
                audit.notify_team(db, attacker.id, {"type": "attack_result", "status": UsageStatus.EXPIRED, "target_name": target.team_name})
        return {"status": UsageStatus.EXPIRED, "message": "Too late - the response window closed. You are frozen.", "frozen_until": iso(target.frozen_until)}

    if use_defence:
        tp = _team_power(db, target.id, PowerKind.DEFENCE)
        if tp.remaining < 1:
            raise ConflictError("You have no Defence power left - accept the attack instead.")
        if not _resolve(db, usage.id, UsageStatus.CANCELLED, now):
            db.refresh(usage)
            return {"status": usage.status, "message": "This attack has already been resolved.", "frozen_until": iso(target.frozen_until)}
        tp.used += 1
        db.add(
            PowerUsage(
                event_id=event.id,
                kind=PowerKind.DEFENCE,
                team_id=target.id,
                target_team_id=usage.team_id,
                status=UsageStatus.USED,
                created_at=now,
                resolved_at=now,
            )
        )
        audit.log_game(db, event.id, target.id, "ATTACK_DEFENDED", f"{target.team_name} blocked an attack from {attacker.team_name if attacker else '?'}")
        if attacker:
            audit.notify_team(db, attacker.id, {"type": "attack_result", "status": UsageStatus.CANCELLED, "target_name": target.team_name})
        audit.team_changed(db, event.id, target.id)
        return {"status": UsageStatus.CANCELLED, "message": "DEFENDED - the attack was blocked.", "frozen_until": None}

    if not _resolve(db, usage.id, UsageStatus.CONFIRMED, now):
        db.refresh(usage)
        return {"status": usage.status, "message": "This attack has already been resolved.", "frozen_until": iso(target.frozen_until)}
    freeze(db, event, target, freeze_s, now, "attack accepted")
    if attacker:
        audit.notify_team(db, attacker.id, {"type": "attack_result", "status": UsageStatus.CONFIRMED, "target_name": target.team_name})
    return {"status": UsageStatus.CONFIRMED, "message": f"Attack accepted - frozen for {freeze_s}s.", "frozen_until": iso(target.frozen_until)}


def expire_due_attacks(db: Session, event: Event, now: datetime) -> int:
    """Freeze targets whose response window ran out. Returns how many.

    Safe to call from anywhere, and concurrently: each attack is claimed with
    a compare-and-set, and the target's lock is held while it is frozen.
    Callers must not already hold a team lock.
    """
    if event.status != EventStatus.LIVE:
        return 0
    due = list(
        db.scalars(
            select(PowerUsage).where(
                PowerUsage.event_id == event.id,
                PowerUsage.kind == PowerKind.ATTACK,
                PowerUsage.status == UsageStatus.PENDING,
                PowerUsage.expires_at <= now,
            )
        )
    )
    count = 0
    freeze_s = int(event_settings(event)["freeze_duration_s"])
    for usage in due:
        with team_locks(usage.target_team_id):
            if not _resolve(db, usage.id, UsageStatus.EXPIRED, now):
                # Someone else resolved it first. End our transaction anyway:
                # even a zero-row UPDATE holds SQLite's write lock until then.
                db.rollback()
                continue
            target = db.get(Team, usage.target_team_id)
            if target is None:
                db.commit()
                continue
            db.refresh(target)
            if target.status in TeamStatus.PLAYING:
                freeze(db, event, target, freeze_s, now, "attack not answered in time")
            audit.notify_team(db, usage.team_id, {"type": "attack_result", "status": UsageStatus.EXPIRED, "target_name": target.team_name})
            db.commit()
            count += 1
    return count


# ---------------------------------------------------------------------------
# Help (spec section 18: PENDING -> ACKNOWLEDGED -> RESOLVED)
# ---------------------------------------------------------------------------


def open_help(db: Session, team_id: str) -> HelpRequest | None:
    return db.scalar(
        select(HelpRequest)
        .where(HelpRequest.team_id == team_id, HelpRequest.status.in_(HelpStatus.OPEN))
        .order_by(HelpRequest.created_at.desc())
        .limit(1)
    )


def request_help(db: Session, event: Event, team: Team, message: str | None, now: datetime) -> dict:
    assert_can_play(event, team, now, allow_frozen=True)
    if open_help(db, team.id) is not None:
        raise ConflictError("You already have an open help request - a volunteer is on the way.")
    tp = _team_power(db, team.id, PowerKind.HELP)
    if tp.remaining < 1:
        raise ConflictError("You have no Help power left.")
    tp.used += 1
    req = HelpRequest(event_id=event.id, team_id=team.id, status=HelpStatus.PENDING, message=(message or "").strip()[:500] or None, created_at=now)
    db.add(req)
    db.add(PowerUsage(event_id=event.id, kind=PowerKind.HELP, team_id=team.id, status=UsageStatus.USED, created_at=now, resolved_at=now))
    db.flush()
    audit.log_game(db, event.id, team.id, "HELP_REQUESTED", f"{team.team_name} asked for help" + (f": {req.message}" if req.message else ""))
    audit.team_changed(db, event.id, team.id)
    return {"id": req.id, "status": req.status, "message": "Help requested - a volunteer will come to you.", "remaining": tp.remaining}


def update_help(db: Session, event: Event, req: HelpRequest, status: str, handled_by: str, now: datetime) -> HelpRequest:
    if status not in (HelpStatus.ACKNOWLEDGED, HelpStatus.RESOLVED):
        raise AppError("Status must be ACKNOWLEDGED or RESOLVED.")
    if req.status == HelpStatus.RESOLVED:
        raise ConflictError("This request is already resolved.")
    if status == HelpStatus.ACKNOWLEDGED:
        req.acknowledged_at = now
    else:
        req.acknowledged_at = req.acknowledged_at or now
        req.resolved_at = now
    req.status = status
    req.handled_by = handled_by
    audit.notify_team(db, req.team_id, {"type": "help", "status": status})
    audit.team_changed(db, event.id, req.team_id)
    return req
