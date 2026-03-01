from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TIMEOUT = "TIMEOUT"
    RETRYING = "RETRYING"


@dataclass
class TaskMessage:
    id: str
    message: str
    created_at: str


@dataclass
class TaskEvent:
    id: str
    stream_id: int
    seq: int
    task_id: str
    event_type: str
    status: Optional[TaskStatus]
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskRun:
    run_id: str
    sequence: int
    reason: str
    created_at: str
    status: TaskStatus = TaskStatus.QUEUED
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class Task:
    id: str
    prompt: str
    priority: int
    workdir: Optional[str]
    status: TaskStatus
    created_at: str
    updated_at: str
    summary: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    paused_at: Optional[str] = None
    retry_count: int = 0
    timeout_seconds: int = 20
    current_run_id: Optional[str] = None
    run_sequence: int = 0
    runs: list[TaskRun] = field(default_factory=list)
    messages: list[TaskMessage] = field(default_factory=list)
    events: list[TaskEvent] = field(default_factory=list)


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task: Task) -> None:
        self._tasks[task.id] = task

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        return list(self._tasks.values())
