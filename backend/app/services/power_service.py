"""Powers (spec section 18): the Help, Attack and Defence families.

* Powers are bought with power points before the event goes LIVE.
  Purchases close automatically at that transition.
* GUIDE (help) reveals the team's current target for ``guide_duration_s``:
  the radar then shows the checkpoint's name, exact distance and bearing,
  and the app offers a Google Maps route. Cleared when the target is scanned.
* An attack (FREEZE / JAM / TRAP) opens a response window for the target
  (default 15s), measured from a server timestamp. The target can answer
  with SHIELD (blocks it) or REFLECT (blocks it and applies the attack's
  effect to the attacker instead), or accept it. If the window runs out
  without a response, the effect lands automatically: by whichever comes
  first, the background sweeper or the next request that touches the attack.
  A target with an active WARD never sees the prompt: the attack is blocked
  on the spot.
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
    Foul,
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
from app.services.scan_service import assert_can_play, is_frozen, is_guided, is_jammed, is_warded

# How the attacker's outgoing list and the target's prompt describe each attack.
ATTACK_EFFECT = {
    PowerKind.FREEZE: "freezes you: no radar, scanner or puzzle for {freeze_duration_s}s",
    PowerKind.JAM: "jams your radar for {jam_duration_s}s (you can still scan and solve)",
    PowerKind.TRAP: "plants a foul on your team (+1 foul)",
}


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


def _spend(db: Session, team_id: str, kind: str) -> TeamPower:
    """Consume one power of ``kind`` or refuse with the same message whatever
    the reason, so nothing else about the game leaks through it."""
    tp = _team_power(db, team_id, kind)
    if tp.remaining < 1:
        raise ConflictError(f"You have no {PowerKind.LABEL[kind]} power left.")
    tp.used += 1
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
    label = PowerKind.LABEL[kind]
    price = db.scalar(select(Power).where(Power.event_id == event.id, Power.kind == kind))
    if price is None or not price.active:
        raise ConflictError(f"{label} isn't available in this event.")
    tp = _team_power(db, team.id, kind)
    if tp.owned + quantity > price.max_per_team:
        raise ConflictError(f"A team can hold at most {price.max_per_team} {label} power(s).")
    total = price.cost * quantity
    if team.power_points < total:
        raise ConflictError(f"Not enough power points: {total} needed, {team.power_points} left.")
    team.power_points -= total
    tp.owned += quantity
    audit.log_game(db, event.id, team.id, "POWER_PURCHASED", f"{team.team_name} bought {quantity} x {label} for {total} pts")
    audit.team_changed(db, event.id, team.id)
    return {
        "message": f"Bought {quantity} x {label}.",
        "power_points": team.power_points,
        "kind": kind,
        "owned": tp.owned,
        "remaining": tp.remaining,
    }


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


def freeze(db: Session, event: Event, team: Team, seconds: int, now: datetime, reason: str) -> None:
    base = team.frozen_until if is_frozen(team, now) else now
    team.frozen_until = base + timedelta(seconds=seconds)
    audit.log_game(db, event.id, team.id, "TEAM_FROZEN", f"{team.team_name} frozen for {seconds}s ({reason})")
    audit.notify_team(db, team.id, {"type": "frozen", "frozen_until": iso(team.frozen_until), "reason": reason})
    audit.team_changed(db, event.id, team.id)


def jam(db: Session, event: Event, team: Team, seconds: int, now: datetime, reason: str) -> None:
    base = team.jammed_until if is_jammed(team, now) else now
    team.jammed_until = base + timedelta(seconds=seconds)
    audit.log_game(db, event.id, team.id, "RADAR_JAMMED", f"{team.team_name}'s radar jammed for {seconds}s ({reason})")
    audit.notify_team(db, team.id, {"type": "jammed", "jammed_until": iso(team.jammed_until), "reason": reason})
    audit.team_changed(db, event.id, team.id)


def trap(db: Session, event: Event, team: Team, now: datetime, reason: str) -> None:
    team.foul_count += 1
    db.add(Foul(event_id=event.id, team_id=team.id, reason=f"Trapped by a rival team ({reason})", source="SYSTEM", created_at=now))
    audit.log_game(db, event.id, team.id, "TEAM_TRAPPED", f"{team.team_name} walked into a trap - foul +1 ({reason})")
    audit.notify_team(db, team.id, {"type": "trapped", "foul_count": team.foul_count, "reason": reason})
    audit.team_changed(db, event.id, team.id)


def apply_attack(db: Session, event: Event, kind: str, victim: Team, now: datetime, reason: str) -> None:
    settings = event_settings(event)
    if kind == PowerKind.FREEZE:
        freeze(db, event, victim, int(settings["freeze_duration_s"]), now, reason)
    elif kind == PowerKind.JAM:
        jam(db, event, victim, int(settings["jam_duration_s"]), now, reason)
    elif kind == PowerKind.TRAP:
        trap(db, event, victim, now, reason)


def attack_effect_text(event: Event, kind: str) -> str:
    return ATTACK_EFFECT[kind].format(**event_settings(event))


# ---------------------------------------------------------------------------
# Guide (help) and Ward (defence armed in advance)
# ---------------------------------------------------------------------------


def guide(db: Session, event: Event, team: Team, now: datetime) -> dict:
    assert_can_play(event, team, now)
    if team.status not in (TeamStatus.ACTIVE, TeamStatus.FINAL):
        raise ConflictError("Solve your puzzle first - the Guide shows the way to your next checkpoint.")
    if is_guided(team, now):
        raise ConflictError("Your Guide is already active - open the radar.")
    tp = _spend(db, team.id, PowerKind.GUIDE)
    seconds = int(event_settings(event)["guide_duration_s"])
    team.guide_until = now + timedelta(seconds=seconds)
    db.add(PowerUsage(event_id=event.id, kind=PowerKind.GUIDE, team_id=team.id, status=UsageStatus.USED, created_at=now, resolved_at=now))
    audit.log_game(db, event.id, team.id, "GUIDE_USED", f"{team.team_name} used a Guide to checkpoint {team.progress + 1}")
    audit.team_changed(db, event.id, team.id)
    return {
        "message": f"Guide active for {seconds // 60} min - open the radar for the exact way.",
        "guide_until": iso(team.guide_until),
        "remaining": tp.remaining,
    }


def ward(db: Session, event: Event, team: Team, now: datetime) -> dict:
    assert_can_play(event, team, now, allow_frozen=True)
    if is_warded(team, now):
        raise ConflictError("Your Ward is already up.")
    tp = _spend(db, team.id, PowerKind.WARD)
    seconds = int(event_settings(event)["ward_duration_s"])
    team.warded_until = now + timedelta(seconds=seconds)
    db.add(PowerUsage(event_id=event.id, kind=PowerKind.WARD, team_id=team.id, status=UsageStatus.USED, created_at=now, resolved_at=now))
    audit.log_game(db, event.id, team.id, "WARD_RAISED", f"{team.team_name} raised a Ward for {seconds}s")
    audit.team_changed(db, event.id, team.id)
    return {
        "message": f"Ward up for {seconds // 60} min - attacks bounce off automatically.",
        "warded_until": iso(team.warded_until),
        "remaining": tp.remaining,
    }


# ---------------------------------------------------------------------------
# Attack / Defence
# ---------------------------------------------------------------------------


def pending_attack_on(db: Session, team_id: str) -> PowerUsage | None:
    return db.scalar(
        select(PowerUsage)
        .where(
            PowerUsage.kind.in_(PowerKind.ATTACKS),
            PowerUsage.target_team_id == team_id,
            PowerUsage.status == UsageStatus.PENDING,
        )
        .order_by(PowerUsage.created_at)
        .limit(1)
    )


def attack(db: Session, event: Event, attacker: Team, target: Team, kind: str, now: datetime) -> dict:
    assert_can_play(event, attacker, now)
    if kind not in PowerKind.ATTACKS:
        raise AppError("That isn't an attack power.")
    label = PowerKind.LABEL[kind]
    if target.id == attacker.id:
        raise AppError("You can't attack your own team.")
    if target.event_id != event.id:
        raise NotFoundError("Target team not found.")
    # Check the attacker's own inventory first, so a team with nothing to
    # spend can't use the rejection messages below to probe rivals' status.
    tp = _team_power(db, attacker.id, kind)
    if tp.remaining < 1:
        raise ConflictError(f"You have no {label} power left.")
    if target.status in (TeamStatus.COMPLETED, TeamStatus.DISQUALIFIED) or target.status not in TeamStatus.PLAYING:
        raise ConflictError(f"{target.team_name} is out of play and can't be attacked.")
    if target.started_at is not None and now < target.started_at:
        raise ConflictError(f"{target.team_name} hasn't started yet.")
    settings = event_settings(event)
    if not settings["allow_attack_frozen"]:
        if kind == PowerKind.FREEZE and is_frozen(target, now):
            raise ConflictError(f"{target.team_name} is already frozen and can't be attacked again.")
        if kind == PowerKind.JAM and is_jammed(target, now):
            raise ConflictError(f"{target.team_name}'s radar is already jammed.")
    if pending_attack_on(db, target.id) is not None:
        raise ConflictError(f"{target.team_name} is already responding to another attack. Try again shortly.")

    tp.used += 1  # consumed on use (spec)

    if is_warded(target, now):
        # No prompt: the Ward takes the hit. The attacker learns only that it bounced.
        usage = PowerUsage(
            event_id=event.id, kind=kind, team_id=attacker.id, target_team_id=target.id,
            status=UsageStatus.CANCELLED, resolved_with=PowerKind.WARD, created_at=now, resolved_at=now,
        )
        db.add(usage)
        db.flush()
        audit.log_game(db, event.id, attacker.id, "ATTACK_WARDED", f"{attacker.team_name}'s {label} bounced off {target.team_name}'s Ward")
        audit.notify_team(db, target.id, {"type": "toast", "message": f"Your Ward just blocked a {label} attack."})
        audit.team_changed(db, event.id, attacker.id)
        audit.team_changed(db, event.id, target.id)
        return {
            "usage_id": usage.id,
            "kind": kind,
            "status": usage.status,
            "resolved_with": PowerKind.WARD,
            "expires_at": None,
            "message": f"{target.team_name} has a Ward up - your {label} bounced off.",
            "remaining": tp.remaining,
        }

    window = int(settings["attack_response_window_s"])
    usage = PowerUsage(
        event_id=event.id,
        kind=kind,
        team_id=attacker.id,
        target_team_id=target.id,
        status=UsageStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(seconds=window),
    )
    db.add(usage)
    db.flush()
    audit.log_game(db, event.id, attacker.id, "ATTACK", f"{attacker.team_name} sent a {label} at {target.team_name}")
    # The target isn't told who attacked: power use is coordinator-only info.
    audit.notify_team(
        db,
        target.id,
        {"type": "attack_incoming", "usage_id": usage.id, "kind": kind, "expires_at": iso(usage.expires_at), "window_s": window},
    )
    audit.team_changed(db, event.id, attacker.id)
    audit.team_changed(db, event.id, target.id)
    return {
        "usage_id": usage.id,
        "kind": kind,
        "status": usage.status,
        "resolved_with": None,
        "expires_at": iso(usage.expires_at),
        "message": f"{label} sent to {target.team_name}. They have {window}s to respond.",
        "remaining": tp.remaining,
    }


def _resolve(db: Session, usage_id: str, new_status: str, resolved_with: str, now: datetime) -> bool:
    """Compare-and-set PENDING -> new_status. True only for the winner."""
    result = db.execute(
        update(PowerUsage)
        .where(PowerUsage.id == usage_id, PowerUsage.status == UsageStatus.PENDING)
        .values(status=new_status, resolved_with=resolved_with, resolved_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _already(usage: PowerUsage, target: Team) -> dict:
    return {"status": usage.status, "resolved_with": usage.resolved_with, "message": "This attack has already been resolved.", "frozen_until": iso(target.frozen_until)}


def _tell_attacker(db: Session, attacker: Team | None, usage: PowerUsage, target: Team, status: str, resolved_with: str) -> None:
    if attacker:
        audit.notify_team(db, attacker.id, {"type": "attack_result", "kind": usage.kind, "status": status, "resolved_with": resolved_with, "target_name": target.team_name})


def respond(db: Session, event: Event, target: Team, usage_id: str, defence: str | None, now: datetime) -> dict:
    """Answer an incoming attack: ``defence`` is SHIELD, REFLECT, or None to accept it."""
    usage = db.get(PowerUsage, usage_id)
    if usage is None or usage.kind not in PowerKind.ATTACKS or usage.target_team_id != target.id:
        raise NotFoundError("That attack doesn't exist.")
    if defence is not None and defence not in PowerKind.RESPONSES:
        raise AppError("Answer with a Shield, a Reflect, or accept the attack.")
    db.refresh(usage)
    if usage.status != UsageStatus.PENDING:
        return _already(usage, target)
    if event.status != EventStatus.LIVE:
        raise ConflictError("The game isn't running right now.")

    label = PowerKind.LABEL[usage.kind]
    attacker = db.get(Team, usage.team_id)

    if usage.expires_at is not None and now >= usage.expires_at:
        if _resolve(db, usage.id, UsageStatus.EXPIRED, "TIMEOUT", now):
            apply_attack(db, event, usage.kind, target, now, "attack not answered in time")
            _tell_attacker(db, attacker, usage, target, UsageStatus.EXPIRED, "TIMEOUT")
        return {"status": UsageStatus.EXPIRED, "resolved_with": "TIMEOUT", "message": f"Too late - the response window closed. The {label} landed.", "frozen_until": iso(target.frozen_until)}

    if defence is not None:
        tp = _team_power(db, target.id, defence)
        if tp.remaining < 1:
            raise ConflictError(f"You have no {PowerKind.LABEL[defence]} power left - accept the attack instead.")
        if not _resolve(db, usage.id, UsageStatus.CANCELLED, defence, now):
            db.refresh(usage)
            return _already(usage, target)
        tp.used += 1
        db.add(
            PowerUsage(
                event_id=event.id,
                kind=defence,
                team_id=target.id,
                target_team_id=usage.team_id,
                status=UsageStatus.USED,
                created_at=now,
                resolved_at=now,
            )
        )
        who = attacker.team_name if attacker else "?"
        if defence == PowerKind.REFLECT:
            audit.log_game(db, event.id, target.id, "ATTACK_REFLECTED", f"{target.team_name} reflected {who}'s {label}")
            # The bounce lands at once: a reflected attack can't be defended again.
            if attacker is not None and attacker.status in TeamStatus.PLAYING:
                apply_attack(db, event, usage.kind, attacker, now, f"{label} reflected by {target.team_name}")
            message = f"REFLECTED - the {label} bounced back at them."
        else:
            audit.log_game(db, event.id, target.id, "ATTACK_DEFENDED", f"{target.team_name} blocked {who}'s {label} with a Shield")
            message = f"DEFENDED - the {label} was blocked."
        _tell_attacker(db, attacker, usage, target, UsageStatus.CANCELLED, defence)
        audit.team_changed(db, event.id, target.id)
        return {"status": UsageStatus.CANCELLED, "resolved_with": defence, "message": message, "frozen_until": None}

    if not _resolve(db, usage.id, UsageStatus.CONFIRMED, "ACCEPTED", now):
        db.refresh(usage)
        return _already(usage, target)
    apply_attack(db, event, usage.kind, target, now, "attack accepted")
    _tell_attacker(db, attacker, usage, target, UsageStatus.CONFIRMED, "ACCEPTED")
    return {"status": UsageStatus.CONFIRMED, "resolved_with": "ACCEPTED", "message": f"{label} accepted.", "frozen_until": iso(target.frozen_until)}


def expire_due_attacks(db: Session, event: Event, now: datetime) -> int:
    """Apply attacks whose response window ran out. Returns how many.

    Safe to call from anywhere, and concurrently: each attack is claimed with
    a compare-and-set, and the target's lock is held while the effect lands.
    Callers must not already hold a team lock.
    """
    if event.status != EventStatus.LIVE:
        return 0
    due = list(
        db.scalars(
            select(PowerUsage).where(
                PowerUsage.event_id == event.id,
                PowerUsage.kind.in_(PowerKind.ATTACKS),
                PowerUsage.status == UsageStatus.PENDING,
                PowerUsage.expires_at <= now,
            )
        )
    )
    count = 0
    for usage in due:
        with team_locks(usage.target_team_id):
            if not _resolve(db, usage.id, UsageStatus.EXPIRED, "TIMEOUT", now):
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
                apply_attack(db, event, usage.kind, target, now, "attack not answered in time")
            audit.notify_team(db, usage.team_id, {"type": "attack_result", "kind": usage.kind, "status": UsageStatus.EXPIRED, "resolved_with": "TIMEOUT", "target_name": target.team_name})
            db.commit()
            count += 1
    return count


def family_usage(db: Session, event_id: str) -> dict[tuple[str, str], int]:
    """(team_id, family) -> how many powers of that family the team used."""
    counts: dict[tuple[str, str], int] = {}
    for u in db.scalars(select(PowerUsage).where(PowerUsage.event_id == event_id)):
        family = PowerKind.FAMILY.get(u.kind)
        if family is None:
            continue
        key = (u.team_id, family)
        counts[key] = counts.get(key, 0) + 1
    return counts
