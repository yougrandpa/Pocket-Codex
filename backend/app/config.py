from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _as_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: str, fallback: bool) -> bool:
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return fallback


def _normalize_database_url(value: str) -> str:
    if not value.startswith("sqlite:///"):
        return value

    path_part = value.removeprefix("sqlite:///")
    if path_part in {"", ":memory:"}:
        return value
    if path_part.startswith("/"):
        return value

    normalized = (PROJECT_ROOT / path_part).resolve()
    return f"sqlite:///{normalized}"


def _default_database_url() -> str:
    return f"sqlite:///{(BACKEND_ROOT / 'pocket_codex.db').resolve()}"


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
    retry_backoff_base_seconds: int
    execution_backend: str
    redis_url: str
    redis_queue_prefix: str
    task_executor: str
    codex_cli_path: str
    codex_model: str | None
    codex_full_auto: bool
    auto_rerun_on_message: bool


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
        database_url=_normalize_database_url(
            os.getenv("DATABASE_URL", _default_database_url())
        ),
        max_auto_retries=_as_int(os.getenv("APP_MAX_AUTO_RETRIES", "1"), fallback=1),
        default_task_timeout_seconds=_as_int(
            os.getenv("APP_DEFAULT_TASK_TIMEOUT_SECONDS", "20"),
            fallback=20,
        ),
        retry_backoff_base_seconds=_as_int(
            os.getenv("APP_RETRY_BACKOFF_BASE_SECONDS", "1"),
            fallback=1,
        ),
        execution_backend=os.getenv("APP_EXECUTION_BACKEND", "local").strip().lower() or "local",
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_queue_prefix=os.getenv("REDIS_QUEUE_PREFIX", "pocket_codex:tasks"),
        task_executor=os.getenv("APP_TASK_EXECUTOR", "simulator").strip().lower() or "simulator",
        codex_cli_path=os.getenv("CODEX_CLI_PATH", "codex"),
        codex_model=os.getenv("CODEX_MODEL", "").strip() or None,
        codex_full_auto=_as_bool(os.getenv("CODEX_FULL_AUTO", "true"), True),
        auto_rerun_on_message=_as_bool(os.getenv("APP_AUTO_RERUN_ON_MESSAGE", "true"), True),
    )


settings = load_settings()
