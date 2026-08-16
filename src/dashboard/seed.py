"""Idempotent startup seed: the first admin account."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from . import models
from .config import get_settings
from .database import engine
from .security import hash_password

log = logging.getLogger("dashboard.seed")


def run_seed() -> None:
    settings = get_settings()
    with Session(engine) as session:
        if settings.admin_username and settings.admin_password:
            admin = session.exec(select(models.User).where(models.User.username == settings.admin_username)).first()
            if admin is None:
                session.add(
                    models.User(
                        username=settings.admin_username,
                        password_hash=hash_password(settings.admin_password),
                        display_name="Administrator",
                        role="admin",
                        active=True,
                    )
                )
                log.info("Created the first administrator %r.", settings.admin_username)
            elif admin.role != "admin":
                admin.role = "admin"
                admin.active = True
                log.info("Promoted %r to administrator.", admin.username)

        total_users = len(session.exec(select(models.User)).all())
        if total_users == 0:
            log.warning(
                "No users in %s. Set DASH_ADMIN_USERNAME and DASH_ADMIN_PASSWORD",
                settings.database_url,
            )
        session.commit()
