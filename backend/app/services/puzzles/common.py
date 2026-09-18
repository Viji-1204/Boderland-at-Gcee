"""Shared bits for the built-in puzzle types."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.exceptions import AppError


@dataclass
class Outcome:
    solved: bool = False
    message: str = ""
    # A checked answer or submission: counts as an attempt and starts the
    # short retry cooldown. Game moves (rock-paper-scissors, X/O) don't.
    attempt: bool = False
    extra: dict = field(default_factory=dict)


def normalise(value: str | None) -> str:
    """Case, spacing and trailing punctuation never matter."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,!?;:'\"`")


def matches(given: str | None, *accepted: str) -> bool:
    target = normalise(given)
    return bool(target) and any(target == normalise(a) for a in accepted)


def need_text(payload: dict, what: str = "an answer") -> str:
    text = str(payload.get("answer") or "").strip()
    if not text:
        raise AppError(f"Type {what} first.")
    return text
