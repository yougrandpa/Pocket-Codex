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


class MobileLoginStartRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    device_name: str = Field(default="unknown-device", min_length=1, max_length=120)


class MobileLoginStartResponse(BaseModel):
    request_id: str
    request_token: str
    status: str
    expires_at: str
    poll_interval_seconds: int


class MobileLoginStatusResponse(BaseModel):
    request_id: str
    status: str
    device_name: str
    request_ip: str
    created_at: str
    expires_at: str
    approved_at: Optional[str]
    approved_by: Optional[str]
    completed_at: Optional[str]
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in_seconds: Optional[int] = None


class MobileLoginPendingResponse(BaseModel):
    request_id: str
    status: str
    username: str
    device_name: str
    request_ip: str
    created_at: str
    expires_at: str


class MobileLoginPendingListResponse(BaseModel):
    total: int
    items: list[MobileLoginPendingResponse]


class MobileLoginDecisionResponse(BaseModel):
    request_id: str
    status: str


class TaskCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    priority: int = 0
    workdir: Optional[str] = None
    timeout_seconds: int = Field(default=20, ge=5, le=3600)
    model: Optional[str] = Field(default=None, max_length=80)
    reasoning_effort: Optional[str] = Field(default=None, max_length=16)
    enable_parallel_agents: bool = False


class ExecutorCapabilityResponse(BaseModel):
    source: str
    model_options: list[str]
    reasoning_effort_options: list[str]
    supports_parallel_agents: bool


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


class UiEventRequest(BaseModel):
    event_name: str = Field(min_length=1, max_length=80)
    task_id: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)


class UiEventAckResponse(BaseModel):
    accepted: bool
    action: str


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
    model: Optional[str]
    reasoning_effort: Optional[str]
    enable_parallel_agents: bool
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    cache_read_cost_usd: float
    cost_multiplier: float
    original_cost_usd: float
    billed_cost_usd: float
    cost_usd: float
    context_window_used_tokens: Optional[int]
    context_window_total_tokens: Optional[int]

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
            model=run.model,
            reasoning_effort=run.reasoning_effort,
            enable_parallel_agents=run.enable_parallel_agents,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            cache_read_tokens=run.cache_read_tokens,
            total_tokens=run.total_tokens,
            input_cost_usd=run.input_cost_usd,
            output_cost_usd=run.output_cost_usd,
            cache_read_cost_usd=run.cache_read_cost_usd,
            cost_multiplier=run.cost_multiplier,
            original_cost_usd=run.original_cost_usd,
            billed_cost_usd=run.billed_cost_usd,
            cost_usd=run.cost_usd,
            context_window_used_tokens=run.context_window_used_tokens,
            context_window_total_tokens=run.context_window_total_tokens,
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
    model: Optional[str]
    reasoning_effort: Optional[str]
    enable_parallel_agents: bool
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    cache_read_cost_usd: float
    cost_multiplier: float
    original_cost_usd: float
    billed_cost_usd: float
    cost_usd: float
    context_window_used_tokens: Optional[int]
    context_window_total_tokens: Optional[int]
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
            model=task.model,
            reasoning_effort=task.reasoning_effort,
            enable_parallel_agents=task.enable_parallel_agents,
            prompt_tokens=task.prompt_tokens,
            completion_tokens=task.completion_tokens,
            cache_read_tokens=task.cache_read_tokens,
            total_tokens=task.total_tokens,
            input_cost_usd=task.input_cost_usd,
            output_cost_usd=task.output_cost_usd,
            cache_read_cost_usd=task.cache_read_cost_usd,
            cost_multiplier=task.cost_multiplier,
            original_cost_usd=task.original_cost_usd,
            billed_cost_usd=task.billed_cost_usd,
            cost_usd=task.cost_usd,
            context_window_used_tokens=task.context_window_used_tokens,
            context_window_total_tokens=task.context_window_total_tokens,
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
