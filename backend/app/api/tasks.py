from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_current_user
from ..models import TaskStatus
from ..schemas import (
    TaskControlRequest,
    TaskControlResponse,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskEventResponse,
    TaskListResponse,
    TaskMessageAckResponse,
    TaskMessageRequest,
    TaskResponse,
)
from ..services.task_service import task_service


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_user)],
)
async def create_task(payload: TaskCreateRequest) -> TaskResponse:
    task = await task_service.create_task(
        prompt=payload.prompt,
        priority=payload.priority,
        workdir=payload.workdir,
    )
    return TaskResponse.from_model(task)


@router.get("", response_model=TaskListResponse, dependencies=[Depends(get_current_user)])
async def list_tasks(
    status_filter: Optional[TaskStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskListResponse:
    tasks, total = await task_service.list_tasks(status=status_filter, limit=limit, offset=offset)
    return TaskListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[TaskResponse.from_model(item) for item in tasks],
    )


@router.get("/{task_id}", response_model=TaskDetailResponse, dependencies=[Depends(get_current_user)])
async def get_task(task_id: str) -> TaskDetailResponse:
    task = await task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskDetailResponse(
        task=TaskResponse.from_model(task),
        events=[TaskEventResponse.from_model(event) for event in task.events],
    )


@router.post(
    "/{task_id}/control",
    response_model=TaskControlResponse,
    dependencies=[Depends(get_current_user)],
)
async def control_task(task_id: str, payload: TaskControlRequest) -> TaskControlResponse:
    try:
        result = await task_service.control_task(task_id=task_id, action=payload.action.value)
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


@router.post(
    "/{task_id}/message",
    response_model=TaskMessageAckResponse,
    dependencies=[Depends(get_current_user)],
)
async def append_message(task_id: str, payload: TaskMessageRequest) -> TaskMessageAckResponse:
    try:
        _, item = await task_service.append_message(task_id=task_id, message=payload.message)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from None
    return TaskMessageAckResponse(
        task_id=task_id,
        message_id=item.id,
        accepted=True,
        created_at=item.created_at,
    )
