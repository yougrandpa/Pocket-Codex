from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..services.task_service import task_service


router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream_events(request: Request, task_id: str | None = Query(default=None)) -> StreamingResponse:
    queue = await task_service.subscribe(task_id=task_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    data = json.dumps(event, separators=(",", ":"))
                    yield f"event: task_event\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await task_service.unsubscribe(queue=queue, task_id=task_id)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
