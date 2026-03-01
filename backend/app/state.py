from __future__ import annotations

from .models import TaskStatus


TERMINAL_STATUSES: set[TaskStatus] = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELED,
    TaskStatus.TIMEOUT,
}


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELED,
        TaskStatus.TIMEOUT,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_INPUT,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
        TaskStatus.TIMEOUT,
    },
    TaskStatus.WAITING_INPUT: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELED,
        TaskStatus.TIMEOUT,
    },
    TaskStatus.SUCCEEDED: {TaskStatus.RETRYING},
    TaskStatus.FAILED: {TaskStatus.RETRYING},
    TaskStatus.CANCELED: {TaskStatus.RETRYING},
    TaskStatus.TIMEOUT: {TaskStatus.RETRYING},
    TaskStatus.RETRYING: {TaskStatus.QUEUED, TaskStatus.FAILED},
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def ensure_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Invalid task state transition: {current} -> {target}")
