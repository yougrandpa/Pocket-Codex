from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import Task, TaskEvent, TaskMessage, TaskRun, TaskStatus


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    priority: int = 0
    workdir: Optional[str] = None
    timeout_seconds: int = Field(default=20, ge=5, le=3600)


class TaskControlAction(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RETRY = "retry"


class TaskControlRequest(BaseModel):
    action: TaskControlAction


class TaskControlResponse(BaseModel):
    task_id: str
    action: TaskControlAction
    accepted: bool
    status: TaskStatus
    message: str


class TaskMessageRequest(BaseModel):
    message: str = Field(min_length=1)


class TaskMessageAckResponse(BaseModel):
    task_id: str
    message_id: str
    accepted: bool
    created_at: str


class TaskMessageResponse(BaseModel):
    id: str
    message: str
    created_at: str

    @classmethod
    def from_model(cls, message: TaskMessage) -> "TaskMessageResponse":
        return cls(id=message.id, message=message.message, created_at=message.created_at)


class TaskEventResponse(BaseModel):
    id: str
    stream_id: int
    seq: int
    task_id: str
    event_type: str
    status: Optional[TaskStatus]
    timestamp: str
    payload: dict[str, Any]

    @classmethod
    def from_model(cls, event: TaskEvent) -> "TaskEventResponse":
        return cls(
            id=event.id,
            stream_id=event.stream_id,
            seq=event.seq,
            task_id=event.task_id,
            event_type=event.event_type,
            status=event.status,
            timestamp=event.timestamp,
            payload=event.payload,
        )


class TaskRunResponse(BaseModel):
    run_id: str
    sequence: int
    reason: str
    status: TaskStatus
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    summary: Optional[str]

    @classmethod
    def from_model(cls, run: TaskRun) -> "TaskRunResponse":
        return cls(
            run_id=run.run_id,
            sequence=run.sequence,
            reason=run.reason,
            status=run.status,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            summary=run.summary,
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
    paused_at: Optional[str]
    retry_count: int
    timeout_seconds: int
    current_run_id: Optional[str]
    run_sequence: int
    runs: list[TaskRunResponse] = Field(default_factory=list)
    messages: list[TaskMessageResponse] = Field(default_factory=list)

    @classmethod
    def from_model(cls, task: Task) -> "TaskResponse":
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
            paused_at=task.paused_at,
            retry_count=task.retry_count,
            timeout_seconds=task.timeout_seconds,
            current_run_id=task.current_run_id,
            run_sequence=task.run_sequence,
            runs=[TaskRunResponse.from_model(item) for item in task.runs],
            messages=[TaskMessageResponse.from_model(item) for item in task.messages],
        )


class TaskDetailResponse(BaseModel):
    task: TaskResponse
    events: list[TaskEventResponse]


class TaskListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TaskResponse]


class AuditLogResponse(BaseModel):
    id: int
    timestamp: str
    actor: str
    action: str
    task_id: Optional[str]
    detail: dict[str, Any]


class AuditLogListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditLogResponse]
