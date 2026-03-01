from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import settings
from ..execution_queue import create_execution_queue
from ..models import (
    InMemoryTaskRepository,
    Task,
    TaskEvent,
    TaskMessage,
    TaskRun,
    TaskStatus,
    new_id,
    utc_now_iso,
)
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
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._next_stream_id = 1
        self._load_persisted_tasks()

    def _load_persisted_tasks(self) -> None:
        max_stream_id = 0
        for task in self._storage.load_tasks():
            if not task.runs:
                fallback_run_id = task.current_run_id or new_id("run")
                task.run_sequence = max(task.run_sequence, 1)
                task.current_run_id = fallback_run_id
                task.runs.append(
                    TaskRun(
                        run_id=fallback_run_id,
                        sequence=task.run_sequence,
                        reason="migrated_legacy_task",
                        created_at=task.created_at,
                        status=task.status,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                        summary=task.summary,
                    )
                )
            if task.events:
                max_stream_id = max(max_stream_id, max(event.stream_id for event in task.events))
            self._repo.add(task)
        self._next_stream_id = max_stream_id + 1

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

    async def list_audits(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        actor: str | None = None,
        task_id: str | None = None,
        action: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        items, total = self._storage.list_audits(
            limit=limit,
            offset=offset,
            actor=actor,
            task_id=task_id,
            action=action,
        )
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
        if self._worker_tasks and all(not task.done() for task in self._worker_tasks):
            return
        await self._execution_queue.start()
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(index + 1))
            for index in range(settings.worker_concurrency)
        ]

    async def stop_worker(self) -> None:
        if not self._worker_tasks:
            await self._execution_queue.stop()
            return
        for worker_task in self._worker_tasks:
            worker_task.cancel()
        for worker_task in self._worker_tasks:
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        self._worker_tasks = []
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
        normalized_workdir = self._normalize_workdir_or_raise(workdir)
        now = utc_now_iso()
        base_timeout = timeout_seconds or settings.default_task_timeout_seconds
        effective_timeout = self._normalize_timeout_for_executor(base_timeout)
        task = Task(
            id=new_id("task"),
            prompt=prompt,
            priority=priority,
            workdir=normalized_workdir,
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
            timeout_seconds=effective_timeout,
        )

        async with self._lock:
            self._repo.add(task)
            queued_events: list[dict[str, Any]] = []
            self._create_run_locked(task, reason="task_created", events_out=queued_events)
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
            detail={
                "priority": priority,
                "workdir": normalized_workdir,
                "timeout_seconds": task.timeout_seconds,
            },
        )

        for event in queued_events:
            await self._broadcast(event, subscribers)

        await self._schedule_execution(task.id, delay_seconds=0.2, priority=task.priority)
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
                    process = self._active_processes.get(task_id)
                    if process is not None and process.returncode is None:
                        process.terminate()
                    message = "task canceled"
            elif action == "retry":
                if task.status not in {
                    TaskStatus.FAILED,
                    TaskStatus.CANCELED,
                    TaskStatus.TIMEOUT,
                    TaskStatus.SUCCEEDED,
                }:
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
            await self._schedule_execution(task_id, delay_seconds=retry_delay, priority=task_copy.priority)

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

            if settings.auto_rerun_on_message and task.status in TERMINAL_STATUSES:
                self._schedule_retry_locked(
                    task,
                    reason="message_followup",
                    events_out=queued_events,
                )
                self._append_event_locked(
                    task=task,
                    event_type="task.summary.updated",
                    status=task.status,
                    payload={
                        "summary": "Follow-up message accepted; rerun scheduled."
                    },
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

        if settings.auto_rerun_on_message and task_copy.status == TaskStatus.QUEUED:
            retry_delay = settings.retry_backoff_base_seconds * max(1, task_copy.retry_count)
            await self._schedule_execution(task_id, delay_seconds=retry_delay, priority=task_copy.priority)
        return task_copy, item

    async def subscribe(
        self,
        task_id: Optional[str] = None,
        *,
        last_event_id: str | None = None,
    ) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        replay_events: list[dict[str, Any]] = []
        async with self._lock:
            if task_id:
                self._task_subscribers.setdefault(task_id, set()).add(queue)
            else:
                self._global_subscribers.add(queue)
            replay_events = self._collect_replay_events_locked(
                task_id=task_id,
                last_event_id=last_event_id,
            )
        return queue, replay_events

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

    def _collect_replay_events_locked(
        self,
        *,
        task_id: str | None,
        last_event_id: str | None,
    ) -> list[dict[str, Any]]:
        last_stream_id = self._parse_last_stream_id(last_event_id)
        if last_stream_id < 0:
            return []

        if task_id:
            task = self._repo.get(task_id)
            source_tasks = [task] if task is not None else []
        else:
            source_tasks = self._repo.list()

        replay_events: list[TaskEvent] = []
        for task in source_tasks:
            if task is None:
                continue
            for event in task.events:
                if event.stream_id > last_stream_id:
                    replay_events.append(event)
        replay_events.sort(key=lambda item: item.stream_id)
        if len(replay_events) > settings.sse_replay_limit:
            replay_events = replay_events[-settings.sse_replay_limit :]
        return [self._event_to_payload(event) for event in replay_events]

    @staticmethod
    def _parse_last_stream_id(raw_value: str | None) -> int:
        if raw_value is None:
            return -1
        value = raw_value.strip()
        if not value:
            return -1
        try:
            return max(0, int(value))
        except ValueError:
            return -1

    async def _simulate_run(self, task_id: str) -> None:
        if settings.task_executor == "codex":
            await self._run_codex_task(task_id)
            return

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
                    retry_priority = retry_task.priority if retry_task else 0
                    retry_delay = settings.retry_backoff_base_seconds * max(1, retry_count)
                    await self._schedule_execution(
                        retry_task_id,
                        delay_seconds=retry_delay,
                        priority=retry_priority,
                    )
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

    def _create_run_locked(
        self,
        task: Task,
        *,
        reason: str,
        events_out: list[dict[str, Any]],
    ) -> TaskRun:
        now = utc_now_iso()
        task.run_sequence += 1
        run = TaskRun(
            run_id=new_id("run"),
            sequence=task.run_sequence,
            reason=reason,
            created_at=now,
        )
        task.current_run_id = run.run_id
        task.runs.append(run)
        self._append_event_locked(
            task=task,
            event_type="task.run.created",
            status=task.status,
            payload={
                "run_id": run.run_id,
                "run_sequence": run.sequence,
                "reason": reason,
            },
            events_out=events_out,
        )
        return run

    @staticmethod
    def _current_run(task: Task) -> TaskRun | None:
        if not task.current_run_id:
            return None
        for run in reversed(task.runs):
            if run.run_id == task.current_run_id:
                return run
        return None

    def _schedule_retry_locked(
        self,
        task: Task,
        *,
        reason: str,
        events_out: list[dict[str, Any]],
    ) -> None:
        self._create_run_locked(task, reason=reason, events_out=events_out)
        next_timeout = self._normalize_timeout_for_executor(task.timeout_seconds)
        if next_timeout != task.timeout_seconds:
            task.timeout_seconds = next_timeout
            self._append_log_event_locked(
                task=task,
                message=f"timeout increased to {next_timeout}s for codex executor",
                events_out=events_out,
            )
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

    @staticmethod
    def _normalize_timeout_for_executor(timeout_seconds: int) -> int:
        normalized = max(5, int(timeout_seconds))
        if settings.task_executor == "codex":
            return max(normalized, settings.codex_min_timeout_seconds)
        return normalized

    def _normalize_workdir_or_raise(self, workdir: str | None) -> str | None:
        if workdir is None:
            return None
        raw = workdir.strip()
        if not raw:
            return None
        resolved = Path(raw).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"workdir does not exist or is not a directory: {resolved}")
        for allowed_raw in settings.workdir_whitelist:
            allowed = Path(allowed_raw).resolve()
            try:
                resolved.relative_to(allowed)
                return str(resolved)
            except ValueError:
                continue
        raise ValueError(
            "workdir is outside allowed roots: "
            + ", ".join(settings.workdir_whitelist)
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
        run = self._current_run(task)
        if run is not None:
            run.status = target_status
            if target_status == TaskStatus.RUNNING and run.started_at is None:
                run.started_at = now
            if target_status in TERMINAL_STATUSES:
                run.finished_at = now
                run.summary = task.summary

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
        if task.current_run_id:
            payload = dict(payload)
            payload.setdefault("run_id", task.current_run_id)
            payload.setdefault("run_sequence", task.run_sequence)
        stream_id = self._next_stream_id
        self._next_stream_id += 1
        event = TaskEvent(
            id=new_id("evt"),
            stream_id=stream_id,
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

    async def _schedule_execution(self, task_id: str, *, delay_seconds: float, priority: int) -> None:
        await self.start_worker()
        await self._execution_queue.enqueue(
            task_id,
            delay_seconds=max(0.0, delay_seconds),
            priority=priority,
        )

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            task_id = await self._execution_queue.dequeue(timeout_seconds=1)
            if task_id is None:
                continue
            await self._simulate_run(task_id)

    async def _run_codex_task(self, task_id: str) -> None:
        running_events: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.QUEUED:
                return
            self._transition_locked(
                task=task,
                target_status=TaskStatus.RUNNING,
                payload={"source": "codex"},
                events_out=running_events,
            )
            self._append_log_event_locked(
                task=task,
                message="starting codex executor",
                events_out=running_events,
            )
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)

        for event in running_events:
            await self._broadcast(event, subscribers)

        try:
            normalized_workdir = self._normalize_workdir_or_raise(task.workdir)
        except ValueError as exc:
            await self._mark_task_failed(task_id=task_id, reason=str(exc))
            return
        workdir = normalized_workdir or str(Path.cwd())
        prompt = self._build_codex_prompt(task)
        cmd = [settings.codex_cli_path, "exec", "--skip-git-repo-check", "-C", workdir]
        if settings.codex_full_auto:
            cmd.append("--full-auto")
        if settings.codex_model:
            cmd.extend(["--model", settings.codex_model])
        cmd.append(prompt)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            await self._mark_task_failed(
                task_id=task_id,
                reason=f"codex cli not found at '{settings.codex_cli_path}'",
            )
            return

        self._active_processes[task_id] = process
        output_lines: list[str] = []
        progress = {
            "started_at": time.monotonic(),
            "last_output_at": time.monotonic(),
        }
        reader_tasks = []
        if process.stdout is not None:
            reader_tasks.append(
                asyncio.create_task(
                    self._stream_process_output(
                        task_id,
                        process.stdout,
                        "stdout",
                        output_lines,
                        progress,
                    )
                )
            )
        if process.stderr is not None:
            reader_tasks.append(
                asyncio.create_task(
                    self._stream_process_output(
                        task_id,
                        process.stderr,
                        "stderr",
                        output_lines,
                        progress,
                    )
                )
            )

        timed_out = False
        timeout_reason = "codex execution timeout"
        return_code: int | None = None
        while True:
            try:
                return_code = await asyncio.wait_for(process.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                now = time.monotonic()
                idle_elapsed = now - progress["last_output_at"]
                total_elapsed = now - progress["started_at"]
                if idle_elapsed > task.timeout_seconds:
                    timed_out = True
                    timeout_reason = f"codex execution timeout (idle>{task.timeout_seconds}s)"
                elif total_elapsed > settings.codex_hard_timeout_seconds:
                    timed_out = True
                    timeout_reason = (
                        "codex execution timeout "
                        f"(hard>{settings.codex_hard_timeout_seconds}s)"
                    )
                if timed_out:
                    process.kill()
                    await process.wait()
                    break
        for read_task in reader_tasks:
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass
        self._active_processes.pop(task_id, None)

        if timed_out:
            await self._mark_task_timeout(task_id=task_id, reason=timeout_reason)
            return

        if return_code == 0:
            summary = self._summarize_output(output_lines)
            await self._mark_task_succeeded(task_id=task_id, summary=summary)
        else:
            reason = f"codex exited with code {return_code}"
            await self._mark_task_failed(task_id=task_id, reason=reason, output_lines=output_lines)

    async def _stream_process_output(
        self,
        task_id: str,
        stream: asyncio.StreamReader,
        stream_name: str,
        output_lines: list[str],
        progress: dict[str, float],
    ) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if not text:
                continue
            if self._is_noise_log_line(text):
                continue
            progress["last_output_at"] = time.monotonic()
            output_lines.append(text)
            events_out: list[dict[str, Any]] = []
            async with self._lock:
                task = self._repo.get(task_id)
                if task is None or task.status != TaskStatus.RUNNING:
                    return
                self._append_event_locked(
                    task=task,
                    event_type="task.log.appended",
                    status=task.status,
                    payload={"level": "info", "source": stream_name, "message": text},
                    events_out=events_out,
                )
                self._persist_task_locked(task)
                subscribers = self._collect_subscribers_locked(task.id)
            for event in events_out:
                await self._broadcast(event, subscribers)

    @staticmethod
    def _is_noise_log_line(text: str) -> bool:
        trimmed = text.strip()
        if not trimmed:
            return True
        if len(trimmed) <= 2 and all(char in "{}[]()," for char in trimmed):
            return True
        return False

    async def _mark_task_succeeded(self, *, task_id: str, summary: str | None) -> None:
        events_out: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            task.summary = summary or "Task completed successfully (codex)."
            self._append_event_locked(
                task=task,
                event_type="task.summary.updated",
                status=task.status,
                payload={"summary": task.summary},
                events_out=events_out,
            )
            self._transition_locked(
                task=task,
                target_status=TaskStatus.SUCCEEDED,
                payload={"source": "codex"},
                events_out=events_out,
            )
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
        for event in events_out:
            await self._broadcast(event, subscribers)

    async def _mark_task_timeout(self, *, task_id: str, reason: str) -> None:
        events_out: list[dict[str, Any]] = []
        schedule_auto_retry = False
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            self._transition_locked(
                task=task,
                target_status=TaskStatus.TIMEOUT,
                payload={"source": "codex", "reason": "timeout"},
                events_out=events_out,
            )
            self._append_log_event_locked(task=task, message=reason, events_out=events_out)
            if task.retry_count < settings.max_auto_retries:
                self._schedule_retry_locked(task, reason="auto_retry_timeout", events_out=events_out)
                schedule_auto_retry = True
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
            retry_count = task.retry_count
            retry_priority = task.priority
        for event in events_out:
            await self._broadcast(event, subscribers)
        if schedule_auto_retry:
            retry_delay = settings.retry_backoff_base_seconds * max(1, retry_count)
            await self._schedule_execution(
                task_id,
                delay_seconds=retry_delay,
                priority=retry_priority,
            )

    async def _mark_task_failed(
        self,
        *,
        task_id: str,
        reason: str,
        output_lines: list[str] | None = None,
    ) -> None:
        events_out: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status not in {TaskStatus.RUNNING, TaskStatus.QUEUED}:
                return
            if task.status == TaskStatus.QUEUED:
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.RUNNING,
                    payload={"source": "codex", "reason": "bootstrap_failed"},
                    events_out=events_out,
                )
            tail = self._summarize_output(output_lines or [])
            task.summary = tail or reason
            self._append_event_locked(
                task=task,
                event_type="task.summary.updated",
                status=task.status,
                payload={"summary": task.summary},
                events_out=events_out,
            )
            self._transition_locked(
                task=task,
                target_status=TaskStatus.FAILED,
                payload={"source": "codex", "reason": reason},
                events_out=events_out,
            )
            self._append_log_event_locked(task=task, message=reason, events_out=events_out)
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
        for event in events_out:
            await self._broadcast(event, subscribers)

    @staticmethod
    def _summarize_output(lines: list[str], max_lines: int = 8, max_chars: int = 1200) -> str | None:
        if not lines:
            return None
        picked = lines[-max_lines:]
        text = "\n".join(picked).strip()
        if len(text) > max_chars:
            text = text[-max_chars:]
        return text or None

    @staticmethod
    def _build_codex_prompt(task: Task) -> str:
        if not task.messages:
            return task.prompt
        latest_followup = task.messages[-1].message.strip()
        context_followups = "\n".join(f"- {item.message}" for item in task.messages[-5:])
        return (
            "Original task prompt:\n"
            f"{task.prompt}\n\n"
            "Latest follow-up message (highest priority; override conflicting earlier instructions):\n"
            f"{latest_followup}\n\n"
            "Recent follow-up history for context:\n"
            f"{context_followups}"
        )

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
            "stream_id": event.stream_id,
            "seq": event.seq,
            "task_id": event.task_id,
            "event_type": event.event_type,
            "status": event.status.value if event.status else None,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }


task_service = TaskService()
