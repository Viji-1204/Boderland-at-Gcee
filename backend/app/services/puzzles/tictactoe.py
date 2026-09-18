"""4 - X/O (tic-tac-toe) against the computer: you must WIN a game.

The team is X and moves first; the server plays O. The computer always
takes a win and usually blocks, but not always - so careful play wins.
A draw or a loss starts a new game.
"""
from __future__ import annotations

import random

from app.core.exceptions import AppError
from app.services.puzzles.common import Outcome

KIND = "tictactoe"
LABEL = "X/O game"
INSTRUCTIONS = "You are X and go first. Win a game against the computer (a draw doesn't count)."
CHECKED = False
SIZE = 1

EMPTY = "."
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
BLOCK_CHANCE = 0.6  # how often the computer spots your winning threat


def winner(board: str) -> str | None:
    for a, b, c in LINES:
        if board[a] != EMPTY and board[a] == board[b] == board[c]:
            return board[a]
    return None


def _place(board: str, i: int, mark: str) -> str:
    return board[:i] + mark + board[i + 1:]


def ai_move(board: str, rng: random.Random) -> int:
    empty = [i for i, ch in enumerate(board) if ch == EMPTY]
    for i in empty:  # win when it can
        if winner(_place(board, i, "O")) == "O":
            return i
    threats = [i for i in empty if winner(_place(board, i, "X")) == "X"]
    if threats and rng.random() < BLOCK_CHANCE:
        return rng.choice(threats)
    if 4 in empty and rng.random() < 0.5:
        return 4
    return rng.choice(empty)


def new_state(index: int, rng: random.Random) -> dict:
    return {"board": EMPTY * 9, "games": 0, "last": None}


def view(state: dict) -> dict:
    return {"board": state["board"], "games": state["games"], "last": state["last"]}


def act(state: dict, payload: dict, rng: random.Random) -> Outcome:
    move = payload.get("move")
    board = state["board"]
    if not isinstance(move, int) or not 0 <= move < 9 or board[move] != EMPTY:
        raise AppError("Pick an empty square.")
    board = _place(board, move, "X")
    if winner(board) == "X":
        state["board"] = board
        return Outcome(solved=True, message="You beat the computer!")
    if EMPTY in board:
        board = _place(board, ai_move(board, rng), "O")
    if winner(board) == "O" or EMPTY not in board:
        lost = winner(board) == "O"
        state["games"] += 1
        state["last"] = {"result": "lost" if lost else "draw", "board": board}
        state["board"] = EMPTY * 9
        return Outcome(message="The computer won - new game, you go first." if lost else "Draw - you need a win. New game!")
    state["board"] = board
    state["last"] = None
    return Outcome(message="Your move.")


def solution(state: dict) -> list[dict]:
    """With ai_move rigged to always take the last empty square (tests only)."""
    return [{"move": 0}, {"move": 1}, {"move": 2}]
