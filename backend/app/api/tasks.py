from __future__ import annotations

import asyncio
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_current_user
from ..models import TaskStatus
from ..schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    ExecutorCapabilityResponse,
    TaskControlRequest,
    TaskControlResponse,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskEventResponse,
    UiEventAckResponse,
    UiEventRequest,
    TaskListResponse,
    TaskMessageAckResponse,
    TaskMessageRequest,
    TaskResponse,
)
from ..services.task_service import task_service


router = APIRouter(prefix="/tasks", tags=["tasks"])
UI_EVENT_NAME_PATTERN = re.compile(r"^[a-z0-9._-]{1,80}$")


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreateRequest,
    current_user: str = Depends(get_current_user),
) -> TaskResponse:
    try:
        task = await task_service.create_task(
            prompt=payload.prompt,
            priority=payload.priority,
            workdir=payload.workdir,
            timeout_seconds=payload.timeout_seconds,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
            enable_parallel_agents=payload.enable_parallel_agents,
            actor=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TaskResponse.from_model(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status_filter: Optional[TaskStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(get_current_user),
) -> TaskListResponse:
    tasks, total = await task_service.list_tasks(status=status_filter, limit=limit, offset=offset)
    return TaskListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[TaskResponse.from_model(item) for item in tasks],
    )


@router.post("/telemetry/event", response_model=UiEventAckResponse)
async def track_ui_event(
    payload: UiEventRequest,
    current_user: str = Depends(get_current_user),
) -> UiEventAckResponse:
    event_name = payload.event_name.strip().lower()
    if not UI_EVENT_NAME_PATTERN.fullmatch(event_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="event_name contains invalid characters",
        )
    action = f"ui.event.{event_name}"
    await asyncio.to_thread(
        task_service.append_audit,
        actor=current_user,
        action=action,
        task_id=payload.task_id,
        detail=payload.detail or {},
    )
    return UiEventAckResponse(accepted=True, action=action)


@router.get("/executor/options", response_model=ExecutorCapabilityResponse)
async def get_executor_options(_: str = Depends(get_current_user)) -> ExecutorCapabilityResponse:
    options = await task_service.get_executor_capabilities()
    return ExecutorCapabilityResponse(**options)


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: str,
    include_events: bool = Query(default=True),
    event_limit: int = Query(default=200, ge=1, le=500),
    _: str = Depends(get_current_user),
) -> TaskDetailResponse:
    task = await task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    events = task.events if include_events else []
    if include_events and event_limit > 0:
        events = events[-event_limit:]
    return TaskDetailResponse(
        task=TaskResponse.from_model(task),
        events=[TaskEventResponse.from_model(event) for event in events],
    )


@router.post("/{task_id}/control", response_model=TaskControlResponse)
async def control_task(
    task_id: str,
    payload: TaskControlRequest,
    current_user: str = Depends(get_current_user),
) -> TaskControlResponse:
    try:
        result = await task_service.control_task(
            task_id=task_id,
            action=payload.action.value,
            actor=current_user,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return TaskControlResponse(
        task_id=result.task.id,
        action=payload.action,
        accepted=result.accepted,
        status=result.task.status,
        message=result.message,
    )


@router.post("/{task_id}/message", response_model=TaskMessageAckResponse)
async def append_message(
    task_id: str,
    payload: TaskMessageRequest,
    current_user: str = Depends(get_current_user),
) -> TaskMessageAckResponse:
    try:
        _, item = await task_service.append_message(
            task_id=task_id,
            message=payload.message,
            actor=current_user,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from None
    return TaskMessageAckResponse(
        task_id=task_id,
        message_id=item.id,
        accepted=True,
        created_at=item.created_at,
    )


@router.get("/audit/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actor: str | None = Query(default=None, min_length=1, max_length=128),
    task_id: str | None = Query(default=None, min_length=1, max_length=64),
    action: str | None = Query(default=None, min_length=1, max_length=128),
    _: str = Depends(get_current_user),
) -> AuditLogListResponse:
    items, total = await task_service.list_audits(
        limit=limit,
        offset=offset,
        actor=actor,
        task_id=task_id,
        action=action,
    )
    return AuditLogListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[AuditLogResponse(**item) for item in items],
    )
