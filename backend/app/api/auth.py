from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from jwt import InvalidTokenError

from ..auth import create_access_token, create_refresh_token, decode_token
from ..config import settings
from ..schemas import LoginRequest, RefreshTokenRequest, TokenResponse
from ..services.task_service import task_service


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    if payload.username != settings.username or payload.password != settings.password:
        task_service.append_audit(
            actor=payload.username,
            action="auth.login.failed",
            task_id=None,
            detail={},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    task_service.append_audit(
        actor=payload.username,
        action="auth.login.succeeded",
        task_id=None,
        detail={},
    )

    return TokenResponse(
        access_token=create_access_token(payload.username),
        refresh_token=create_refresh_token(payload.username),
        expires_in_seconds=settings.access_token_expires_minutes * 60,
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

    task_service.append_audit(
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
