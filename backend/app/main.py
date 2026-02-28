from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth import router as auth_router
from .api.stream import router as stream_router
from .api.tasks import router as tasks_router
from .config import settings
from .errors import register_error_handlers
from .models import utc_now_iso


app = FastAPI(
    title="Pocket Codex Backend",
    version="0.1.0",
    description="FastAPI MVP backend for remote Codex task monitoring and control.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(stream_router, prefix="/api/v1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "timestamp": utc_now_iso()}
