"""Password hashing and JWTs - the same scheme as Round 1 (bcrypt + HS256).

Tokens carry ``type`` = ``team`` | ``admin`` so a team token can never be used
on an admin endpoint (or the other way round).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# Checked when a login names no existing account, so a wrong team code takes
# as long as a wrong password and response times can't reveal which codes exist.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt()).decode("utf-8")


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def password_fingerprint(password_hash: str) -> str:
    """Short digest of the current password hash, carried in tokens as ``pwv``:
    changing a password invalidates every token issued before the change."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, token_type: str, extra_claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
