from __future__ import annotations

import os
from dataclasses import dataclass


def _as_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    jwt_secret: str
    jwt_algorithm: str
    access_token_expires_minutes: int
    refresh_token_expires_days: int
    cors_origins: list[str]
    database_url: str
    max_auto_retries: int
    default_task_timeout_seconds: int


def load_settings() -> Settings:
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    return Settings(
        username=os.getenv("APP_USERNAME", "admin"),
        password=os.getenv("APP_PASSWORD", "admin123"),
        jwt_secret=os.getenv("APP_JWT_SECRET", "dev-secret-change-me"),
        jwt_algorithm="HS256",
        access_token_expires_minutes=_as_int(
            os.getenv("APP_ACCESS_TOKEN_EXPIRES_MINUTES", "30"),
            fallback=30,
        ),
        refresh_token_expires_days=_as_int(
            os.getenv("APP_REFRESH_TOKEN_EXPIRES_DAYS", "7"),
            fallback=7,
        ),
        cors_origins=allow_origins,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./backend/pocket_codex.db"),
        max_auto_retries=_as_int(os.getenv("APP_MAX_AUTO_RETRIES", "1"), fallback=1),
        default_task_timeout_seconds=_as_int(
            os.getenv("APP_DEFAULT_TASK_TIMEOUT_SECONDS", "20"),
            fallback=20,
        ),
    )


settings = load_settings()
