"""1 - Scrambled words or sentence: put the letters (or words) back in order."""
from __future__ import annotations

import random

from app.services.puzzles.common import Outcome, matches, need_text

KIND = "scramble"
LABEL = "Scrambled words"
INSTRUCTIONS = "Unscramble it and type the answer."
CHECKED = True

# (answer, clue, other accepted answers). A single word is shown as shuffled
# letters; a sentence as shuffled words.
ITEMS: list[tuple[str, str, tuple[str, ...]]] = [
    ("BORDERLAND", "Where this game takes place", ()),
    ("CHECKPOINT", "What you are standing at", ()),
    ("TREASURE", "What every hunt is for", ()),
    ("DIAMONDS", "The suit of the intelligence games", ()),
    ("ENGINEER", "What this college turns you into", ()),
    ("SURVIVAL", "What Borderland is really about", ()),
    ("STRATEGY", "A plan to win", ()),
    ("VICTORY", "What you're playing for", ()),
    ("COMPASS", "It always points north", ()),
    ("MYSTERY", "Something nobody has solved yet", ()),
    ("KNOWLEDGE", "Power, they say", ()),
    ("THE JOKER IS WILD", "A saying about the wild card", ("IS THE JOKER WILD",)),
    ("ALICE ENTERS BORDERLAND", "How the story begins", ()),
    ("TRUST YOUR OWN TEAM", "Advice for the Hearts games", ()),
    ("READ THE RULES CAREFULLY", "Before every game", ("CAREFULLY READ THE RULES",)),
    ("NEVER GIVE UP THE HUNT", "Keep going!", ()),
    ("YOUR VISA IS RUNNING OUT", "Better hurry", ("IS YOUR VISA RUNNING OUT",)),
]
SIZE = len(ITEMS)


def new_state(index: int, rng: random.Random) -> dict:
    answer, clue, _alts = ITEMS[index % SIZE]
    sentence = " " in answer
    parts = answer.split() if sentence else list(answer)
    tiles = parts[:]
    while tiles == parts:  # never hand out the answer itself
        rng.shuffle(tiles)
    return {"item": index % SIZE, "mode": "words" if sentence else "letters", "tiles": tiles, "clue": clue}


def view(state: dict) -> dict:
    return {"mode": state["mode"], "tiles": state["tiles"], "count": len(state["tiles"]), "hint": state["clue"]}


def act(state: dict, payload: dict, rng: random.Random) -> Outcome:
    answer, _clue, alts = ITEMS[state["item"]]
    given = need_text(payload)
    accepted = [answer, *alts]
    if state["mode"] == "letters":  # "border land" is still BORDERLAND
        given = given.replace(" ", "")
    if matches(given, *accepted):
        return Outcome(solved=True, message="Unscrambled!", attempt=True)
    return Outcome(message="Not quite - try again. No penalty.", attempt=True)


def solution(state: dict) -> list[dict]:
    return [{"answer": ITEMS[state["item"]][0]}]
