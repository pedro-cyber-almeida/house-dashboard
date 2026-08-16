"""Password hashing via passlib + bcrypt. Never implemented by hand."""

from __future__ import annotations

import logging

from passlib.context import CryptContext

# bcrypt 12 rounds is passlib's default and a sensible, well-vetted cost.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

log = logging.getLogger("dashboard.security")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError) as exc:  # malformed stored hash
        log.warning("Falha ao validar hash: %s", exc)
        return False


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)
