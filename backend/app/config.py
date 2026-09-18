"""Runtime settings.

Every value can be overridden with an environment variable of the same name
(case-insensitive) or a line in ``backend/.env``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

logger = logging.getLogger("round2.config")

_PLACEHOLDER_SECRETS = {
    "",
    "change-me",
    "change-me-in-prod",
    "REPLACE_WITH_A_REAL_RANDOM_SECRET",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    environment: str = "development"

    # Absolute by default, so the database no longer depends on the directory
    # the server is started from (the old relative ./round2.db did).
    database_url: str = f"sqlite:///{(DATA_DIR / 'round2.db').as_posix()}"
    # Apply Alembic migrations at startup. Never drops data.
    auto_migrate: bool = True
    # On a brand-new database, create a ready-to-play demo event. Unset means
    # "only in development"; SEED_DEMO=true also allows it in production (a
    # dry run on the real server), SEED_DEMO=false never.
    seed_demo: bool | None = None

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # The first SUPER_ADMIN is created from these if it doesn't exist yet
    # (same mechanism as Round 1's seed_admin).
    admin_username: str = "admin"
    admin_password: str = "admin123"

    cors_origins: str = "*"
    frontend_dir: str = str(REPO_DIR / "frontend")

    # Login throttling (Round 1 had none): this many failures per
    # client+account inside the window locks further attempts until it passes.
    login_max_failures: int = 8
    login_window_seconds: int = 300

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in ("development", "dev", "local", "test")

    @property
    def should_seed_demo(self) -> bool:
        return self.is_development if self.seed_demo is None else self.seed_demo

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def _local_dev_secret() -> str:
    """A random signing key kept in backend/data/.jwt-secret. With no secret
    configured, a development server then signs tokens with an unguessable
    key, not the public placeholder "change-me" that anyone could forge admin
    tokens with."""
    import secrets

    path = DATA_DIR / ".jwt-secret"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    except OSError:
        pass
    secret = secrets.token_hex(32)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secret, encoding="utf-8")
    except OSError:  # read-only filesystem: still random, just not persistent
        logger.warning("Could not save %s - logins will reset when the server restarts.", path)
    return secret


if settings.is_development and settings.jwt_secret in _PLACEHOLDER_SECRETS:
    settings.jwt_secret = _local_dev_secret()


def validate_settings() -> None:
    """Refuse to run a real event on placeholder secrets.

    Round 1 only checked this outside development, and development was the
    default, so the check never fired. Here development warns loudly and any
    other environment refuses to start.
    """
    weak_secret = settings.jwt_secret in _PLACEHOLDER_SECRETS
    weak_admin = settings.admin_password == "admin123"
    if settings.is_development:
        # (A placeholder JWT_SECRET was already swapped for a random local one above.)
        if weak_admin:
            logger.warning("ADMIN_PASSWORD is the default 'admin123' - fine on your own machine; change it before sharing the server.")
        return
    if weak_secret:
        raise RuntimeError(
            "JWT_SECRET must be a long random value when ENVIRONMENT is not development. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if weak_admin:
        raise RuntimeError("ADMIN_PASSWORD must be changed from the default when ENVIRONMENT is not development.")
