"""Configuration loaded from the environment with sane local defaults."""

from __future__ import annotations

import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
# Overridable via DASH_DATA_DIR so containers can point this at a mounted
# volume (the SQLite database and the generated .secret key live here).
DATA_DIR = Path(os.getenv("DASH_DATA_DIR") or BASE_DIR / "data")

LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
_TRUTHY = {"1", "true", "yes", "on", "y"}
_FALSY = {"0", "false", "no", "off", "n"}


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    norm = value.strip().lower()
    if norm in _TRUTHY:
        return True
    if norm in _FALSY:
        return False
    return None


def _load_secret_key() -> str:
    """Session cookie key. From env if set, else generated and persisted so that
    sessions survive a restart."""
    env = os.getenv("DASH_SECRET_KEY")
    if env:
        return env
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = DATA_DIR / ".secret"
    if secret_file.exists():
        return secret_file.read_text().strip()
    token = secrets.token_urlsafe(48)
    secret_file.write_text(token)
    with suppress(OSError):
        os.chmod(secret_file, 0o600)
    return token


@dataclass(slots=True)
class Settings:
    secret_key: str
    database_url: str
    app_name: str
    cookie_name: str
    cookie_secure: bool
    cookie_max_age: int
    admin_username: str | None
    admin_password: str | None
    host: str
    port: int
    probe_timeout: float
    probe_cache_ttl: float


@lru_cache
def get_settings() -> Settings:
    host = os.getenv("DASH_HOST", "127.0.0.1").strip() or "127.0.0.1"
    db_path = os.getenv("DASH_DB_PATH")
    if not db_path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = str(DATA_DIR / "dashboard.db")
    secure = _optional_bool(os.getenv("DASH_COOKIE_SECURE"))
    if secure is None:
        secure = host not in LOCAL_HOSTS
    app_name = os.getenv("DASH_APP_NAME", "").strip() or "House Dashboard"
    return Settings(
        secret_key=_load_secret_key(),
        database_url=f"sqlite:///{db_path}",
        app_name=app_name,
        cookie_name=os.getenv("DASH_COOKIE_NAME", "dashboard_session"),
        cookie_secure=secure,
        cookie_max_age=int(os.getenv("DASH_COOKIE_MAX_AGE", "43200")),
        admin_username=os.getenv("DASH_ADMIN_USERNAME"),
        admin_password=os.getenv("DASH_ADMIN_PASSWORD"),
        host=host,
        port=int(os.getenv("DASH_PORT", "8000")),
        probe_timeout=float(os.getenv("DASH_PROBE_TIMEOUT", "3.0")),
        probe_cache_ttl=float(os.getenv("DASH_PROBE_CACHE_TTL", "30")),
    )
