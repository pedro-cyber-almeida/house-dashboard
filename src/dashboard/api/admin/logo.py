"""Admin: service logos — manual upload (PNG / JPEG / SVG) and automatic
favicon fetching from the service itself.

Logos are persisted as base64 data URIs in the existing ``Service.icon``
column — no new tables or columns. The front-end always renders them through
``<img src="data:...">`` (never inline injection), so scripts embedded in SVG
cannot execute; the sanitization below is a second defensive layer.
"""

from __future__ import annotations

import base64
import re
from typing import Annotated
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlmodel import Session

from ... import models, schemas
from ...auth.deps import AdminUserDep, SessionDep

MAX_LOGO_BYTES = 512 * 1024  # 512 KB

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_SVG_TAG = re.compile(rb"<svg[\s>]", re.IGNORECASE)
_SCRIPT_TAG = re.compile(r"<script\b.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_ON_ATTR = re.compile(r"""\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]*)""", re.IGNORECASE)
_ICO_LINK_TAG = re.compile(
    rb"""<link\b[^>]*\brel=["\'][^"\']*(?:icon|apple-touch-icon|apple-touch-startup-image)[^"\']*["\'][^>]*>""",
    re.IGNORECASE,
)
_HREF_ATTR = re.compile(rb"""href=["\']([^"\']+)["\']""", re.IGNORECASE)

router = APIRouter(prefix="/api/services", tags=["admin:services"])


def _detect_mime(data: bytes) -> str | None:
    """Real file type by magic bytes; the reported Content-Type is never trusted."""
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<") and _SVG_TAG.search(head[:4096]):
        return "image/svg+xml"
    return None


def _sanitize_svg(data: bytes) -> bytes:
    """Drop <script> and on* handlers (defence in depth; display is <img>)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Invalid SVG: expected UTF-8 text.",
        ) from exc
    text = _SCRIPT_TAG.sub("", text)
    text = _ON_ATTR.sub("", text)
    if re.search(r"<script\b|\son\w+\s*=", text, re.IGNORECASE):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="SVG rejected: contains executable code.",
        )
    return text.encode("utf-8")


def _get_service_or_404(session: Session, service_id: int) -> models.Service:
    service = session.get(models.Service, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found.")
    return service


@router.post("/{service_id}/logo", response_model=schemas.ServiceRead)
async def upload_service_logo(
    admin: AdminUserDep,
    service_id: int,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="Logo (PNG, JPEG or SVG)")],
) -> models.Service:
    service = _get_service_or_404(session, service_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Logo too large ({len(data) // 1024} KB). The limit is 512 KB.",
        )
    mime = _detect_mime(data)
    if mime is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported format. Send PNG, JPEG or SVG.",
        )
    if mime == "image/svg+xml":
        data = _sanitize_svg(data)
    payload = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    service.icon = payload
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


# ---------------- automatic favicon fetch -----------------------------------
_icon_client: httpx.AsyncClient | None = None
PAGE_SCAN_LIMIT = 512 * 1024  # only the first 512 KB of the home page is scanned


def _get_icon_client() -> httpx.AsyncClient:
    """Dedicated client for icon fetching: short timeout, follows redirects.
    ``verify=False`` follows the health-probe precedent — self-signed certs on
    home services are common and this is not a trust decision."""
    global _icon_client
    if _icon_client is None or _icon_client.is_closed:
        _icon_client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(8.0, connect=5.0),
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": "house-dashboard/0.1 icon-fetcher"},
        )
    return _icon_client


def _icon_links(home_page: bytes) -> list[str]:
    """Favicon hrefs declared on the home page (any <link rel*=icon …>)."""
    found: list[str] = []
    for tag in _ICO_LINK_TAG.findall(home_page):
        match = _HREF_ATTR.search(tag)
        if match:
            href = match.group(1).decode(errors="ignore").strip()
            if href and not href.lower().startswith(("data:", "javascript:")):
                found.append(href)
    return found


@router.post("/{service_id}/fetch-icon", response_model=schemas.ServiceRead)
async def fetch_service_icon(
    admin: AdminUserDep,
    service_id: int,
    session: SessionDep,
) -> models.Service:
    """Fetch a usable favicon from the service itself and store it as the logo.

    Tries, in order: <link rel="icon"> targets declared on the home page,
    then /favicon.ico. First candidate whose bytes pass the same magic-byte
    validation as uploads (PNG/JPEG/SVG, ≤ 512 KB) wins.
    """
    service = _get_service_or_404(session, service_id)
    root = str(service.url).rstrip("/")
    try:
        parsed = urlparse(root)
    except ValueError:
        parsed = None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Service URL must be http(s).")

    client = _get_icon_client()
    candidates: list[str] = []
    try:
        page = await client.get(root + "/")
        if page.status_code < 400:
            candidates.extend(urljoin(root + "/", href) for href in _icon_links(page.content[:PAGE_SCAN_LIMIT]))
    except httpx.HTTPError:
        pass
    candidates.append(root + "/favicon.ico")

    for candidate in candidates:
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme not in ("http", "https") or not parsed_candidate.hostname:
            continue
        try:
            response = await client.get(candidate)
        except httpx.HTTPError:
            continue
        if response.status_code >= 400:
            continue
        data = response.content
        if not data or len(data) > MAX_LOGO_BYTES:
            continue
        mime = _detect_mime(data)
        if mime is None:
            continue
        if mime == "image/svg+xml":
            try:
                data = _sanitize_svg(data)
            except HTTPException:
                continue
        service.icon = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        session.add(service)
        session.commit()
        session.refresh(service)
        return service

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No usable icon found — the service is offline or has no PNG/JPEG/SVG favicon.",
    )
