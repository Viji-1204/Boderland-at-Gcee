"""The secret sentences (spec section 14), dealt to teams automatically.

Twenty original lines in the spirit of Alice in Borderland - visas, the
four suits, the games, the Beach, the Joker. Each has 10 to 13 words, so it
splits cleanly into one fragment per checkpoint (7-9 of them). A team made
without a sentence gets one nobody else in the game has; once all twenty
are out, the least-used one is dealt again. A coordinator can still type
their own sentence, or change the dealt one, while the game is in DRAFT.
"""
from __future__ import annotations

import random
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Team

SENTENCES: tuple[str, ...] = (
    "ONLY THE PLAYERS WHO FINISH EVERY GAME KEEP THEIR VISA ALIVE",
    "WHEN THE FIREWORKS FADE THE BORDERLAND OPENS ITS FIRST DOOR",
    "A HEART GAME IS WON BY TRUSTING THE ONE YOU FEAR",
    "SPADES TEST THE BODY DIAMONDS TEST THE MIND CLUBS TEST THE TEAM",
    "THE QUEEN OF HEARTS SMILES ONLY WHEN THE CLOCK RUNS OUT",
    "EVERY VISA EXPIRES BUT COURAGE IS STAMPED FOR ONE MORE DAY",
    "THE BEACH PROMISED PARADISE AND SOLD EVERY CARD TWICE OVER",
    "FOLLOW THE LASER INTO THE DARK AND WALK OUT WITH A CARD",
    "THE KING OF SPADES HUNTS ALONE BUT THE HUNTED RUN TOGETHER",
    "A JOKER HIDES WHERE THE LAST FACE CARD FALLS SILENT",
    "THE GAME IS CLEARED WHEN EVERY PLAYER CROSSES THE SAME LINE",
    "NO ONE LEAVES THE BORDERLAND UNTIL THE FINAL CARD IS DRAWN",
    "THE JACK OF HEARTS TRADES IN SECRETS AND PAYS IN SILENCE",
    "TAG THE HORSE BUT NEVER LET THE HUNTER SEE YOUR FACE",
    "THE DIAMONDS ARE COUNTED THE ANSWER IS ONE AND THE DOOR IS OPEN",
    "A CLUBS GAME NEEDS EVERY HAND OR THE WHOLE TEAM FALLS",
    "THE SHOOTING STAR WAS THE SIGN THAT THE GAMES HAD BEGUN",
    "COLLECT THE FACE CARDS AND THE JOKER WILL COME TO YOU",
    "HOLD YOUR NERVE AT THE BONFIRE THE TIMER IS ONLY A GAME",
    "WHOEVER READS THIS SENTENCE WHOLE HAS ALREADY WON THE BORDERLAND",
)


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def deal(db: Session, event_id: str, rng: random.Random | None = None) -> str:
    """A sentence no other team in the game has - or, past twenty teams,
    the one dealt the fewest times."""
    rng = rng or random.SystemRandom()
    in_use = Counter(_norm(s) for s in db.scalars(select(Team.sentence).where(Team.event_id == event_id)) if s)
    fewest = min((in_use.get(_norm(s), 0) for s in SENTENCES), default=0)
    candidates = [s for s in SENTENCES if in_use.get(_norm(s), 0) == fewest]
    return rng.choice(candidates)


def fill_missing(db: Session, event_id: str, rng: random.Random | None = None) -> int:
    """Deal a sentence to every team in the game that has none. Returns how many."""
    count = 0
    for team in db.scalars(select(Team).where(Team.event_id == event_id).order_by(Team.team_name)):
        if not (team.sentence or "").strip():
            team.sentence = deal(db, event_id, rng)
            db.flush()  # so the next deal sees it
            count += 1
    return count
