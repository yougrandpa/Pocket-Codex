from __future__ import annotations

import asyncio
from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt import InvalidTokenError

from ..auth import create_access_token, create_refresh_token, decode_token
from ..config import settings
from ..dependencies import get_current_user
from ..schemas import (
    LoginRequest,
    MobileLoginDecisionResponse,
    MobileLoginPendingListResponse,
    MobileLoginPendingResponse,
    MobileLoginStartRequest,
    MobileLoginStartResponse,
    MobileLoginStatusResponse,
    RefreshTokenRequest,
    TokenResponse,
)
from ..services.mobile_auth_service import mobile_auth_service
from ..services.task_service import task_service


router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_ip_candidate(value: str | None) -> str:
    if not value:
        return "unknown"
    candidate = value.strip().lower()
    if not candidate:
        return "unknown"
    if candidate.startswith("[") and "]" in candidate:
        end = candidate.find("]")
        if end > 1:
            candidate = candidate[1:end].strip().lower()
    try:
        parsed = ip_address(candidate)
    except ValueError:
        return candidate
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def _is_loopback_host(value: str | None) -> bool:
    normalized = _normalize_ip_candidate(value)
    if normalized == "localhost":
        return True
    try:
        parsed = ip_address(normalized)
    except ValueError:
        return False
    if parsed.is_loopback:
        return True
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        return parsed.ipv4_mapped.is_loopback
    return False


def _is_trusted_proxy_host(value: str | None) -> bool:
    normalized = _normalize_ip_candidate(value)
    trusted_hosts = {_normalize_ip_candidate(item) for item in settings.trusted_proxy_hosts}
    return normalized in trusted_hosts


def _extract_forwarded_ip_candidates(request: Request) -> list[str]:
    x_forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
    if not x_forwarded_for:
        return []
    candidates: list[str] = []
    for item in x_forwarded_for.split(","):
        normalized = _normalize_ip_candidate(item)
        try:
            ip_address(normalized)
        except ValueError:
            continue
        candidates.append(normalized)
    return candidates


def _request_ip(request: Request) -> str:
    direct_host = request.client.host if request.client is not None and request.client.host else "unknown"
    normalized_direct_host = _normalize_ip_candidate(direct_host)

    if not settings.trust_proxy_headers:
        return normalized_direct_host
    if not _is_trusted_proxy_host(direct_host):
        return normalized_direct_host

    proxy_hints = (
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-forwarded-host"),
        request.headers.get("x-forwarded-proto"),
    )
    if not any(proxy_hints):
        return normalized_direct_host

    forwarded_candidates = _extract_forwarded_ip_candidates(request)

    if _is_loopback_host(direct_host) or normalized_direct_host == "unknown":
        for candidate in reversed(forwarded_candidates):
            return candidate
        return "untrusted-proxy"
    return normalized_direct_host


def _is_loopback_request(request: Request) -> bool:
    host = _normalize_ip_candidate(_request_ip(request))
    if host == "localhost":
        return True
    return _is_loopback_host(host)


def _read_mobile_request_token_or_raise(request: Request) -> str:
    header_value = (request.headers.get("x-mobile-request-token") or "").strip()
    if header_value:
        return header_value
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Missing X-Mobile-Request-Token header",
    )


async def _append_audit_async(
    *,
    actor: str,
    action: str,
    task_id: str | None,
    detail: dict[str, object],
) -> None:
    await asyncio.to_thread(
        task_service.append_audit,
        actor=actor,
        action=action,
        task_id=task_id,
        detail=detail,
    )


async def _verify_credentials(username: str, password: str) -> None:
    if username != settings.username or password != settings.password:
        await _append_audit_async(
            actor=username,
            action="auth.login.failed",
            task_id=None,
            detail={},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request) -> TokenResponse:
    await _verify_credentials(payload.username, payload.password)
    request_ip = _request_ip(request)

    if settings.require_loopback_direct_login and not _is_loopback_request(request):
        await _append_audit_async(
            actor=payload.username,
            action="auth.login.blocked.non_loopback",
            task_id=None,
            detail={"request_ip": request_ip},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct login is only allowed from localhost. Use mobile approval flow.",
        )

    await _append_audit_async(
        actor=payload.username,
        action="auth.login.succeeded",
        task_id=None,
        detail={"request_ip": request_ip},
    )

    return TokenResponse(
        access_token=create_access_token(payload.username),
        refresh_token=create_refresh_token(payload.username),
        expires_in_seconds=settings.access_token_expires_minutes * 60,
    )


@router.post("/mobile/request", response_model=MobileLoginStartResponse)
async def create_mobile_login_request(
    payload: MobileLoginStartRequest,
    request: Request,
) -> MobileLoginStartResponse:
    await _verify_credentials(payload.username, payload.password)
    request_ip = _request_ip(request)
    record = await mobile_auth_service.create_request(
        username=payload.username,
        device_name=payload.device_name.strip() or "unknown-device",
        request_ip=request_ip,
    )
    await _append_audit_async(
        actor=payload.username,
        action="auth.mobile.request.created",
        task_id=None,
        detail={
            "request_id": record.request_id,
            "request_ip": request_ip,
            "device_name": record.device_name,
        },
    )
    return MobileLoginStartResponse(
        request_id=record.request_id,
        request_token=record.request_token,
        status=record.status,
        expires_at=record.expires_at,
        poll_interval_seconds=2,
    )


