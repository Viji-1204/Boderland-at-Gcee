"""Per-team serialisation of game-changing actions (spec section 7/10).

Several phones can share one team login. Every write for a team (scan, puzzle
answer, power use, admin override) runs inside ``team_locks(team_id)`` and
re-reads the team row after acquiring it, so two members acting at the same
instant are applied one after the other against fresh state.

These are in-process locks: they cover one API process. For several
processes, the services also use ``SELECT ... FOR UPDATE`` on Postgres and
compare-and-set UPDATEs for attack resolution.

Locks are always taken in sorted order, and callers never take a second lock
while holding one out of order, so two locks can't deadlock.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def _lock_for(key: str) -> threading.RLock:
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


@contextmanager
def team_locks(*team_ids: str | None) -> Iterator[None]:
    ids = sorted({t for t in team_ids if t})
    acquired: list[threading.RLock] = []
    try:
        for team_id in ids:
            lock = _lock_for(team_id)
            lock.acquire()
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()
