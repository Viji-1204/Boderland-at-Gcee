"""Built-in checkpoint puzzles - nobody writes puzzles for an event.

Every checkpoint gets one of six fixed types by its number, repeating:

    L01 scrambled words   L02 picture puzzle   L03 rock paper scissors
    L04 X/O game          L05 riddle           L06 crossword
    L07 scrambled words   L08 picture puzzle   ... L12 crossword

Each team gets its own version at each checkpoint (its own words, riddle,
crossword and shuffle), so answers can't be passed between teams, and a
team's two checkpoints of the same type never repeat. The games are played
against the server - the phone only sends moves - so a result can't be faked.
"""
from __future__ import annotations

import hashlib
import re
from types import ModuleType

from app.services.puzzles import crossword, picture, riddle, rps, scramble, tictactoe
from app.services.puzzles.common import Outcome

ORDER: list[ModuleType] = [scramble, picture, rps, tictactoe, riddle, crossword]
BY_KIND: dict[str, ModuleType] = {m.KIND: m for m in ORDER}

__all__ = ["BY_KIND", "ORDER", "Outcome", "kind_for_code", "label", "pick"]


def kind_for_code(code: str) -> str:
    """L01 -> scramble, L02 -> picture, ... L07 -> scramble again."""
    number = int(re.sub(r"\D", "", code or "") or 1)
    return ORDER[(number - 1) % len(ORDER)].KIND


def label(kind: str) -> str:
    return BY_KIND[kind].LABEL


def pick(team_id: str, kind: str, occurrence: int, size: int) -> int:
    """Which version a team gets: fixed per team (so a reload shows the same
    puzzle), different between teams, and never the same one twice for one
    team (``occurrence`` counts its earlier checkpoints of this type)."""
    base = int(hashlib.sha256(f"{team_id}:{kind}".encode()).hexdigest()[:8], 16)
    return (base + occurrence) % size
