"""The dashboard catalogue: which services the current user can see, plus a
real server-side health check for the per-card status LED.

The probe talks to the service from this host (unlike a browser fetch, it is
not limited by CORS). Per service it tries a short list of well-known health
paths in order — a 2xx/3xx on any of them means "online". If the socket
answers but none of the paths does, the service is "degraded" (it accepts
connections but nothing confirms health). Connection refused/timeout means
"offline"; an unresolvable hostname means "unknown". Results are cached per
URL for a few seconds so a page load does not hammer the services.

NOTE: the probe uses its OWN dedicated ``httpx.AsyncClient`` with
``verify=False`` — internal services often ship self-signed certificates and
this is only a liveness check, never a trust decision. That insecure option
must never leak into other code paths that make real requests.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import suppress
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlmodel import Session, select

from .. import database, models, schemas
from ..auth.deps import CurrentUserDep, SessionDep
from ..config import get_settings

router = APIRouter(prefix="/api/services", tags=["services"])

# Ordered liveness hints; the first one to answer 2xx/3xx decides "online".
HEALTH_PATHS = ("/health", "/healthz", "/ping", "/api/health", "/api/ping", "/")
MAX_PROBE_CONCURRENCY = 5
MAX_CACHE_ENTRIES = 4096

_probe_client: httpx.AsyncClient | None = None
_probe_semaphore: asyncio.Semaphore | None = None
# url -> (expires_at monotonic, status, checked_at); checked_at is None for
# unresolvable hosts, and for refused connections it is the moment of the try.
_cache: dict[str, tuple[float, str, datetime | None]] = {}
# url -> the single probe task currently running for that URL (one-flight
# dedup, so parallel callers share one network check instead of queuing).
_inflight: dict[str, asyncio.Task[tuple[str, datetime | None]]] = {}
_cache_guard = asyncio.Lock()


async def close_probe_resources() -> None:
    """Shut the dedicated probe client down (called from the app lifespan)."""
    global _probe_client
    if _probe_client is not None and not _probe_client.is_closed:
        await _probe_client.aclose()
    _probe_client = None


def _get_probe_client() -> httpx.AsyncClient:
    global _probe_client
    if _probe_client is None or _probe_client.is_closed:
        # Dedicated instance for the health probe only — see module note on
        # verify=False. Short timeout, no redirects, modest pool.
        _probe_client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(get_settings().probe_timeout),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=MAX_PROBE_CONCURRENCY * 2, max_keepalive_connections=4),
            headers={"User-Agent": "house-dashboard/0.1 health-check"},
        )
    return _probe_client


def _get_semaphore() -> asyncio.Semaphore:
    global _probe_semaphore
    if _probe_semaphore is None:
        _probe_semaphore = asyncio.Semaphore(MAX_PROBE_CONCURRENCY)
    return _probe_semaphore


async def _name_resolves(host: str, port: int) -> bool:
    """A hostname that cannot be resolved from THIS host is "unknown", not dead."""
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=get_settings().probe_timeout,
        )
        return True
    except (OSError, ValueError, TimeoutError):
        return False


async def _probe(url: str) -> tuple[str, datetime | None]:
    """Returns (status, checked_at). Status: online | offline | degraded | unknown."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ("unknown", None)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ("unknown", None)

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not await _name_resolves(parsed.hostname, port):
        return ("unknown", None)

    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    base = f"{parsed.scheme}://{host}:{port}"

    async with _get_semaphore():
        checked_at = datetime.now(tz=timezone.utc)
        client = _get_probe_client()
        for path in HEALTH_PATHS:
            try:
                response = await client.get(base + path)
            except (httpx.TimeoutException, httpx.TransportError):
                return ("offline", checked_at)
            if 200 <= response.status_code < 400:
                return ("online", checked_at)
        return ("degraded", checked_at)


async def _probed(url: str) -> tuple[str, datetime | None]:
    """Cached, deduplicated probe.

    Returns a fresh result from the cache when available; otherwise (re)uses
    the single in-flight probe for this URL. Crucially, the cache lock is only
    held for the tiny dict mutations — never across the network await — so
    probes from different URLs run in parallel instead of serializing behind
    the lock.
    """
    loop = asyncio.get_running_loop()
    now = loop.time()
    entry = _cache.get(url)
    if entry is not None and entry[0] > now:
        return (entry[1], entry[2])

    task = _inflight.get(url)
    if task is None:
        task = asyncio.create_task(_probe(url))
        _inflight[url] = task

    status: str | None = None
    checked_at: datetime | None = None
    try:
        status, checked_at = await task
    finally:
        # Release the in-flight slot; identity check makes it first-to-wins.
        async with _cache_guard:
            if _inflight.get(url) is task:
                _inflight.pop(url, None)

    if status is not None:
        async with _cache_guard:
            current = _cache.get(url)
            # Don't clobber a fresher entry a sibling caller just wrote.
            if current is None or current[0] <= loop.time():
                _cache[url] = (loop.time() + get_settings().probe_cache_ttl, status, checked_at)
                if len(_cache) > MAX_CACHE_ENTRIES:
                    _cache.clear()
    return (status, checked_at)


