from __future__ import annotations

import hmac
import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError

from .config import settings

_refresh_lock = threading.Lock()
_refresh_sessions: OrderedDict[str, tuple[str, int]] = OrderedDict()
_REFRESH_SESSION_MAX = 20_000


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
    return issue_refresh_token(username)


def _cleanup_refresh_sessions(now_epoch: int) -> None:
    stale_ids = [
        session_id for session_id, (_, expires_at_epoch) in _refresh_sessions.items() if expires_at_epoch <= now_epoch
    ]
    for session_id in stale_ids:
        _refresh_sessions.pop(session_id, None)
    while len(_refresh_sessions) > _REFRESH_SESSION_MAX:
        _refresh_sessions.popitem(last=False)


def issue_refresh_token(username: str, session_id: str | None = None) -> str:
    sid = (session_id or secrets.token_urlsafe(18)).strip()
    if not sid:
        sid = secrets.token_urlsafe(18)
    jti = secrets.token_urlsafe(18)
    now_epoch = int(_utc_now().timestamp())
    expires_delta = timedelta(days=settings.refresh_token_expires_days)
    expires_at_epoch = now_epoch + int(expires_delta.total_seconds())
    with _refresh_lock:
        _cleanup_refresh_sessions(now_epoch)
        _refresh_sessions[sid] = (jti, expires_at_epoch)
        _refresh_sessions.move_to_end(sid)
    return _encode_token(
        payload={"sub": username, "type": "refresh", "sid": sid, "jti": jti},
        expires_delta=expires_delta,
    )


def rotate_refresh_token(payload: dict[str, Any]) -> str:
    username = payload.get("sub")
    session_id = payload.get("sid")
    token_id = payload.get("jti")
    if not isinstance(username, str) or not username.strip():
        raise InvalidTokenError("invalid refresh payload")
    if not isinstance(session_id, str) or not session_id.strip():
        raise InvalidTokenError("invalid refresh payload")
    if not isinstance(token_id, str) or not token_id.strip():
        raise InvalidTokenError("invalid refresh payload")
    sid = session_id.strip()
    jti = token_id.strip()
    new_jti = secrets.token_urlsafe(18)
    expires_delta = timedelta(days=settings.refresh_token_expires_days)
    now_epoch = int(_utc_now().timestamp())
    expires_at_epoch = now_epoch + int(expires_delta.total_seconds())
    with _refresh_lock:
        _cleanup_refresh_sessions(now_epoch)
        current = _refresh_sessions.get(sid)
        if current is None:
            raise InvalidTokenError("refresh session not found")
        stored_jti, expires_at_epoch = current
        if expires_at_epoch <= now_epoch:
            _refresh_sessions.pop(sid, None)
            raise InvalidTokenError("refresh session expired")
        if not hmac.compare_digest(stored_jti, jti):
            _refresh_sessions.pop(sid, None)
            raise InvalidTokenError("refresh token replay detected")
        _refresh_sessions[sid] = (new_jti, expires_at_epoch)
        _refresh_sessions.move_to_end(sid)
    return _encode_token(
        payload={"sub": username, "type": "refresh", "sid": sid, "jti": new_jti},
        expires_delta=expires_delta,
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
