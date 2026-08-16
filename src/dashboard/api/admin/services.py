"""Admin: manage the services catalogue and their icons/descriptions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import Session, select

from ... import models, schemas
from ...auth.deps import AdminUserDep, SessionDep

router = APIRouter(prefix="/api/admin/services", tags=["admin:services"])


def _clean_category(value: str | None) -> str | None:
    clean = (value or "").strip() or None
    return clean


def _get_service_or_404(session: Session, service_id: int) -> models.Service:
    service = session.get(models.Service, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found.")
    return service


@router.get("", response_model=list[schemas.ServiceRead])
def list_services(admin: AdminUserDep, session: SessionDep) -> list[models.Service]:
    return list(session.exec(select(models.Service).order_by(models.Service.name)).all())


@router.post("", response_model=schemas.ServiceRead, status_code=status.HTTP_201_CREATED)
def create_service(admin: AdminUserDep, payload: schemas.ServiceCreate, session: SessionDep) -> models.Service:
    if session.exec(select(models.Service).where(models.Service.name == payload.name)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A service with this name already exists.")
    service = models.Service(
        name=payload.name,
        url=str(payload.url),
        description=payload.description,
        icon=payload.icon,
        category=_clean_category(payload.category),
    )
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


@router.patch("/{service_id}", response_model=schemas.ServiceRead)
def update_service(
    admin: AdminUserDep, service_id: int, payload: schemas.ServiceUpdate, session: SessionDep
) -> models.Service:
    service = _get_service_or_404(session, service_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] and data["name"] != service.name:
        clash = session.exec(
            select(models.Service).where(models.Service.name == data["name"], models.Service.id != service_id)
        ).first()
        if clash is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A service with this name already exists.")
        service.name = data["name"]
    if data.get("url") is not None:
        service.url = str(data["url"])
    if "description" in data:
        service.description = data["description"]
    if "icon" in data:
        service.icon = data["icon"] or None
    if "category" in data:
        service.category = _clean_category(data["category"])
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(admin: AdminUserDep, service_id: int, session: SessionDep) -> Response:
    service = _get_service_or_404(session, service_id)
    for user in list(service.users):
        user.services.remove(service)
    session.delete(service)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