@router.get("/mobile/pending", response_model=MobileLoginPendingListResponse)
async def list_mobile_login_requests(_: str = Depends(get_current_user)) -> MobileLoginPendingListResponse:
    items = await mobile_auth_service.list_pending_with_risk()
    return MobileLoginPendingListResponse(
        total=len(items),
        items=[
            MobileLoginPendingResponse(
                request_id=item.request_id,
                status=item.status,
                username=item.username,
                device_name=item.device_name,
                request_ip=item.request_ip,
                created_at=item.created_at,
                expires_at=item.expires_at,
                risk_level=risk.risk_level,
                risk_reasons=risk.risk_reasons,
                known_device=risk.known_device,
                known_ip=risk.known_ip,
                device_approval_count=risk.device_approval_count,
                device_last_approved_at=risk.device_last_approved_at,
                ip_seen_count=risk.ip_seen_count,
                ip_last_seen_at=risk.ip_last_seen_at,
                ip_risk_level=risk.ip_risk_level,
            )
            for item, risk in items
        ],
    )


@router.post("/mobile/requests/{request_id}/approve", response_model=MobileLoginDecisionResponse)
async def approve_mobile_login_request(
    request_id: str,
    current_user: str = Depends(get_current_user),
) -> MobileLoginDecisionResponse:
    try:
        updated = await mobile_auth_service.approve(request_id=request_id, actor=current_user)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _append_audit_async(
        actor=current_user,
        action="auth.mobile.request.approved",
        task_id=None,
        detail={"request_id": request_id, "device_name": updated.device_name, "request_ip": updated.request_ip},
    )
    return MobileLoginDecisionResponse(request_id=updated.request_id, status=updated.status)


@router.post("/mobile/requests/{request_id}/reject", response_model=MobileLoginDecisionResponse)
async def reject_mobile_login_request(
    request_id: str,
    current_user: str = Depends(get_current_user),
) -> MobileLoginDecisionResponse:
    try:
        updated = await mobile_auth_service.reject(request_id=request_id, actor=current_user)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _append_audit_async(
        actor=current_user,
        action="auth.mobile.request.rejected",
        task_id=None,
        detail={"request_id": request_id, "device_name": updated.device_name, "request_ip": updated.request_ip},
    )
    return MobileLoginDecisionResponse(request_id=updated.request_id, status=updated.status)


@router.post("/mobile/requests/{request_id}/cancel", response_model=MobileLoginDecisionResponse)
async def cancel_mobile_login_request(request_id: str, request: Request) -> MobileLoginDecisionResponse:
    request_token = _read_mobile_request_token_or_raise(request)
    try:
        updated = await mobile_auth_service.cancel(
            request_id=request_id,
            request_token=request_token,
            actor="requester",
        )
    except (KeyError, PermissionError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _append_audit_async(
        actor=updated.username,
        action="auth.mobile.request.canceled",
        task_id=None,
        detail={"request_id": request_id, "device_name": updated.device_name, "request_ip": updated.request_ip},
    )
    return MobileLoginDecisionResponse(request_id=updated.request_id, status=updated.status)


@router.get("/mobile/requests/{request_id}", response_model=MobileLoginStatusResponse)
async def get_mobile_login_request_status(
    request_id: str,
    request: Request,
) -> MobileLoginStatusResponse:
    request_token = _read_mobile_request_token_or_raise(request)
    try:
        record, access_token, refresh_token = await mobile_auth_service.consume_tokens_if_approved(
            request_id=request_id,
            request_token=request_token,
        )
    except (KeyError, PermissionError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found") from None

    if access_token and refresh_token:
        await _append_audit_async(
            actor=record.username,
            action="auth.mobile.request.completed",
            task_id=None,
            detail={"request_id": request_id, "request_ip": record.request_ip},
        )

    return MobileLoginStatusResponse(
        request_id=record.request_id,
        status=record.status,
        device_name=record.device_name,
        request_ip=record.request_ip,
        created_at=record.created_at,
        expires_at=record.expires_at,
        approved_at=record.approved_at,
        approved_by=record.approved_by,
        completed_at=record.completed_at,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=settings.access_token_expires_minutes * 60 if access_token else None,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshTokenRequest) -> TokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc

    if token_payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    username = token_payload.get("sub")
    if not isinstance(username, str) or username != settings.username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )

    await _append_audit_async(
        actor=username,
        action="auth.refresh",
        task_id=None,
        detail={},
    )

    return TokenResponse(
        access_token=create_access_token(username),
        refresh_token=create_refresh_token(username),
        expires_in_seconds=settings.access_token_expires_minutes * 60,
    )
