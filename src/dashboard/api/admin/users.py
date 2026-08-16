"""Admin: create/edit users, assign roles, and gate per-user services."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import Session, select

from ... import models, schemas, security
from ...auth.deps import AdminUserDep, SessionDep

router = APIRouter(prefix="/api/admin/users", tags=["admin:users"])

VALID_THEMES = {"dark", "light", "system"}


def _get_user_or_404(session: Session, user_id: int) -> models.User:
    user = session.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _to_admin_dict(user: models.User) -> dict:
    data = schemas.UserRead.model_validate(user, from_attributes=True).model_dump()
    data["service_ids"] = [svc.id for svc in user.services if svc.id is not None]
    return data


@router.get("", response_model=list[schemas.AdminUserRead])
def list_users(admin: AdminUserDep, session: SessionDep) -> list[dict]:
    users = session.exec(select(models.User).order_by(models.User.username)).all()
    return [_to_admin_dict(user) for user in users]


@router.post("", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def create_user(admin: AdminUserDep, payload: schemas.UserCreate, session: SessionDep) -> models.User:
    taken = session.exec(select(models.User).where(models.User.username == payload.username)).first()
    if taken is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This username is already taken.")
    user = models.User(
        username=payload.username,
        password_hash=security.hash_password(payload.password),
        display_name=payload.display_name,
        theme=payload.theme,
        role=payload.role,
        active=payload.active,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.patch("/{user_id}", response_model=schemas.UserRead)
def update_user(admin: AdminUserDep, user_id: int, payload: schemas.UserUpdate, session: SessionDep) -> models.User:
    user = _get_user_or_404(session, user_id)
    data = payload.model_dump(exclude_unset=True)
    if "display_name" in data:
        user.display_name = (data["display_name"] or "").strip()
    if data.get("theme") in VALID_THEMES:
        user.theme = data["theme"]
    if "avatar" in data:
        user.avatar = data["avatar"] or None
    if "active" in data:
        if not data["active"] and user.id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot deactivate your own account.",
            )
        user.active = bool(data["active"])
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/{user_id}/role", response_model=schemas.UserRead)
def set_role(admin: AdminUserDep, user_id: int, payload: schemas.UserRole, session: SessionDep) -> models.User:
    user = _get_user_or_404(session, user_id)
    if user.id == admin.id and payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot remove your own administrator role.",
        )
    user.role = payload.role
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.put("/{user_id}/services", response_model=schemas.UserRead)
def assign_services(
    admin: AdminUserDep, user_id: int, payload: schemas.ServiceAssignment, session: SessionDep
) -> models.User:
    user = _get_user_or_404(session, user_id)
    existing = list(session.exec(select(models.Service)).all())
    valid_ids = {svc.id for svc in existing}
    wanted = [sid for sid in sorted(set(payload.service_ids)) if sid in valid_ids]
    chosen = list(session.exec(select(models.Service).where(models.Service.id.in_(wanted))).all()) if wanted else []
    user.services = chosen
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(admin: AdminUserDep, user_id: int, session: SessionDep) -> Response:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You cannot delete your own account.")
    user = _get_user_or_404(session, user_id)
    session.delete(user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