def _spawn_revalidate(url: str) -> None:
    """Refresh a stale entry in the background; fire-and-forget, self-healing."""
    loop = asyncio.get_running_loop()

    async def _work() -> None:
        # A background probe must never take the app down.
        with suppress(Exception):
            await _probed(url)

    loop.create_task(_work())


async def warm_cache() -> None:
    """Fire one probe per catalogue service so the first page load is instant.

    Called once at startup, in the background. Any /assigned request that lands
    while these are running simply joins the in-flight tasks (see _probed),
    so it never double-probes a URL.
    """
    # Background work: any failure here must not take the app down with it.
    with suppress(Exception):
        with Session(database.engine) as session:
            urls = [service.url for service in session.exec(select(models.Service)).all()]
        if urls:
            await asyncio.gather(*(_probed(u) for u in urls))


def _order_map(user: models.User, session: Session) -> dict[int, int | None]:
    links = session.exec(select(models.UserServices).where(models.UserServices.user_id == user.id)).all()
    return {link.service_id: link.position for link in links}


def _assigned(user: models.User, session: Session) -> tuple[list[models.Service], dict[int, int | None]]:
    if user.role == "admin":
        # Admins curate the whole catalogue, so the dashboard shows all of it,
        # by name — they have no personal tile order (decision, Fase 2).
        return list(session.exec(select(models.Service).order_by(models.Service.name)).all()), {}
    positions = _order_map(user, session)
    services = sorted(
        user.services,
        key=lambda s: (positions.get(s.id) is None, positions.get(s.id) or 0, s.name.lower()),
    )
    return services, positions


@router.get("/assigned", response_model=list[schemas.ServiceStatusRead])
async def assigned_services(user: CurrentUserDep, session: SessionDep) -> list[dict]:
    """Last-known state for every assigned service, returned without blocking.

    A service with a cached probe answers instantly (fresh or, if stale, the
    previous value) and is re-verified in the background. Only a URL that has
    never been probed (e.g. the first load right after a restart) performs a
    bounded, parallel check before responding — so the page never waits for the
    sum of every service's timeout, only (at worst) a single one, run in
    parallel with the rest.
    """
    services, positions = _assigned(user, session)
    now = asyncio.get_running_loop().time()

    async def status_of(svc: models.Service) -> tuple[str, datetime | None]:
        entry = _cache.get(svc.url)
        if entry is not None:
            if entry[0] <= now and _inflight.get(svc.url) is None:
                _spawn_revalidate(svc.url)
            return (entry[1], entry[2])
        return await _probed(svc.url)

    # gather = every never-probed service is checked once, in parallel, while
    # the cached ones already returned — the response time is bounded by the
    # worst single out-of-cache probe, never by the sum of all probes.
    statuses = await asyncio.gather(*(status_of(svc) for svc in services))

    out: list[dict] = []
    for svc, (probe, checked_at) in zip(services, statuses, strict=True):
        data = schemas.ServiceRead.model_validate(svc, from_attributes=True).model_dump()
        data["online"] = probe
        data["checked_at"] = checked_at
        data["position"] = positions.get(svc.id)
        out.append(data)
    return out


@router.put("/order", response_model=schemas.Msg)
def save_order(user: CurrentUserDep, payload: schemas.ServiceOrderIn, session: SessionDep) -> dict[str, str]:
    if user.role != "user":
        # Admins curate the catalogue by name; only plain users have an order.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has no personal service order.",
        )
    received = payload.service_ids
    if len(received) != len(set(received)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The list contains duplicate ids.")
    assigned_ids = {service.id for service in user.services}
    if set(received) != assigned_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The list must contain exactly the assigned services (no more, no less).",
        )
    links = {
        link.service_id: link
        for link in session.exec(select(models.UserServices).where(models.UserServices.user_id == user.id)).all()
    }
    # One implicit transaction for the whole rewrite; a mid-way failure rolls
    # back every position instead of leaving a partial/duplicated order.
    for position, service_id in enumerate(received):
        links[service_id].position = position
    session.commit()
    return {"message": "Order saved."}
