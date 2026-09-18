"""5 - Riddles."""
from __future__ import annotations

import random

from app.services.puzzles.common import Outcome, matches, need_text

KIND = "riddle"
LABEL = "Riddle"
INSTRUCTIONS = "Solve the riddle and type the answer."
CHECKED = True

# (riddle, answer, other accepted answers, hint)
ITEMS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("I have keys but open no locks, space but no room. What am I?", "keyboard", ("a keyboard",), "You type on me."),
    ("The more you take, the more you leave behind. What are they?", "footsteps", ("steps", "foot steps"), "Look down while you walk."),
    ("What has one eye but can't see?", "needle", ("a needle",), "Used for sewing."),
    ("What gets wetter the more it dries?", "towel", ("a towel",), "You use it after a bath."),
    ("I speak without a mouth and hear without ears. I have no body, but I come alive with the wind. What am I?",
     "echo", ("an echo",), "Shout in an empty hall."),
    ("What has a neck but no head, and wears a cap?", "bottle", ("a bottle",), "You drink from it."),
    ("What can travel around the world while staying in one corner?", "stamp", ("a stamp", "postage stamp"), "Look at an envelope."),
    ("I have cities but no houses, forests but no trees, rivers but no water. What am I?", "map", ("a map",),
     "You'd want me on a treasure hunt."),
    ("What has 52 cards, 4 suits and no clothes?", "deck", ("a deck", "deck of cards", "a deck of cards"),
     "Borderland is played with one."),
    ("Forward I am heavy, backward I am not. What am I?", "ton", ("a ton",), "Spell the answer backwards."),
    ("What comes once in a minute, twice in a moment, but never in a thousand years?", "m", ("the letter m", "letter m"),
     "Look at how the words are spelled."),
    ("What belongs to you, but other people use it more than you do?", "name", ("your name", "my name"), "People call you by it."),
    ("What has hands but can't clap?", "clock", ("a clock", "watch", "a watch"), "It's on the wall - or your wrist."),
    ("The one who makes it sells it. The one who buys it never uses it. The one who uses it never knows. What is it?",
     "coffin", ("a coffin",), "Borderland is a deadly game."),
]
SIZE = len(ITEMS)


def new_state(index: int, rng: random.Random) -> dict:
    return {"item": index % SIZE}


def view(state: dict) -> dict:
    question, _answer, _alts, hint = ITEMS[state["item"]]
    return {"question": question, "hint": hint}


def act(state: dict, payload: dict, rng: random.Random) -> Outcome:
    _question, answer, alts, _hint = ITEMS[state["item"]]
    if matches(need_text(payload), answer, *alts):
        return Outcome(solved=True, message="Riddle solved!", attempt=True)
    return Outcome(message="Not quite - try again. No penalty.", attempt=True)


def solution(state: dict) -> list[dict]:
    return [{"answer": ITEMS[state["item"]][1]}]
