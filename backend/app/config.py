from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(BACKEND_ROOT / ".env")


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


def _as_csv_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _require_non_empty_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    raise RuntimeError(
        f"Missing required env var {name}. Configure backend/.env before starting the server."
    )

def _require_strong_jwt_secret() -> str:
    value = _require_non_empty_env("APP_JWT_SECRET")
    weak_values = {
        "dev-secret-change-me",
        "replace-with-a-random-32-plus-char-secret",
        "changeme",
        "password",
    }
    normalized = value.strip().lower()
    if len(value) < 32 or normalized in weak_values:
        raise RuntimeError(
            "APP_JWT_SECRET is too weak. Use a random secret with at least 32 characters."
        )
    return value


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


def _is_subpath(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_workdir_whitelist(raw_items: list[str]) -> list[str]:
    resolved: list[str] = []
    for item in raw_items:
        candidate = Path(item).expanduser()
        if not candidate.is_absolute():
            candidate = (PROJECT_ROOT / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_dir():
            continue
        normalized = str(candidate)
        if normalized not in resolved:
            resolved.append(normalized)
    if not resolved:
        resolved.append(str(PROJECT_ROOT.resolve()))
    return resolved


def _resolve_codex_cli_path(value: str) -> str:
    candidate = (value or "").strip() or "codex"
    expanded = Path(candidate).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    if "/" in candidate and expanded.exists():
        return str(expanded.resolve())

    found = shutil.which(candidate)
    if found:
        return found

    fallback_candidates = [
        Path("/Applications/Codex.app/Contents/Resources/codex"),
        Path.home() / "Applications/Codex.app/Contents/Resources/codex",
    ]
    for fallback in fallback_candidates:
        if fallback.exists():
            return str(fallback)
    return candidate


def _normalize_task_executor(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("_", "-")
    if normalized in {"codex", "codex-cli"}:
        return normalized
    if normalized == "simulator":
        return "simulator"
    return "simulator"


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
    worker_concurrency: int
    redis_url: str
    redis_queue_prefix: str
    task_executor: str
    codex_min_timeout_seconds: int
    codex_hard_timeout_seconds: int
    codex_cli_path: str
    codex_model: str | None
    codex_reasoning_effort: str | None
    codex_full_auto: bool
    auto_rerun_on_message: bool
    sse_replay_limit: int
    workdir_whitelist: list[str]
    require_loopback_direct_login: bool
    trust_proxy_headers: bool
    trusted_proxy_hosts: list[str]
    mobile_login_request_ttl_seconds: int
    cors_allow_private_network: bool


def load_settings() -> Settings:
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    worker_concurrency = _as_int(
        os.getenv("APP_WORKER_CONCURRENCY", "2"),
        fallback=2,
    )
    worker_concurrency = max(1, min(worker_concurrency, 4))
    sse_replay_limit = _as_int(
        os.getenv("APP_SSE_REPLAY_LIMIT", "500"),
        fallback=500,
    )
    sse_replay_limit = max(10, min(sse_replay_limit, 5000))
    mobile_login_request_ttl_seconds = _as_int(
        os.getenv("APP_MOBILE_LOGIN_REQUEST_TTL_SECONDS", "180"),
        fallback=180,
    )
    mobile_login_request_ttl_seconds = max(30, min(mobile_login_request_ttl_seconds, 900))
    task_executor = _normalize_task_executor(os.getenv("APP_TASK_EXECUTOR", "simulator"))
    raw_whitelist = _as_csv_list(
        os.getenv("APP_WORKDIR_WHITELIST", str(PROJECT_ROOT.resolve()))
    )
    workdir_whitelist = _resolve_workdir_whitelist(raw_whitelist)
    trusted_proxy_hosts = _as_csv_list(
        os.getenv("APP_TRUSTED_PROXY_HOSTS", "127.0.0.1,::1,localhost")
    )
    if not trusted_proxy_hosts:
        trusted_proxy_hosts = ["127.0.0.1", "::1", "localhost"]
    return Settings(
        username=_require_non_empty_env("APP_USERNAME"),
        password=_require_non_empty_env("APP_PASSWORD"),
        jwt_secret=_require_strong_jwt_secret(),
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
        worker_concurrency=worker_concurrency,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_queue_prefix=os.getenv("REDIS_QUEUE_PREFIX", "pocket_codex:tasks"),
        task_executor=task_executor,
        codex_min_timeout_seconds=_as_int(
            os.getenv("APP_CODEX_MIN_TIMEOUT_SECONDS", "180"),
            fallback=180,
        ),
        codex_hard_timeout_seconds=_as_int(
            os.getenv("APP_CODEX_HARD_TIMEOUT_SECONDS", "1800"),
            fallback=1800,
        ),
        codex_cli_path=_resolve_codex_cli_path(
            os.getenv("CODEX_CLI_PATH", "codex-cli" if task_executor == "codex-cli" else "codex")
        ),
        codex_model=os.getenv("CODEX_MODEL", "").strip() or None,
        codex_reasoning_effort=os.getenv("CODEX_REASONING_EFFORT", "").strip().lower() or None,
        codex_full_auto=_as_bool(os.getenv("CODEX_FULL_AUTO", "true"), True),
        auto_rerun_on_message=_as_bool(os.getenv("APP_AUTO_RERUN_ON_MESSAGE", "true"), True),
        sse_replay_limit=sse_replay_limit,
        workdir_whitelist=workdir_whitelist,
        require_loopback_direct_login=_as_bool(
            os.getenv("APP_REQUIRE_LOOPBACK_DIRECT_LOGIN", "true"),
            True,
        ),
        trust_proxy_headers=_as_bool(
            os.getenv("APP_TRUST_PROXY_HEADERS", "true"),
            True,
        ),
        trusted_proxy_hosts=trusted_proxy_hosts,
        mobile_login_request_ttl_seconds=mobile_login_request_ttl_seconds,
        cors_allow_private_network=_as_bool(
            os.getenv("APP_CORS_ALLOW_PRIVATE_NETWORK", "true"),
            True,
        ),
    )


settings = load_settings()
