"""Shared dependencies: DB session, current user, admin guard."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from .. import models
from ..database import get_session

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(request: Request, session: SessionDep) -> models.User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Session"},
        )
    user = session.get(models.User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session. Please sign in.",
        )
    if not user.active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled.")
    return user


CurrentUserDep = Annotated[models.User, Depends(get_current_user)]


def get_admin_user(user: CurrentUserDep) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required.")
    return user


AdminUserDep = Annotated[models.User, Depends(get_admin_user)]
__all__ = ["SessionDep", "CurrentUserDep", "AdminUserDep"]  # noqa: F401
