"""3 - Rock paper scissors against the computer: first to 2 wins.

The server throws its hand only after the team's throw arrives, so the
phone can never see it in advance. Lose the match and a new one starts.
"""
from __future__ import annotations

import random

from app.core.exceptions import AppError
from app.services.puzzles.common import Outcome

KIND = "rps"
LABEL = "Rock paper scissors"
INSTRUCTIONS = "Beat the computer: first to 2 wins. Lose, and a new match starts."
CHECKED = False
SIZE = 1

THROWS = ("rock", "paper", "scissors")
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
TARGET = 2


def computer_throw(rng: random.Random) -> str:
    return rng.choice(THROWS)


def new_state(index: int, rng: random.Random) -> dict:
    return {"you": 0, "cpu": 0, "matches_lost": 0, "last": None}


def view(state: dict) -> dict:
    return {"you": state["you"], "cpu": state["cpu"], "target": TARGET, "matches_lost": state["matches_lost"], "last": state["last"]}


def act(state: dict, payload: dict, rng: random.Random) -> Outcome:
    mine = str(payload.get("move") or "").lower()
    if mine not in THROWS:
        raise AppError("Pick rock, paper or scissors.")
    theirs = computer_throw(rng)
    result = "draw" if mine == theirs else ("win" if BEATS[mine] == theirs else "lose")
    if result == "win":
        state["you"] += 1
    elif result == "lose":
        state["cpu"] += 1
    state["last"] = {"you": mine, "cpu": theirs, "result": result, "score": [state["you"], state["cpu"]]}
    if state["you"] >= TARGET:
        return Outcome(solved=True, message=f"You won the match {state['you']}-{state['cpu']}!")
    if state["cpu"] >= TARGET:
        state["matches_lost"] += 1
        state["you"] = state["cpu"] = 0
        return Outcome(message="The computer won that match. New match - go again!")
    return Outcome(message={"win": "You win this round!", "lose": "The computer wins this round.", "draw": "Draw - throw again."}[result])


def solution(state: dict) -> list[dict]:
    """With computer_throw rigged to 'scissors' (tests / smoke run only)."""
    return [{"move": "rock"}] * TARGET
