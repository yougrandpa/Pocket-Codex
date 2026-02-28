from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any, Optional

from ..models import InMemoryTaskRepository, Task, TaskEvent, TaskMessage, TaskStatus, new_id, utc_now_iso
from ..state import TERMINAL_STATUSES, ensure_transition


@dataclass
class ControlResult:
    task: Task
    accepted: bool
    message: str


class TaskService:
    def __init__(self) -> None:
        self._repo = InMemoryTaskRepository()
        self._lock = asyncio.Lock()
        self._global_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def list_tasks(
        self,
        *,
        status: Optional[TaskStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        async with self._lock:
            items = self._repo.list()
            if status is not None:
                items = [item for item in items if item.status == status]
            items.sort(key=lambda item: item.created_at, reverse=True)
            total = len(items)
            paged = items[offset : offset + limit]
            return [copy.deepcopy(item) for item in paged], total

    async def get_task(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            task = self._repo.get(task_id)
            return copy.deepcopy(task) if task else None

    async def create_task(self, prompt: str, priority: int = 0, workdir: Optional[str] = None) -> Task:
        now = utc_now_iso()
        task = Task(
            id=new_id("task"),
            prompt=prompt,
            priority=priority,
            workdir=workdir,
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )

        async with self._lock:
            self._repo.add(task)
            queued_events: list[dict[str, Any]] = []
            self._append_status_event_locked(
                task=task,
                from_status=None,
                to_status=TaskStatus.QUEUED,
                extra_payload={"reason": "task_created"},
                events_out=queued_events,
            )
            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        for event in queued_events:
            await self._broadcast(event, subscribers)

        asyncio.create_task(self._simulate_run(task.id))
        return task_copy

    async def control_task(self, task_id: str, action: str) -> ControlResult:
        action = action.lower()
        queued_events: list[dict[str, Any]] = []
        subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        schedule_retry = False
        accepted = True
        message = "ok"

        async with self._lock:
            task = self._repo.get(task_id)
            if task is None:
                raise KeyError(task_id)

            if action == "pause":
                if task.status != TaskStatus.RUNNING:
                    accepted = False
                    message = "task is not running"
                else:
                    task.paused_at = utc_now_iso()
                    self._transition_locked(
                        task=task,
                        target_status=TaskStatus.WAITING_INPUT,
                        payload={"action": "pause"},
                        events_out=queued_events,
                    )
                    self._append_log_event_locked(
                        task=task,
                        message="task paused by user",
                        events_out=queued_events,
                    )
                    message = "task paused"
            elif action == "resume":
                if task.status != TaskStatus.WAITING_INPUT:
                    accepted = False
                    message = "task is not waiting for input"
                else:
                    task.paused_at = None
                    self._transition_locked(
                        task=task,
                        target_status=TaskStatus.RUNNING,
                        payload={"action": "resume"},
                        events_out=queued_events,
                    )
                    self._append_log_event_locked(
                        task=task,
                        message="task resumed by user",
                        events_out=queued_events,
                    )
                    message = "task resumed"
            elif action == "cancel":
                if task.status in TERMINAL_STATUSES:
                    accepted = False
                    message = "task already in terminal state"
                else:
                    self._transition_locked(
                        task=task,
                        target_status=TaskStatus.CANCELED,
                        payload={"action": "cancel"},
                        events_out=queued_events,
                    )
                    self._append_log_event_locked(
                        task=task,
                        message="task canceled by user",
                        events_out=queued_events,
                    )
                    message = "task canceled"
            elif action == "retry":
                if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELED, TaskStatus.TIMEOUT}:
                    raise ValueError(
                        f"Task {task_id} in state {task.status} cannot be retried."
                    )
                task.retry_count += 1
                task.paused_at = None
                task.finished_at = None
                task.started_at = None
                task.summary = None
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.RETRYING,
                    payload={"action": "retry"},
                    events_out=queued_events,
                )
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.QUEUED,
                    payload={"reason": "retry"},
                    events_out=queued_events,
                )
                self._append_log_event_locked(
                    task=task,
                    message="task scheduled for retry",
                    events_out=queued_events,
                )
                schedule_retry = True
                message = "task scheduled for retry"
            else:
                raise ValueError(f"Unsupported control action: {action}")

            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        for event in queued_events:
            await self._broadcast(event, subscribers)

        if schedule_retry:
            asyncio.create_task(self._simulate_run(task_id))

        return ControlResult(task=task_copy, accepted=accepted, message=message)

    async def append_message(self, task_id: str, message: str) -> tuple[Task, TaskMessage]:
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None:
                raise KeyError(task_id)

            item = TaskMessage(id=new_id("msg"), message=message, created_at=utc_now_iso())
            task.messages.append(item)
            queued_events: list[dict[str, Any]] = []
            self._append_event_locked(
                task=task,
                event_type="task.message.appended",
                status=task.status,
                payload={"message_id": item.id, "message": item.message},
                events_out=queued_events,
            )
            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        for event in queued_events:
            await self._broadcast(event, subscribers)
        return task_copy, item

    async def subscribe(self, task_id: Optional[str] = None) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        async with self._lock:
            if task_id:
                self._task_subscribers.setdefault(task_id, set()).add(queue)
            else:
                self._global_subscribers.add(queue)
        return queue

    async def unsubscribe(
        self, queue: asyncio.Queue[dict[str, Any]], task_id: Optional[str] = None
    ) -> None:
        async with self._lock:
            if task_id:
                watchers = self._task_subscribers.get(task_id)
                if watchers and queue in watchers:
                    watchers.remove(queue)
                if watchers is not None and not watchers:
                    self._task_subscribers.pop(task_id, None)
            else:
                self._global_subscribers.discard(queue)

    async def _simulate_run(self, task_id: str) -> None:
        await asyncio.sleep(0.4)
        running_events: list[dict[str, Any]] = []
        subscribers: list[asyncio.Queue[dict[str, Any]]] = []

        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.QUEUED:
                return
            self._transition_locked(
                task=task,
                target_status=TaskStatus.RUNNING,
                payload={"source": "simulator"},
                events_out=running_events,
            )
            self._append_log_event_locked(task=task, message="execution started", events_out=running_events)
            subscribers = self._collect_subscribers_locked(task.id)

        for event in running_events:
            await self._broadcast(event, subscribers)

        progress = 0
        while progress < 4:
            await asyncio.sleep(0.6)
            loop_events: list[dict[str, Any]] = []

            async with self._lock:
                task = self._repo.get(task_id)
                if task is None:
                    return
                if task.status in TERMINAL_STATUSES:
                    return
                if task.status == TaskStatus.WAITING_INPUT:
                    self._touch_heartbeat_locked(task)
                    subscribers = self._collect_subscribers_locked(task.id)
                    continue
                if task.status != TaskStatus.RUNNING:
                    return

                progress += 1
                self._append_log_event_locked(
                    task=task,
                    message=f"execution step {progress}/4",
                    events_out=loop_events,
                )
                if progress == 2:
                    task.summary = "Execution is in progress (simulated)."
                    self._append_event_locked(
                        task=task,
                        event_type="task.summary.updated",
                        status=task.status,
                        payload={"summary": task.summary},
                        events_out=loop_events,
                    )
                subscribers = self._collect_subscribers_locked(task.id)

            for event in loop_events:
                await self._broadcast(event, subscribers)

        done_events: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            task.summary = "Task completed successfully (simulated)."
            self._append_event_locked(
                task=task,
                event_type="task.summary.updated",
                status=task.status,
                payload={"summary": task.summary},
                events_out=done_events,
            )
            self._transition_locked(
                task=task,
                target_status=TaskStatus.SUCCEEDED,
                payload={"source": "simulator"},
                events_out=done_events,
            )
            self._append_log_event_locked(task=task, message="execution finished", events_out=done_events)
            subscribers = self._collect_subscribers_locked(task.id)

        for event in done_events:
            await self._broadcast(event, subscribers)

    def _transition_locked(
        self,
        *,
        task: Task,
        target_status: TaskStatus,
        payload: dict[str, Any],
        events_out: list[dict[str, Any]],
    ) -> None:
        from_status = task.status
        ensure_transition(from_status, target_status)
        now = utc_now_iso()
        task.status = target_status
        task.updated_at = now
        task.last_heartbeat_at = now

        if target_status == TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        if target_status == TaskStatus.WAITING_INPUT:
            task.paused_at = task.paused_at or now
        if target_status in TERMINAL_STATUSES:
            task.finished_at = now

        self._append_status_event_locked(
            task=task,
            from_status=from_status,
            to_status=target_status,
            extra_payload=payload,
            events_out=events_out,
        )

    def _append_status_event_locked(
        self,
        *,
        task: Task,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        extra_payload: dict[str, Any],
        events_out: list[dict[str, Any]],
    ) -> None:
        payload: dict[str, Any] = {
            "from": from_status.value if from_status else None,
            "to": to_status.value,
        }
        payload.update(extra_payload)
        self._append_event_locked(
            task=task,
            event_type="task.status.changed",
            status=to_status,
            payload=payload,
            events_out=events_out,
        )

    def _append_log_event_locked(
        self,
        *,
        task: Task,
        message: str,
        events_out: list[dict[str, Any]],
    ) -> None:
        self._append_event_locked(
            task=task,
            event_type="task.log.appended",
            status=task.status,
            payload={"level": "info", "message": message},
            events_out=events_out,
        )

    def _append_event_locked(
        self,
        *,
        task: Task,
        event_type: str,
        status: Optional[TaskStatus],
        payload: dict[str, Any],
        events_out: list[dict[str, Any]],
    ) -> None:
        event = TaskEvent(
            id=new_id("evt"),
            seq=len(task.events) + 1,
            task_id=task.id,
            event_type=event_type,
            status=status,
            timestamp=utc_now_iso(),
            payload=payload,
        )
        task.events.append(event)
        task.updated_at = event.timestamp
        task.last_heartbeat_at = event.timestamp
        events_out.append(self._event_to_payload(event))

    def _touch_heartbeat_locked(self, task: Task) -> None:
        now = utc_now_iso()
        task.updated_at = now
        task.last_heartbeat_at = now

    def _collect_subscribers_locked(self, task_id: str) -> list[asyncio.Queue[dict[str, Any]]]:
        combined = set(self._global_subscribers)
        combined.update(self._task_subscribers.get(task_id, set()))
        return list(combined)

    async def _broadcast(
        self, event_payload: dict[str, Any], subscribers: list[asyncio.Queue[dict[str, Any]]]
    ) -> None:
        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event_payload)
            except asyncio.QueueFull:
                continue

    @staticmethod
    def _event_to_payload(event: TaskEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "seq": event.seq,
            "task_id": event.task_id,
            "event_type": event.event_type,
            "status": event.status.value if event.status else None,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }


task_service = TaskService()
