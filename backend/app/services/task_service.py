from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import settings
from ..execution_queue import create_execution_queue
from ..models import InMemoryTaskRepository, Task, TaskEvent, TaskMessage, TaskStatus, new_id, utc_now_iso
from ..state import TERMINAL_STATUSES, ensure_transition
from ..storage import Storage


@dataclass
class ControlResult:
    task: Task
    accepted: bool
    message: str


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class TaskService:
    def __init__(self) -> None:
        self._repo = InMemoryTaskRepository()
        self._storage = Storage(settings.database_url)
        self._lock = asyncio.Lock()
        self._global_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._execution_queue = create_execution_queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._load_persisted_tasks()

    def _load_persisted_tasks(self) -> None:
        for task in self._storage.load_tasks():
            self._repo.add(task)

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

    async def list_audits(self, *, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        items, total = self._storage.list_audits(limit=limit, offset=offset)
        return items, total

    def append_audit(
        self,
        *,
        actor: str,
        action: str,
        task_id: str | None,
        detail: dict[str, Any],
    ) -> None:
        self._storage.append_audit(actor=actor, action=action, task_id=task_id, detail=detail)

    async def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            await self._execution_queue.start()
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop_worker(self) -> None:
        if self._worker_task is None:
            await self._execution_queue.stop()
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None
        await self._execution_queue.stop()

    async def create_task(
        self,
        *,
        prompt: str,
        priority: int = 0,
        workdir: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        actor: str = "system",
    ) -> Task:
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
            timeout_seconds=timeout_seconds or settings.default_task_timeout_seconds,
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
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        self._storage.append_audit(
            actor=actor,
            action="task.create",
            task_id=task.id,
            detail={"priority": priority, "workdir": workdir, "timeout_seconds": task.timeout_seconds},
        )

        for event in queued_events:
            await self._broadcast(event, subscribers)

        await self._schedule_execution(task.id, delay_seconds=0.2)
        return task_copy

    async def control_task(self, *, task_id: str, action: str, actor: str = "system") -> ControlResult:
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
                self._schedule_retry_locked(task, reason="manual_retry", events_out=queued_events)
                schedule_retry = True
                message = "task scheduled for retry"
            else:
                raise ValueError(f"Unsupported control action: {action}")

            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        self._storage.append_audit(
            actor=actor,
            action=f"task.control.{action}",
            task_id=task_id,
            detail={"accepted": accepted, "message": message},
        )

        for event in queued_events:
            await self._broadcast(event, subscribers)

        if schedule_retry:
            retry_delay = settings.retry_backoff_base_seconds * max(1, task_copy.retry_count)
            await self._schedule_execution(task_id, delay_seconds=retry_delay)

        return ControlResult(task=task_copy, accepted=accepted, message=message)

    async def append_message(self, *, task_id: str, message: str, actor: str = "system") -> tuple[Task, TaskMessage]:
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
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
            task_copy = copy.deepcopy(task)

        self._storage.append_audit(
            actor=actor,
            action="task.message.append",
            task_id=task_id,
            detail={"message_id": item.id},
        )

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
        await asyncio.sleep(0.3)
        running_events: list[dict[str, Any]] = []
        subscribers: list[asyncio.Queue[dict[str, Any]]] = []

        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.QUEUED:
                return
            self._transition_locked(
                task=task,
                target_status=TaskStatus.RUNNING,
                payload={"source": "worker"},
                events_out=running_events,
            )
            self._append_log_event_locked(task=task, message="execution started", events_out=running_events)
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)

        for event in running_events:
            await self._broadcast(event, subscribers)

        progress = 0
        while progress < 4:
            await asyncio.sleep(0.6)
            loop_events: list[dict[str, Any]] = []
            schedule_auto_retry = False
            retry_task_id: str | None = None

            async with self._lock:
                task = self._repo.get(task_id)
                if task is None:
                    return
                if task.status in TERMINAL_STATUSES:
                    return
                if task.status == TaskStatus.WAITING_INPUT:
                    self._touch_heartbeat_locked(task)
                    self._persist_task_locked(task)
                    continue
                if task.status != TaskStatus.RUNNING:
                    return

                if self._is_timed_out(task):
                    self._transition_locked(
                        task=task,
                        target_status=TaskStatus.TIMEOUT,
                        payload={"source": "worker", "reason": "timeout"},
                        events_out=loop_events,
                    )
                    self._append_log_event_locked(
                        task=task,
                        message="task timed out",
                        events_out=loop_events,
                    )
                    if task.retry_count < settings.max_auto_retries:
                        self._schedule_retry_locked(task, reason="auto_retry_timeout", events_out=loop_events)
                        schedule_auto_retry = True
                    self._persist_task_locked(task)
                    subscribers = self._collect_subscribers_locked(task.id)
                    retry_task_id = task.id

                else:
                    progress += 1
                    self._append_log_event_locked(
                        task=task,
                        message=f"execution step {progress}/4",
                        events_out=loop_events,
                    )
                    if progress == 2:
                        task.summary = "Execution is in progress (worker)."
                        self._append_event_locked(
                            task=task,
                            event_type="task.summary.updated",
                            status=task.status,
                            payload={"summary": task.summary},
                            events_out=loop_events,
                        )
                    self._persist_task_locked(task)
                    subscribers = self._collect_subscribers_locked(task.id)

            for event in loop_events:
                await self._broadcast(event, subscribers)
            if retry_task_id is not None:
                if schedule_auto_retry:
                    retry_task = await self.get_task(retry_task_id)
                    retry_count = retry_task.retry_count if retry_task else 1
                    retry_delay = settings.retry_backoff_base_seconds * max(1, retry_count)
                    await self._schedule_execution(retry_task_id, delay_seconds=retry_delay)
                return

        done_events: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            task.summary = "Task completed successfully (worker)."
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
                payload={"source": "worker"},
                events_out=done_events,
            )
            self._append_log_event_locked(task=task, message="execution finished", events_out=done_events)
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)

        for event in done_events:
            await self._broadcast(event, subscribers)

    def _schedule_retry_locked(
        self,
        task: Task,
        *,
        reason: str,
        events_out: list[dict[str, Any]],
    ) -> None:
        task.retry_count += 1
        task.paused_at = None
        task.finished_at = None
        task.started_at = None
        task.summary = None
        self._transition_locked(
            task=task,
            target_status=TaskStatus.RETRYING,
            payload={"reason": reason},
            events_out=events_out,
        )
        self._transition_locked(
            task=task,
            target_status=TaskStatus.QUEUED,
            payload={"reason": reason},
            events_out=events_out,
        )
        self._append_log_event_locked(
            task=task,
            message=f"task scheduled for retry ({reason})",
            events_out=events_out,
        )

    def _is_timed_out(self, task: Task) -> bool:
        started = _parse_iso(task.started_at)
        if started is None:
            return False
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return elapsed > task.timeout_seconds

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

    def _persist_task_locked(self, task: Task) -> None:
        self._storage.save_task(task)

    async def _schedule_execution(self, task_id: str, *, delay_seconds: float) -> None:
        await self.start_worker()
        await self._execution_queue.enqueue(task_id, max(0.0, delay_seconds))

    async def _worker_loop(self) -> None:
        while True:
            task_id = await self._execution_queue.dequeue(timeout_seconds=1)
            if task_id is None:
                continue
            await self._simulate_run(task_id)

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
