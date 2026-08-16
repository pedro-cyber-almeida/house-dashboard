"""SQLModel ORM definitions.

The many-to-many link between users and services lives in a dedicated
``user_services`` table. Because SQLModel's ``link_model`` must be a concrete
class, ``UserServices`` is declared before the two parents (it only refers to
them through string foreign keys, so order is safe).

NOTE: this module must not use ``from __future__ import annotations`` —
SQLModel's metaclass needs real (evaluated) typing objects to resolve
relationship targets, and stringified annotations break it.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlalchemy.orm import Mapped
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


TIMESTAMP = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
UPDATED_AT = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class UserServices(SQLModel, table=True):
    __tablename__ = "user_services"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    service_id: int = Field(foreign_key="services.id", primary_key=True)
    # Per-user tile position (index into the user's ordered service list).
    # NULL means "no explicit order" — the server then falls back to name.
    position: int | None = Field(default=None)


class Service(SQLModel, table=True):
    __tablename__ = "services"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=120)
    url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=280)
    icon: str | None = Field(default=None)  # inline SVG or data-URI logo
    # Free-form grouping label (e.g. "Media"); None renders as "No category".
    # Explicit index name so upgraded DBs (database.py) and fresh DBs match.
    category: str | None = Field(default=None, max_length=64, index={"name": "ix_services_category"})
    users: Mapped[list["User"]] = Relationship(back_populates="services", link_model=UserServices)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=64)
    password_hash: str
    display_name: str = Field(default="", max_length=120)
    avatar: str | None = Field(default=None)  # stored as a data URI (base64)
    theme: str = Field(default="system")
    role: str = Field(default="user")
    active: bool = Field(default=True)
    created_at: datetime | None = Field(default=None, sa_column=TIMESTAMP)
    updated_at: datetime | None = Field(default=None, sa_column=UPDATED_AT)
    services: Mapped[list[Service]] = Relationship(back_populates="users", link_model=UserServices)
