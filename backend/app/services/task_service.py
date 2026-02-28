from __future__ import annotations

import asyncio
import copy
from typing import Any, Optional

from ..models import InMemoryTaskRepository, Task, TaskEvent, TaskMessage, TaskStatus, new_id, utc_now_iso
from ..state import TERMINAL_STATUSES, ensure_transition


class TaskService:
    def __init__(self) -> None:
        self._repo = InMemoryTaskRepository()
        self._lock = asyncio.Lock()
        self._global_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        async with self._lock:
            items = self._repo.list()
            if status is not None:
                items = [item for item in items if item.status == status]
            items.sort(key=lambda item: item.created_at, reverse=True)
            return [copy.deepcopy(item) for item in items]

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
            event = self._append_event_locked(
                task=task,
                event_type="task.created",
                status=TaskStatus.QUEUED,
                payload={"prompt": prompt},
            )
            subscribers = self._collect_subscribers_locked(task.id)

        await self._broadcast(event, subscribers)
        asyncio.create_task(self._simulate_run(task.id))
        return copy.deepcopy(task)

    async def control_task(self, task_id: str, action: str) -> Task:
        action = action.lower()
        if action in {"pause", "resume"}:
            raise NotImplementedError(f"Action '{action}' is not implemented in MVP.")
        if action not in {"cancel", "retry"}:
            raise ValueError(f"Unsupported control action: {action}")

        queued_events: list[dict[str, Any]] = []
        subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        schedule_retry = False

        async with self._lock:
            task = self._repo.get(task_id)
            if task is None:
                raise KeyError(task_id)

            if action == "cancel":
                if task.status in TERMINAL_STATUSES:
                    return copy.deepcopy(task)
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.CANCELED,
                    event_type="task.canceled",
                    payload={"action": "cancel"},
                    events_out=queued_events,
                )

            if action == "retry":
                if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELED, TaskStatus.TIMEOUT}:
                    raise ValueError(
                        f"Task {task_id} in state {task.status} cannot be retried."
                    )
                task.retry_count += 1
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.RETRYING,
                    event_type="task.retrying",
                    payload={"action": "retry"},
                    events_out=queued_events,
                )
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.QUEUED,
                    event_type="task.queued",
                    payload={"reason": "retry"},
                    events_out=queued_events,
                )
                schedule_retry = True

            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        for event in queued_events:
            await self._broadcast(event, subscribers)

        if schedule_retry:
            asyncio.create_task(self._simulate_run(task_id))

        return task_copy

    async def append_message(self, task_id: str, message: str) -> Task:
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None:
                raise KeyError(task_id)

            item = TaskMessage(id=new_id("msg"), message=message, created_at=utc_now_iso())
            task.messages.append(item)
            event = self._append_event_locked(
                task=task,
                event_type="task.message.appended",
                status=task.status,
                payload={"message": message},
            )
            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        await self._broadcast(event, subscribers)
        return task_copy

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
        await asyncio.sleep(0.5)
        running_event: Optional[dict[str, Any]] = None
        subscribers: list[asyncio.Queue[dict[str, Any]]] = []

        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.QUEUED:
                return
            events_out: list[dict[str, Any]] = []
            self._transition_locked(
                task=task,
                target_status=TaskStatus.RUNNING,
                event_type="task.running",
                payload={"source": "simulator"},
                events_out=events_out,
            )
            running_event = events_out[0]
            subscribers = self._collect_subscribers_locked(task.id)

        if running_event is not None:
            await self._broadcast(running_event, subscribers)

        await asyncio.sleep(1.0)
        succeeded_event: Optional[dict[str, Any]] = None

        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            task.summary = "Task completed successfully (simulated)."
            events_out: list[dict[str, Any]] = []
            self._transition_locked(
                task=task,
                target_status=TaskStatus.SUCCEEDED,
                event_type="task.succeeded",
                payload={"source": "simulator"},
                events_out=events_out,
            )
            succeeded_event = events_out[0]
            subscribers = self._collect_subscribers_locked(task.id)

        if succeeded_event is not None:
            await self._broadcast(succeeded_event, subscribers)

    def _transition_locked(
        self,
        task: Task,
        target_status: TaskStatus,
        event_type: str,
        payload: dict[str, Any],
        events_out: list[dict[str, Any]],
    ) -> None:
        ensure_transition(task.status, target_status)
        now = utc_now_iso()
        task.status = target_status
        task.updated_at = now
        task.last_heartbeat_at = now

        if target_status == TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        if target_status in TERMINAL_STATUSES:
            task.finished_at = now

        event = self._append_event_locked(
            task=task,
            event_type=event_type,
            status=target_status,
            payload=payload,
        )
        events_out.append(event)

    def _append_event_locked(
        self,
        task: Task,
        event_type: str,
        status: Optional[TaskStatus],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = TaskEvent(
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
        return self._event_to_payload(event)

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
            "seq": event.seq,
            "task_id": event.task_id,
            "event_type": event.event_type,
            "status": event.status.value if event.status else None,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }


task_service = TaskService()
