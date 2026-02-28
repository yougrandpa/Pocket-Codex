from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import Task, TaskEvent, TaskMessage, TaskStatus


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    priority: int = 0
    workdir: Optional[str] = None


class TaskControlAction(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RETRY = "retry"


class TaskControlRequest(BaseModel):
    action: TaskControlAction


class TaskMessageRequest(BaseModel):
    message: str = Field(min_length=1)


class TaskMessageResponse(BaseModel):
    id: str
    message: str
    created_at: str

    @classmethod
    def from_model(cls, message: TaskMessage) -> "TaskMessageResponse":
        return cls(id=message.id, message=message.message, created_at=message.created_at)


class TaskEventResponse(BaseModel):
    seq: int
    task_id: str
    event_type: str
    status: Optional[TaskStatus]
    timestamp: str
    payload: dict[str, Any]

    @classmethod
    def from_model(cls, event: TaskEvent) -> "TaskEventResponse":
        return cls(
            seq=event.seq,
            task_id=event.task_id,
            event_type=event.event_type,
            status=event.status,
            timestamp=event.timestamp,
            payload=event.payload,
        )


class TaskResponse(BaseModel):
    id: str
    prompt: str
    priority: int
    workdir: Optional[str]
    status: TaskStatus
    summary: Optional[str]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    last_heartbeat_at: Optional[str]
    retry_count: int
    messages: list[TaskMessageResponse] = Field(default_factory=list)
    events: list[TaskEventResponse] = Field(default_factory=list)

    @classmethod
    def from_model(cls, task: Task, include_events: bool = True) -> "TaskResponse":
        events = [TaskEventResponse.from_model(item) for item in task.events] if include_events else []
        return cls(
            id=task.id,
            prompt=task.prompt,
            priority=task.priority,
            workdir=task.workdir,
            status=task.status,
            summary=task.summary,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            last_heartbeat_at=task.last_heartbeat_at,
            retry_count=task.retry_count,
            messages=[TaskMessageResponse.from_model(item) for item in task.messages],
            events=events,
        )


class TaskListResponse(BaseModel):
    total: int
    items: list[TaskResponse]
