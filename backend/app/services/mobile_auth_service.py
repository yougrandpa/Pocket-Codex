from __future__ import annotations

import asyncio
import hmac
from ipaddress import ip_address
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from ..auth import create_access_token, create_refresh_token
from ..config import settings
from ..models import new_id, utc_now_iso


MobileLoginStatus = Literal["PENDING", "APPROVED", "REJECTED", "CANCELED", "EXPIRED", "COMPLETED"]
MobileLoginRiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
MOBILE_HISTORY_RETENTION_DAYS = 30
MOBILE_HISTORY_MAX_ENTRIES = 2000


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
    request_token: str
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
            "request_token": self.request_token,
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


@dataclass
class MobileRiskSummary:
    risk_level: MobileLoginRiskLevel
    risk_reasons: list[str]
    known_device: bool
    known_ip: bool
    device_approval_count: int
    device_last_approved_at: Optional[str]
    ip_seen_count: int
    ip_last_seen_at: Optional[str]
    ip_risk_level: MobileLoginRiskLevel


@dataclass
class DeviceApprovalHistory:
    approval_count: int = 0
    last_approved_at: Optional[str] = None


@dataclass
class IpApprovalHistory:
    seen_count: int = 0
    last_seen_at: Optional[str] = None


class MobileAuthService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._requests: dict[str, MobileLoginRequestRecord] = {}
        self._device_histories: dict[tuple[str, str], DeviceApprovalHistory] = {}
        self._ip_histories: dict[tuple[str, str], IpApprovalHistory] = {}

    async def create_request(self, *, username: str, device_name: str, request_ip: str) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            now = utc_now_iso()
            request_id = new_id("mlr")
            request_token = new_id("mlt")
            record = MobileLoginRequestRecord(
                request_id=request_id,
                request_token=request_token,
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

    async def list_pending_with_risk(self) -> list[tuple[MobileLoginRequestRecord, MobileRiskSummary]]:
        async with self._lock:
            self._cleanup_locked()
            items = [record for record in self._requests.values() if record.status == "PENDING"]
            items.sort(key=lambda item: item.created_at, reverse=True)
            result: list[tuple[MobileLoginRequestRecord, MobileRiskSummary]] = []
            for item in items:
                snapshot = MobileLoginRequestRecord(**item.__dict__)
                summary = self._build_risk_summary_locked(item)
                result.append((snapshot, summary))
            return result

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
            self._record_approval_history_locked(record)
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

    async def cancel(
        self,
        *,
        request_id: str,
        request_token: str,
        actor: str,
    ) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            self._assert_request_token(record, request_token)
            if record.status != "PENDING":
                raise ValueError(f"request is not pending: {record.status}")
            record.status = "CANCELED"
            record.approved_at = utc_now_iso()
            record.approved_by = actor
            return MobileLoginRequestRecord(**record.__dict__)

    async def get_status(self, *, request_id: str, request_token: str) -> MobileLoginRequestRecord:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            self._assert_request_token(record, request_token)
            return MobileLoginRequestRecord(**record.__dict__)

    async def consume_tokens_if_approved(
        self,
        *,
        request_id: str,
        request_token: str,
    ) -> tuple[MobileLoginRequestRecord, str | None, str | None]:
        async with self._lock:
            self._cleanup_locked()
            record = self._requests.get(request_id)
            if record is None:
                raise KeyError(request_id)
            self._assert_request_token(record, request_token)
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
            if record.status in {"EXPIRED", "REJECTED", "CANCELED"} and _is_expired(record.expires_at):
                keep_alive = False
            if record.status == "COMPLETED" and record.completed_at:
                completed_at = _parse_iso(record.completed_at)
                if completed_at is not None and now - completed_at > timedelta(minutes=10):
                    keep_alive = False
            if not keep_alive:
                stale_ids.append(record.request_id)
        for request_id in stale_ids:
            self._requests.pop(request_id, None)
        self._cleanup_histories_locked(now)

    def _cleanup_histories_locked(self, now: datetime) -> None:
        cutoff = now - timedelta(days=MOBILE_HISTORY_RETENTION_DAYS)

        stale_device_keys = [
            key
            for key, history in self._device_histories.items()
            if self._is_history_stale(history.last_approved_at, cutoff)
        ]
        for key in stale_device_keys:
            self._device_histories.pop(key, None)

        stale_ip_keys = [
            key
            for key, history in self._ip_histories.items()
            if self._is_history_stale(history.last_seen_at, cutoff)
        ]
        for key in stale_ip_keys:
            self._ip_histories.pop(key, None)

        self._trim_history_capacity_locked()

    @staticmethod
    def _is_history_stale(last_seen_at: Optional[str], cutoff: datetime) -> bool:
        if last_seen_at is None:
            return True
        parsed = _parse_iso(last_seen_at)
        if parsed is None:
            return True
        return parsed < cutoff

    def _trim_history_capacity_locked(self) -> None:
        if len(self._device_histories) > MOBILE_HISTORY_MAX_ENTRIES:
            keep = sorted(
                self._device_histories.items(),
                key=lambda item: _parse_iso(item[1].last_approved_at or "") or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )[:MOBILE_HISTORY_MAX_ENTRIES]
            self._device_histories = dict(keep)

        if len(self._ip_histories) > MOBILE_HISTORY_MAX_ENTRIES:
            keep = sorted(
                self._ip_histories.items(),
                key=lambda item: _parse_iso(item[1].last_seen_at or "") or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )[:MOBILE_HISTORY_MAX_ENTRIES]
            self._ip_histories = dict(keep)

    @staticmethod
    def _assert_request_token(record: MobileLoginRequestRecord, request_token: str) -> None:
        if not hmac.compare_digest(record.request_token, request_token):
            raise PermissionError("invalid request token")

    @staticmethod
    def _device_key(record: MobileLoginRequestRecord) -> tuple[str, str]:
        return (record.username.strip().lower(), record.device_name.strip().lower())

    @staticmethod
    def _ip_key(record: MobileLoginRequestRecord) -> tuple[str, str]:
        return (record.username.strip().lower(), MobileAuthService._normalize_ip_value(record.request_ip))

    @staticmethod
    def _normalize_ip_value(ip_value: str) -> str:
        normalized = ip_value.strip().lower()
        if normalized in {"unknown", "untrusted-proxy", ""}:
            return normalized
        try:
            parsed = ip_address(normalized)
        except ValueError:
            return normalized
        if parsed.version == 6 and parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(parsed)

    def _record_approval_history_locked(self, record: MobileLoginRequestRecord) -> None:
        approved_at = record.approved_at or utc_now_iso()
        device_key = self._device_key(record)
        device_history = self._device_histories.setdefault(device_key, DeviceApprovalHistory())
        device_history.approval_count += 1
        device_history.last_approved_at = approved_at

        ip_key = self._ip_key(record)
        ip_history = self._ip_histories.setdefault(ip_key, IpApprovalHistory())
        ip_history.seen_count += 1
        ip_history.last_seen_at = approved_at

    @staticmethod
    def _ip_risk_level(ip_value: str) -> tuple[MobileLoginRiskLevel, str | None]:
        normalized = MobileAuthService._normalize_ip_value(ip_value)
        if normalized in {"untrusted-proxy"}:
            return "HIGH", "UNTRUSTED_PROXY"
        if normalized in {"unknown", ""}:
            return "HIGH", "UNKNOWN_SOURCE_IP"
        try:
            parsed = ip_address(normalized)
        except ValueError:
            return "HIGH", "INVALID_SOURCE_IP"
        if parsed.is_loopback:
            return "LOW", None
        if parsed.is_private:
            return "LOW", None
        if not parsed.is_global:
            return "MEDIUM", "NON_GLOBAL_SOURCE_IP"
        return "HIGH", "PUBLIC_SOURCE_IP"

    def _build_risk_summary_locked(self, record: MobileLoginRequestRecord) -> MobileRiskSummary:
        device_history = self._device_histories.get(self._device_key(record))
        ip_history = self._ip_histories.get(self._ip_key(record))

        known_device = bool(device_history and device_history.approval_count > 0)
        known_ip = bool(ip_history and ip_history.seen_count > 0)
        ip_risk_level, ip_reason = self._ip_risk_level(record.request_ip)

        risk_reasons: list[str] = []
        if not known_device:
            risk_reasons.append("NEW_DEVICE")
        if not known_ip:
            risk_reasons.append("NEW_IP")
        if ip_reason:
            risk_reasons.append(ip_reason)

        if ip_risk_level == "HIGH":
            risk_level: MobileLoginRiskLevel = "HIGH"
        elif not known_device or not known_ip:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return MobileRiskSummary(
            risk_level=risk_level,
            risk_reasons=risk_reasons,
            known_device=known_device,
            known_ip=known_ip,
            device_approval_count=device_history.approval_count if device_history else 0,
            device_last_approved_at=device_history.last_approved_at if device_history else None,
            ip_seen_count=ip_history.seen_count if ip_history else 0,
            ip_last_seen_at=ip_history.last_seen_at if ip_history else None,
            ip_risk_level=ip_risk_level,
        )


mobile_auth_service = MobileAuthService()
