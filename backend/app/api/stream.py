from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ..config import settings
from ..dependencies import get_optional_current_user
from ..services.task_service import SubscriptionLimitError, task_service


router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream_events(
    request: Request,
    task_id: Optional[str] = Query(default=None),
    last_event_id: Optional[str] = Query(default=None),
    user: Optional[str] = Depends(get_optional_current_user),
) -> StreamingResponse:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token",
        )

    header_last_event_id = request.headers.get("last-event-id")
    replay_from = header_last_event_id or last_event_id
    try:
        queue, replay_events = await task_service.subscribe(
            task_id=task_id,
            last_event_id=replay_from,
            user=user,
        )
    except SubscriptionLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc

    async def event_generator() -> AsyncGenerator[str, None]:
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        max_lifetime_seconds = max(1, int(settings.sse_connection_max_seconds))
        try:
            for event in replay_events:
                data = json.dumps(event, separators=(",", ":"))
                event_name = event.get("event_type", "task.event")
                event_id = str(event.get("stream_id", 0))
                yield f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                if loop.time() - started_at >= max_lifetime_seconds:
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    data = json.dumps(event, separators=(",", ":"))
                    event_name = event.get("event_type", "task.event")
                    event_id = str(event.get("stream_id", 0))
                    yield f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            await task_service.unsubscribe(queue=queue, task_id=task_id)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
