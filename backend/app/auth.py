from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError

from .config import settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _encode_token(payload: dict[str, Any], expires_delta: timedelta) -> str:
    now = _utc_now()
    body = payload.copy()
    body.update(
        {
            "iat": int(now.timestamp()),
            "exp": int((now + expires_delta).timestamp()),
        }
    )
    return jwt.encode(body, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(username: str) -> str:
    return _encode_token(
        payload={"sub": username, "type": "access"},
        expires_delta=timedelta(minutes=settings.access_token_expires_minutes),
    )


def create_refresh_token(username: str) -> str:
    return _encode_token(
        payload={"sub": username, "type": "refresh"},
        expires_delta=timedelta(days=settings.refresh_token_expires_days),
    )


def decode_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if not isinstance(payload, dict):
        raise InvalidTokenError("Invalid token payload")
    return payload
