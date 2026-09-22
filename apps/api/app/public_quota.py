"""Shared fixed-hour public-write quotas, with no retained client addresses."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.public_rejections import record_public_rejection

_local_secret = secrets.token_bytes(32)
_local_lock = threading.Lock()
_local_counts: dict[tuple[str, str, datetime], int] = {}
_ROUTES = {"/api/public-submissions": "submission", "/api/watch-areas": "watch"}


def normalized_address(value: str) -> str:
    if "%" in value:
        raise ValueError("Scoped addresses are not valid forwarded client addresses.")
    address = ipaddress.ip_address(value.strip())
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def trusted_client_address(request: Request) -> str:
    # Uvicorn must run --no-proxy-headers so this is the actual transport peer.
    try:
        peer = normalized_address(request.client.host if request.client else "0.0.0.0")
    except ValueError:
        peer = "0.0.0.0"  # e.g. the in-process TestClient; one conservative bucket
    configured = get_settings().public_write_trusted_proxies
    try:
        networks = [
            ipaddress.ip_network(item.strip()) for item in configured.split(",") if item.strip()
        ]
    except ValueError as exc:
        raise quota_unavailable() from exc

    def trusted(address: str) -> bool:
        return any(ipaddress.ip_address(address) in network for network in networks)

    if not trusted(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if len(forwarded) > 2048:
        return peer
    current = peer
    for raw_address in reversed(forwarded.split(",")):
        if not trusted(current):
            break
        try:
            current = normalized_address(raw_address)
        except ValueError:
            return peer
    return current


def quota_unavailable() -> HTTPException:
    record_public_rejection("quota_unavailable")
    return HTTPException(
        503,
        detail={
            "code": "write_quota_unavailable",
            "message": "Public requests are temporarily unavailable. Please try again later.",
        },
    )


def enforce_public_write_quota(request: Request) -> None:
    settings = get_settings()
    route = _ROUTES[request.url.path.rstrip("/")]
    now = datetime.now(UTC)
    window = now.replace(minute=0, second=0, microsecond=0)
    expires = window + timedelta(hours=2)
    postgres = settings.data_mode == "live" and settings.phase3_store_backend == "postgres"
    if postgres:
        configured_secret = settings.public_write_quota_secret
        if configured_secret is None or len(configured_secret.encode()) < 32:
            raise quota_unavailable()
        secret = configured_secret.encode()
    else:
        secret = _local_secret
    key = hmac.new(
        secret,
        f"{window.isoformat()}|{route}|{trusted_client_address(request)}".encode(),
        hashlib.sha256,
    ).hexdigest()
    limit = settings.public_write_quota_limit
    if postgres:
        from app.db import SessionLocal

        try:
            with SessionLocal.begin() as session:
                session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                session.execute(text("SET LOCAL lock_timeout = '1000ms'"))
                accepted = (
                    session.execute(
                        text("""
                    INSERT INTO public_write_quotas
                      (client_key, route, window_start, attempts, expires_at)
                    VALUES (:key, :route, :window, 1, :expires)
                    ON CONFLICT (client_key, route, window_start) DO UPDATE
                      SET attempts = public_write_quotas.attempts + 1
                      WHERE public_write_quotas.attempts < :limit
                    RETURNING attempts
                """),
                        {
                            "key": key,
                            "route": route,
                            "window": window,
                            "expires": expires,
                            "limit": limit,
                        },
                    ).scalar_one_or_none()
                    is not None
                )
                session.execute(
                    text("""
                    WITH expired AS (
                      SELECT client_key, route, window_start FROM public_write_quotas
                      WHERE expires_at < :now ORDER BY expires_at LIMIT 100
                      FOR UPDATE SKIP LOCKED
                    ) DELETE FROM public_write_quotas q USING expired e
                      WHERE q.client_key=e.client_key AND q.route=e.route
                        AND q.window_start=e.window_start
                """),
                    {"now": now},
                )
        except SQLAlchemyError as exc:
            raise quota_unavailable() from exc
    else:
        with _local_lock:
            for previous in list(_local_counts):
                if previous[2] + timedelta(hours=2) < now:
                    del _local_counts[previous]
            bucket = (key, route, window)
            current = _local_counts.get(bucket, 0)
            accepted = current < limit
            if accepted:
                _local_counts[bucket] = current + 1
    if not accepted:
        record_public_rejection("quota_reached")
        retry = max(1, int((window + timedelta(hours=1) - now).total_seconds()) + 1)
        raise HTTPException(
            429,
            detail={
                "code": "public_write_quota_reached",
                "message": "Hourly request limit reached. Please try again later.",
                "retry_after_seconds": retry,
            },
            headers={"Retry-After": str(retry)},
        )
