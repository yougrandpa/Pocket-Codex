from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth import router as auth_router
from .api.stream import router as stream_router
from .api.tasks import router as tasks_router
from .config import settings
from .errors import register_error_handlers
from .models import utc_now_iso
from .services.task_service import task_service

CORS_PRIVATE_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost"
    r"|127\.0\.0\.1"
    r"|10(?:\.\d{1,3}){3}"
    r"|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|[a-zA-Z0-9.-]+\.local"
    r")(?::\d+)?$"
)


app = FastAPI(
    title="Pocket Codex Backend",
    version="0.1.0",
    description="FastAPI MVP backend for remote Codex task monitoring and control.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=CORS_PRIVATE_ORIGIN_REGEX if settings.cors_allow_private_network else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(stream_router, prefix="/api/v1")


@app.on_event("startup")
async def _startup() -> None:
    await task_service.start_worker()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await task_service.stop_worker()


@app.get("/healthz")
async def healthz() -> dict[str, str | bool | int | list[str]]:
    return {
        "status": "ok",
        "timestamp": utc_now_iso(),
        "task_executor": settings.task_executor,
        "execution_backend": settings.execution_backend,
        "worker_concurrency": settings.worker_concurrency,
        "sse_replay_limit": settings.sse_replay_limit,
        "workdir_whitelist": settings.workdir_whitelist,
        "codex_min_timeout_seconds": settings.codex_min_timeout_seconds,
        "codex_hard_timeout_seconds": settings.codex_hard_timeout_seconds,
        "codex_cli_path": settings.codex_cli_path,
        "codex_cli_exists": Path(settings.codex_cli_path).exists(),
        "require_loopback_direct_login": settings.require_loopback_direct_login,
        "mobile_login_request_ttl_seconds": settings.mobile_login_request_ttl_seconds,
        "cors_allow_private_network": settings.cors_allow_private_network,
    }
