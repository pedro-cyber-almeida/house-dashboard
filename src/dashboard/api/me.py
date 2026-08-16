"""Endpoints for the current user's profile and (non-admin) settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .. import models, schemas, security
from ..auth.deps import CurrentUserDep, SessionDep

router = APIRouter(prefix="/api/me", tags=["me"])

VALID_THEMES = {"dark", "light", "system"}


@router.get("", response_model=schemas.UserRead)
def read_me(user: CurrentUserDep) -> models.User:
    return user


@router.patch("", response_model=schemas.UserRead)
def update_me(user: CurrentUserDep, payload: schemas.MeUpdate, session: SessionDep) -> models.User:
    data = payload.model_dump(exclude_unset=True)
    if "display_name" in data:
        user.display_name = (data["display_name"] or "").strip()
    if data.get("theme") in VALID_THEMES:
        user.theme = data["theme"]
    if "avatar" in data:
        user.avatar = data["avatar"] or None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/password", response_model=schemas.Msg)
def change_password(user: CurrentUserDep, payload: schemas.ChangePassword, session: SessionDep) -> schemas.Msg:
    if not security.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The current password is incorrect.")
    user.password_hash = security.hash_password(payload.new_password)
    session.add(user)
    session.commit()
    return schemas.Msg(message="Password changed.")
