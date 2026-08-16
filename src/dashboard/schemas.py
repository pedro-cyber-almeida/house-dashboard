"""Pydantic schemas: input validation and output shaping."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, StringConstraints

Theme = Literal["dark", "light", "system"]
Role = Literal["admin", "user"]

Username = Annotated[
    str,
    StringConstraints(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]
Secret = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class Msg(BaseModel):
    message: str


# --- Authentication -------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


# --- Users ----------------------------------------------------------------
class UserRead(BaseModel):
    id: int
    username: str
    display_name: str
    avatar: str | None = None
    theme: str
    role: str
    active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminUserRead(UserRead):
    service_ids: list[int] = []


class UserCreate(BaseModel):
    username: Username
    password: Secret
    display_name: str = Field(default="", max_length=120)
    theme: Theme = "system"
    role: Role = "user"
    active: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    avatar: str | None = None
    theme: Theme | None = None
    active: bool | None = None


class UserRole(BaseModel):
    role: Role


class ServiceAssignment(BaseModel):
    service_ids: list[int]


# --- Current user (settings, non-admin view) ------------------------------
class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    avatar: str | None = None
    theme: Theme | None = None


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: Secret


# --- Services -------------------------------------------------------------
class ServiceRead(BaseModel):
    id: int
    name: str
    url: str
    description: str | None = None
    icon: str | None = None
    # Free-form grouping label; null renders as "No category" on the front-end.
    category: str | None = None


class ServiceStatusRead(ServiceRead):
    # "online" | "offline" | "degraded" | "unknown", from the server-side probe.
    online: str = "unknown"
    # When the server last actually verified this (cached within a TTL window).
    checked_at: datetime | None = None
    # The requesting user's saved tile position; null when no order is set
    # (or for roles without a personal order, e.g. admin).
    position: int | None = None


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    description: str | None = Field(default=None, max_length=280)
    icon: str | None = Field(default=None, description="Inline SVG")
    category: str | None = Field(default=None, max_length=64)


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=280)
    icon: str | None = None
    # Absent -> unchanged; null/empty -> cleared.
    category: str | None = Field(default=None, max_length=64)


class ServiceOrderIn(BaseModel):
    # Full ordered list of the user's assigned service ids (position = index).
    # Must contain exactly the assigned set, no more and no less.
    service_ids: list[int]
