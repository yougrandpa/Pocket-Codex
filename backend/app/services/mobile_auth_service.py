from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from ..auth import create_access_token, create_refresh_token
from ..config import settings
from ..models import new_id, utc_now_iso


MobileLoginStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "COMPLETED"]


def _iso_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_expired(expires_at: str) -> bool:
    parsed = _parse_iso(expires_at)
    if parsed is None:
        return True
    return datetime.now(timezone.utc) >= parsed


@dataclass
class MobileLoginRequestRecord:
    request_id: str
    username: str
    device_name: str
    request_ip: str
    status: MobileLoginStatus
    created_at: str
    expires_at: str
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    completed_at: Optional[str] = None

    def to_summary(self) -> dict[str, str | None]:
        return {
            "request_id": self.request_id,
            "username": self.username,
            "device_name": self.device_name,
            "request_ip": self.request_ip,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "completed_at": self.completed_at,
        }


class MobileAuthService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._requests: dict[str, MobileLoginRequestRecord] = {}

    async def create_request(self, *, username: str, device_name: str, request_ip: str) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            now = utc_now_iso()
            request_id = new_id("mlr")
            record = MobileLoginRequestRecord(
                request_id=request_id,
                username=username,
                device_name=device_name,
                request_ip=request_ip,
                status="PENDING",
                created_at=now,
                expires_at=_iso_after(settings.mobile_login_request_ttl_seconds),
            )
            self._requests[request_id] = record
            return MobileLoginRequestRecord(**record.__dict__)

    async def list_pending(self) -> list[MobileLoginRequestRecord]:
        async with self._lock:
            self._cleanup_locked()
            items = [record for record in self._requests.values() if record.status == "PENDING"]
            items.sort(key=lambda item: item.created_at, reverse=True)
            return [MobileLoginRequestRecord(**item.__dict__) for item in items]

    async def approve(self, *, request_id: str, actor: str) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            if record.status != "PENDING":
                raise ValueError(f"request is not pending: {record.status}")
            record.status = "APPROVED"
            record.approved_at = utc_now_iso()
            record.approved_by = actor
            return MobileLoginRequestRecord(**record.__dict__)

    async def reject(self, *, request_id: str, actor: str) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            if record.status != "PENDING":
                raise ValueError(f"request is not pending: {record.status}")
            record.status = "REJECTED"
            record.approved_at = utc_now_iso()
            record.approved_by = actor
            return MobileLoginRequestRecord(**record.__dict__)

    async def get_status(self, *, request_id: str) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            return MobileLoginRequestRecord(**record.__dict__)

    async def consume_tokens_if_approved(
        self,
        *,
        request_id: str,
    ) -> tuple[MobileLoginRequestRecord, str | None, str | None]:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            if record.status != "APPROVED":
                return MobileLoginRequestRecord(**record.__dict__), None, None
            access_token = create_access_token(record.username)
            refresh_token = create_refresh_token(record.username)
            record.status = "COMPLETED"
            record.completed_at = utc_now_iso()
            snapshot = MobileLoginRequestRecord(**record.__dict__)
            return snapshot, access_token, refresh_token

    def _cleanup_locked(self) -> None:
        now = datetime.now(timezone.utc)
        stale_ids: list[str] = []
        for record in self._requests.values():
            if record.status == "PENDING" and _is_expired(record.expires_at):
                record.status = "EXPIRED"
            keep_alive = True
            if record.status in {"EXPIRED", "REJECTED"} and _is_expired(record.expires_at):
                keep_alive = False
            if record.status == "COMPLETED" and record.completed_at:
                completed_at = _parse_iso(record.completed_at)
                if completed_at is not None and now - completed_at > timedelta(minutes=10):
                    keep_alive = False
            if not keep_alive:
                stale_ids.append(record.request_id)
        for request_id in stale_ids:
            self._requests.pop(request_id, None)


mobile_auth_service = MobileAuthService()
