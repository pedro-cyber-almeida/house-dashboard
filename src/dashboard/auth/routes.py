"""Login / logout against the signed session cookie."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import select

from .. import models, schemas, security
from .deps import SessionDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.UserRead, status_code=status.HTTP_200_OK)
def login(payload: schemas.LoginIn, request: Request, session: SessionDep) -> models.User:
    user = session.exec(select(models.User).where(models.User.username == payload.username)).first()
    if user is None or not security.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")
    # Repopulate the signed cookie for this login.
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["role"] = user.role
    return user


@router.post("/logout", response_model=schemas.Msg)
def logout(request: Request) -> schemas.Msg:
    request.session.clear()
    return schemas.Msg(message="Signed out.")
