"""2 - Scrambled picture: swap the tiles until the picture is whole again.

The phone shows the tiles and sends the swaps it made; the server replays
them from the shuffle it dealt, so "solved" can't simply be claimed.
"""
from __future__ import annotations

import random

from app.core.exceptions import AppError
from app.services.puzzles.common import Outcome

KIND = "picture"
LABEL = "Picture puzzle"
INSTRUCTIONS = "Tap two tiles to swap them. Rebuild the picture."
CHECKED = True

IMAGES = ["king", "queen", "jack", "joker"]  # drawn by the team app (puzzle-art.js)
SIDE = 3
TILES = SIDE * SIDE
SIZE = len(IMAGES)
MAX_SWAPS = 400


def new_state(index: int, rng: random.Random) -> dict:
    order = list(range(TILES))
    # At least 6 tiles out of place, so it's a real puzzle.
    while sum(1 for i, t in enumerate(order) if i != t) < 6:
        rng.shuffle(order)
    return {"image": IMAGES[index % SIZE], "side": SIDE, "order": order}


def view(state: dict) -> dict:
    return {"image": state["image"], "side": state["side"], "order": state["order"]}


def act(state: dict, payload: dict, rng: random.Random) -> Outcome:
    swaps = payload.get("swaps")
    if not isinstance(swaps, list) or len(swaps) > MAX_SWAPS:
        raise AppError("Send the swaps you made.")
    order = list(state["order"])
    for pair in swaps:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(i, int) and 0 <= i < TILES for i in pair)):
            raise AppError("That isn't a valid swap.")
        a, b = pair
        order[a], order[b] = order[b], order[a]
    if order == list(range(TILES)):
        return Outcome(solved=True, message="Picture complete!", attempt=True)
    return Outcome(message="The picture isn't complete yet - keep swapping.", attempt=True)


def solution(state: dict) -> list[dict]:
    order, swaps = list(state["order"]), []
    for i in range(TILES):
        j = order.index(i)
        if j != i:
            order[i], order[j] = order[j], order[i]
            swaps.append([i, j])
    return [{"swaps": swaps}]
