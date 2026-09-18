"""6 - Crossword: fill in a small crossword from its clues."""
from __future__ import annotations

import random

from app.core.exceptions import AppError
from app.services.puzzles.common import Outcome

KIND = "crossword"
LABEL = "Crossword"
INSTRUCTIONS = "Fill in every word from the clues, then press Check."
CHECKED = True

# Letters and "." for blank squares. The words are read off the grid
# (every run of 2+ letters), so a clue can never disagree with the grid.
CROSSWORDS: list[dict] = [
    {
        "grid": ["JOKER...", "A.I.O...", "C.N.U...", "K.G.N...", "....DECK", "......L.", "......U.", "......B."],
        "clues": {
            "JOKER": "The wild card - you'll find him at the final destination",
            "JACK": "The first face card you must collect",
            "KING": "The last face card you must collect",
            "ROUND": "This hunt is ___ 2",
            "DECK": "All 52 cards together",
            "CLUB": "The suit shaped like a clover",
        },
    },
    {
        "grid": ["CAMPUS", "L.A..T", "A.P..U", "S....D", "SCAN.Y"],
        "clues": {
            "CAMPUS": "Where this hunt happens",
            "CLASS": "Where lectures happen",
            "MAP": "Shows the way - you only get a radar",
            "STUDY": "What you do before exams",
            "SCAN": "What you do to a QR code",
        },
    },
    {
        "grid": ["ALICE.....", "C..A......", "E..R......", "...DIAMOND", ".........E", ".........A", ".........L"],
        "clues": {
            "ALICE": "Arisu's name in English",
            "ACE": "The card worth 1 (or 11)",
            "CARD": "Every game here gives you one",
            "DIAMOND": "The suit of the intelligence games",
            "DEAL": "To hand out the cards",
        },
    },
]
SIZE = len(CROSSWORDS)


def entries(grid: list[str]) -> list[dict]:
    """Numbered across/down entries, numbered like a printed crossword."""
    rows, cols = len(grid), len(grid[0])

    def letter(r: int, c: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols and grid[r][c] != "."

    found, number = [], 0
    for r in range(rows):
        for c in range(cols):
            if not letter(r, c):
                continue
            starts_across = not letter(r, c - 1) and letter(r, c + 1)
            starts_down = not letter(r - 1, c) and letter(r + 1, c)
            if not (starts_across or starts_down):
                continue
            number += 1
            for direction, (dr, dc), starts in (("across", (0, 1), starts_across), ("down", (1, 0), starts_down)):
                if not starts:
                    continue
                cells, rr, cc = [], r, c
                while letter(rr, cc):
                    cells.append((rr, cc))
                    rr, cc = rr + dr, cc + dc
                found.append({"n": number, "dir": direction, "row": r, "col": c, "cells": cells,
                              "word": "".join(grid[x][y] for x, y in cells)})
    return found


def new_state(index: int, rng: random.Random) -> dict:
    return {"item": index % SIZE}


def view(state: dict) -> dict:
    puzzle = CROSSWORDS[state["item"]]
    grid = puzzle["grid"]
    found = entries(grid)
    numbers = {(e["row"], e["col"]): e["n"] for e in found}
    return {
        "rows": len(grid),
        "cols": len(grid[0]),
        # None = blank square; otherwise the clue number printed in it (or 0)
        "cells": [[None if ch == "." else numbers.get((r, c), 0) for c, ch in enumerate(row)] for r, row in enumerate(grid)],
        "across": [{"n": e["n"], "clue": puzzle["clues"][e["word"]], "len": len(e["word"])} for e in found if e["dir"] == "across"],
        "down": [{"n": e["n"], "clue": puzzle["clues"][e["word"]], "len": len(e["word"])} for e in found if e["dir"] == "down"],
    }


def act(state: dict, payload: dict, rng: random.Random) -> Outcome:
    grid = CROSSWORDS[state["item"]]["grid"]
    filled = payload.get("grid")
    if not isinstance(filled, list) or len(filled) != len(grid):
        raise AppError("Send the whole crossword grid.")
    rows = [str(row or "").upper().ljust(len(grid[0]))[: len(grid[0])] for row in filled]
    wrong = [
        f"{e['n']} {e['dir'].title()}"
        for e in entries(grid)
        if "".join(rows[r][c] for r, c in e["cells"]) != e["word"]
    ]
    if not wrong:
        return Outcome(solved=True, message="Crossword complete!", attempt=True)
    return Outcome(
        message=f"{len(wrong)} {'word isn' if len(wrong) == 1 else 'words aren'}'t right yet: {', '.join(wrong)}.",
        attempt=True,
        extra={"wrong": wrong},
    )


def solution(state: dict) -> list[dict]:
    return [{"grid": [row.replace(".", " ") for row in CROSSWORDS[state["item"]]["grid"]]}]
