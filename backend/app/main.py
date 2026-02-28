from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.stream import router as stream_router
from .api.tasks import router as tasks_router
from .models import utc_now_iso


app = FastAPI(
    title="Pocket Codex Backend",
    version="0.1.0",
    description="FastAPI MVP backend for remote Codex task monitoring and control.",
)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router, prefix="/api/v1")
app.include_router(stream_router, prefix="/api/v1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "timestamp": utc_now_iso()}
