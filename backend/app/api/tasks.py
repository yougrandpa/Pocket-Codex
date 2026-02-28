from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..models import TaskStatus
from ..schemas import (
    TaskControlRequest,
    TaskCreateRequest,
    TaskListResponse,
    TaskMessageRequest,
    TaskResponse,
)
from ..services.task_service import task_service


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreateRequest) -> TaskResponse:
    task = await task_service.create_task(
        prompt=payload.prompt,
        priority=payload.priority,
        workdir=payload.workdir,
    )
    return TaskResponse.from_model(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks(status_filter: TaskStatus | None = Query(default=None, alias="status")) -> TaskListResponse:
    tasks = await task_service.list_tasks(status=status_filter)
    return TaskListResponse(
        total=len(tasks),
        items=[TaskResponse.from_model(item, include_events=False) for item in tasks],
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    task = await task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskResponse.from_model(task)


@router.post("/{task_id}/control", response_model=TaskResponse)
async def control_task(task_id: str, payload: TaskControlRequest) -> TaskResponse:
    try:
        task = await task_service.control_task(task_id=task_id, action=payload.action.value)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from None
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TaskResponse.from_model(task)


@router.post("/{task_id}/message", response_model=TaskResponse)
async def append_message(task_id: str, payload: TaskMessageRequest) -> TaskResponse:
    try:
        task = await task_service.append_message(task_id=task_id, message=payload.message)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from None
    return TaskResponse.from_model(task)
