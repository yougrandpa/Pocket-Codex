from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ..dependencies import get_optional_current_user, validate_access_token
from ..services.task_service import task_service


router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream_events(
    request: Request,
    task_id: Optional[str] = Query(default=None),
    access_token: Optional[str] = Query(default=None),
    user: Optional[str] = Depends(get_optional_current_user),
) -> StreamingResponse:
    if user is None:
        if access_token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing access token",
            )
        user = validate_access_token(access_token)

    queue = await task_service.subscribe(task_id=task_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    data = json.dumps(event, separators=(",", ":"))
                    event_name = event.get("event_type", "task.event")
                    event_id = f"{event.get('task_id', 'task')}:{event.get('seq', 0)}"
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
