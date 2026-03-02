from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import shutil
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


@dataclass
class UsageMetrics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    cache_read_cost_usd: float = 0.0
    cost_multiplier: float = 1.0
    original_cost_usd: float = 0.0
    billed_cost_usd: float = 0.0
    cost_usd: float = 0.0
    context_window_used_tokens: int | None = None
    context_window_total_tokens: int | None = None

    def has_values(self) -> bool:
        return (
            self.prompt_tokens > 0
            or self.completion_tokens > 0
            or self.cache_read_tokens > 0
            or self.total_tokens > 0
            or self.input_cost_usd > 0
            or self.output_cost_usd > 0
            or self.cache_read_cost_usd > 0
            or self.original_cost_usd > 0
            or self.billed_cost_usd > 0
            or self.cost_usd > 0
            or self.context_window_used_tokens is not None
            or self.context_window_total_tokens is not None
        )


class SubscriptionLimitError(RuntimeError):
    pass


_PROMPT_TOKENS_PATTERN = re.compile(
    r"(?:prompt|input|输入)\s*(?:tokens?|token|标记)[^\d]*([\d.,]+(?:[kKmM])?)",
    re.IGNORECASE,
)
_COMPLETION_TOKENS_PATTERN = re.compile(
    r"(?:completion|output|输出)\s*(?:tokens?|token|标记)[^\d]*([\d.,]+(?:[kKmM])?)",
    re.IGNORECASE,
)
_CACHE_READ_TOKENS_PATTERN = re.compile(
    r"(?:cache\s*read|cached?\s*read|缓存读取)\s*(?:tokens?|token|标记)[^\d]*([\d.,]+(?:[kKmM])?)",
    re.IGNORECASE,
)
_TOTAL_TOKENS_PATTERN = re.compile(
    r"(?:total|总)\s*(?:tokens?|token|标记)[^\d]*([\d.,]+(?:[kKmM])?)",
    re.IGNORECASE,
)
_INPUT_COST_PATTERN = re.compile(
    r"(?:input\s*cost|输入成本|输入费用)[^\d$]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_OUTPUT_COST_PATTERN = re.compile(
    r"(?:output\s*cost|输出成本|输出费用)[^\d$]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_CACHE_READ_COST_PATTERN = re.compile(
    r"(?:cache\s*read\s*cost|缓存读取成本|缓存读取费用)[^\d$]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_ORIGINAL_COST_PATTERN = re.compile(
    r"(?:original|原始)[^\d$]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_BILLED_COST_PATTERN = re.compile(
    r"(?:billed|bill|计费)[^\d$]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_GENERIC_COST_PATTERN = re.compile(
    r"(?:cost|费用|usd)[^\d$]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_COST_MULTIPLIER_PATTERN = re.compile(
    r"(?:multiplier|倍率)[^\d]*([\d.]+)x?",
    re.IGNORECASE,
)
_TOKENS_USED_LINE_PATTERN = re.compile(
    r"^tokens\s+used(?:[:：]\s*([\d.,]+(?:[kKmM])?))?$",
    re.IGNORECASE,
)
_NUMBER_ONLY_PATTERN = re.compile(r"^([\d.,]+(?:[kKmM])?)$")
_CONTEXT_WINDOW_FRACTION_PATTERN = re.compile(
    r"(?:context(?:\s*window)?|背景信息窗口|已用)[^\d]*([\d.,]+(?:[kKmM])?)\s*/\s*([\d.,]+(?:[kKmM])?)",
    re.IGNORECASE,
)
_CONTEXT_WINDOW_TEXT_PATTERN = re.compile(
    r"(?:已用|used)\s*([\d.,]+(?:[kKmM])?)\s*(?:tokens?|标记).{0,24}?(?:共|total)\s*([\d.,]+(?:[kKmM])?)",
    re.IGNORECASE,
)
_CONTEXT_WINDOW_PERCENT_PATTERN = re.compile(
    r"(\d{1,3})\s*%\s*(?:已用|used)?",
    re.IGNORECASE,
)
_REASONING_EFFORT_ALLOWED = {"low", "medium", "high"}
_MODEL_PRICING_PER_1M_TOKENS: dict[str, tuple[float, float, float]] = {
    "gpt-5-codex": (1.50, 6.00, 0.15),
    "gpt-5.3-codex": (1.50, 6.00, 0.15),
    "gpt-5": (1.25, 10.00, 0.125),
    "gpt-4.1": (2.00, 8.00, 0.20),
}
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.3-codex": 272_000,
    "gpt-5-codex": 272_000,
    "gpt-5": 272_000,
    "gpt-4.1": 128_000,
}
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_scaled_number(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = raw.strip().lower().replace(",", "")
    if not text:
        return None
    multiplier = 1.0
    if text.endswith("k"):
        multiplier = 1_000.0
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-1]
    try:
        value = float(text) * multiplier
    except ValueError:
        return None
    return max(0, int(round(value)))


def _parse_cost_value(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = raw.strip().replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return max(0.0, value)


def _strip_ansi(raw: str) -> str:
    if not raw:
        return ""
    return _ANSI_ESCAPE_PATTERN.sub("", raw)


def _next_number_only_value(lines: list[str], start_index: int) -> str | None:
    for offset in range(start_index, min(start_index + 3, len(lines))):
        candidate = _strip_ansi(lines[offset]).strip()
        if not candidate:
            continue
        if len(candidate) <= 2 and all(char in "{}[]()," for char in candidate):
            continue
        number_match = _NUMBER_ONLY_PATTERN.match(candidate)
        if number_match:
            return number_match.group(1)
        break
    return None


def _usd_from_tokens(tokens: int, price_per_million: float) -> float:
    if tokens <= 0 or price_per_million <= 0:
        return 0.0
    return (tokens / 1_000_000.0) * price_per_million


def _price_tuple_for_model(model_name: str | None) -> tuple[float, float, float] | None:
    if not model_name:
        return None
    normalized = model_name.strip().lower()
    if normalized in _MODEL_PRICING_PER_1M_TOKENS:
        return _MODEL_PRICING_PER_1M_TOKENS[normalized]
    for key, value in _MODEL_PRICING_PER_1M_TOKENS.items():
        if key in normalized:
            return value
    return None


def _context_window_for_model(model_name: str | None) -> int | None:
    if not model_name:
        return None
    normalized = model_name.strip().lower()
    if normalized in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[normalized]
    for key, value in _MODEL_CONTEXT_WINDOWS.items():
        if key in normalized:
            return value
    return None


class TaskService:
    def __init__(self) -> None:
        self._repo = InMemoryTaskRepository()
        self._storage = Storage(settings.database_url)
        self._lock = asyncio.Lock()
        self._global_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._subscriber_users: dict[asyncio.Queue[dict[str, Any]], str] = {}
        self._subscriber_count_by_user: dict[str, int] = {}
        self._execution_queue = create_execution_queue()
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._next_stream_id = 1
        self._capabilities_cache: dict[str, Any] = {
            "source": settings.task_executor,
            "model_options": [],
            "reasoning_effort_options": ["low", "medium", "high"],
            "supports_parallel_agents": True,
        }
        self._capabilities_cache_updated_at = 0.0
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
                        model=task.model,
                        reasoning_effort=task.reasoning_effort,
                        enable_parallel_agents=task.enable_parallel_agents,
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

    async def get_executor_capabilities(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._capabilities_cache_updated_at < 120:
            return dict(self._capabilities_cache)

        if not self._is_cli_executor():
            model_options = [settings.codex_model] if settings.codex_model else []
            self._capabilities_cache = {
                "source": settings.task_executor,
                "model_options": model_options,
                "reasoning_effort_options": ["low", "medium", "high"],
                "supports_parallel_agents": True,
            }
            self._capabilities_cache_updated_at = now
            return dict(self._capabilities_cache)

        options = await asyncio.to_thread(self._load_cli_capabilities_sync)
        self._capabilities_cache = options
        self._capabilities_cache_updated_at = now
        return dict(self._capabilities_cache)

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
        model: str | None = None,
        reasoning_effort: str | None = None,
        enable_parallel_agents: bool = False,
        actor: str = "system",
    ) -> Task:
        normalized_workdir = self._normalize_workdir_or_raise(workdir)
        normalized_model = self._normalize_model(model)
        normalized_reasoning_effort = self._normalize_reasoning_effort(reasoning_effort)
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
            model=normalized_model,
            reasoning_effort=normalized_reasoning_effort,
            enable_parallel_agents=bool(enable_parallel_agents),
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
                "model": normalized_model,
                "reasoning_effort": normalized_reasoning_effort,
                "enable_parallel_agents": bool(enable_parallel_agents),
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
        user: str | None = None,
    ) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        user_key = (user or "").strip().lower()
        if not user_key:
            user_key = "unknown"
        replay_events: list[dict[str, Any]] = []
        async with self._lock:
            active_global = len(self._subscriber_users)
            if active_global >= settings.sse_max_connections_global:
                raise SubscriptionLimitError("SSE connection limit reached, please retry later")
            active_for_user = self._subscriber_count_by_user.get(user_key, 0)
            if active_for_user >= settings.sse_max_connections_per_user:
                raise SubscriptionLimitError("Too many SSE connections for this account")
            if task_id:
                self._task_subscribers.setdefault(task_id, set()).add(queue)
            else:
                self._global_subscribers.add(queue)
            self._subscriber_users[queue] = user_key
            self._subscriber_count_by_user[user_key] = active_for_user + 1
            replay_events = self._collect_replay_events_locked(
                task_id=task_id,
                last_event_id=last_event_id,
            )
        return queue, replay_events

    async def unsubscribe(
        self, queue: asyncio.Queue[dict[str, Any]], task_id: Optional[str] = None
    ) -> None:
        async with self._lock:
            user_key = self._subscriber_users.pop(queue, None)
            if user_key is not None:
                remaining = self._subscriber_count_by_user.get(user_key, 0) - 1
                if remaining > 0:
                    self._subscriber_count_by_user[user_key] = remaining
                else:
                    self._subscriber_count_by_user.pop(user_key, None)
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
        if self._is_cli_executor():
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
            model=task.model,
            reasoning_effort=task.reasoning_effort,
            enable_parallel_agents=task.enable_parallel_agents,
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
                message=f"timeout increased to {next_timeout}s for cli executor",
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
        if settings.task_executor in {"codex", "codex-cli"}:
            return max(normalized, settings.codex_min_timeout_seconds)
        return normalized

    @staticmethod
    def _normalize_model(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_reasoning_effort(value: str | None) -> str | None:
        raw = value if value is not None else settings.codex_reasoning_effort
        if raw is None:
            return None
        normalized = raw.strip().lower()
        if not normalized:
            return None
        if normalized not in _REASONING_EFFORT_ALLOWED:
            raise ValueError("reasoning_effort must be one of: low, medium, high")
        return normalized

    @staticmethod
    def _is_cli_executor() -> bool:
        return settings.task_executor in {"codex", "codex-cli"}

    @staticmethod
    def _executor_source() -> str:
        if settings.task_executor in {"codex", "codex-cli"}:
            return settings.task_executor
        return "simulator"

    @staticmethod
    def _run_cli_probe(args: list[str]) -> tuple[int, str]:
        import subprocess

        cmd = [settings.codex_cli_path, *args]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
            )
        except (OSError, subprocess.SubprocessError):
            return 1, ""
        output = (completed.stdout or "").strip()
        if not output:
            output = (completed.stderr or "").strip()
        return completed.returncode, output

    def _load_cli_capabilities_sync(self) -> dict[str, Any]:
        model_options: list[str] = []
        model_seen: set[str] = set()
        discovered_from_cli = False

        for args in (["models", "--json"], ["model", "list", "--json"], ["models"]):
            return_code, output = self._run_cli_probe(args)
            if return_code != 0 or not output:
                continue
            discovered = self._parse_model_output(output)
            if discovered:
                discovered_from_cli = True
            for item in discovered:
                if item not in model_seen:
                    model_seen.add(item)
                    model_options.append(item)
            if model_options:
                break

        codex_default_model = self._load_codex_default_model_from_config_sync()
        if codex_default_model and codex_default_model not in model_seen:
            model_seen.add(codex_default_model)
            model_options.insert(0, codex_default_model)
        if settings.codex_model and settings.codex_model not in model_seen:
            model_seen.add(settings.codex_model)
            model_options.insert(0, settings.codex_model)
        if not discovered_from_cli:
            for fallback in ["gpt-5.3-codex", "gpt-5-codex", "gpt-5"]:
                if fallback not in model_seen:
                    model_seen.add(fallback)
                    model_options.append(fallback)
        if not model_options:
            model_options = ["gpt-5-codex", "gpt-5"]

        reasoning_effort_options = ["low", "medium", "high"]
        return_code, help_output = self._run_cli_probe(["exec", "--help"])
        if return_code == 0 and help_output:
            if "reasoning" not in help_output.lower():
                reasoning_effort_options = []

        return {
            "source": settings.task_executor,
            "model_options": model_options,
            "reasoning_effort_options": reasoning_effort_options,
            "supports_parallel_agents": True,
        }

    @staticmethod
    def _parse_model_output(output: str) -> list[str]:
        output = output.strip()
        if not output:
            return []
        model_names: list[str] = []
        seen: set[str] = set()
        if output.startswith("[") or output.startswith("{"):
            try:
                payload = json.loads(output)
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, str):
                            candidate = item.strip()
                        elif isinstance(item, dict):
                            candidate = str(item.get("id") or item.get("name") or "").strip()
                        else:
                            candidate = ""
                        if candidate and candidate not in seen:
                            seen.add(candidate)
                            model_names.append(candidate)
                    return model_names
            except json.JSONDecodeError:
                pass

        for line in output.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate.startswith("-"):
                candidate = candidate.lstrip("-").strip()
            candidate = candidate.split()[0].strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                model_names.append(candidate)
        return model_names

    @staticmethod
    def _load_codex_default_model_from_config_sync() -> str | None:
        codex_home = os.getenv("CODEX_HOME", "").strip()
        candidates = []
        if codex_home:
            candidates.append(Path(codex_home) / "config.toml")
        candidates.append(Path.home() / ".codex" / "config.toml")

        for config_path in candidates:
            try:
                text = config_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = re.match(r'^model\s*=\s*"(.*?)"$', stripped)
                if not match:
                    continue
                model = match.group(1).strip()
                if model:
                    return model
        return None

    def _normalize_workdir_or_raise(self, workdir: str | None) -> str | None:
        default_workdir = Path(settings.workdir_whitelist[0]).resolve()
        if workdir is None:
            return str(default_workdir)
        raw = workdir.strip()
        if not raw:
            return str(default_workdir)
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
        executor_source = self._executor_source()
        running_events: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.QUEUED:
                return
            self._transition_locked(
                task=task,
                target_status=TaskStatus.RUNNING,
                payload={"source": executor_source},
                events_out=running_events,
            )
            self._append_log_event_locked(
                task=task,
                message=f"starting {executor_source} executor",
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
        workdir = normalized_workdir
        prompt = self._build_codex_prompt(task)
        selected_model = task.model or settings.codex_model
        cmd = [settings.codex_cli_path, "exec", "--skip-git-repo-check", "-C", workdir]
        if settings.codex_full_auto:
            cmd.append("--full-auto")
        if selected_model:
            cmd.extend(["--model", selected_model])
        if task.reasoning_effort:
            cmd.extend(["-c", f"model_reasoning_effort={task.reasoning_effort}"])
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
                reason=f"{executor_source} cli not found at '{settings.codex_cli_path}'",
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
        timeout_reason = f"{executor_source} execution timeout"
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
                    timeout_reason = f"{executor_source} execution timeout (idle>{task.timeout_seconds}s)"
                elif total_elapsed > settings.codex_hard_timeout_seconds:
                    timed_out = True
                    timeout_reason = (
                        f"{executor_source} execution timeout "
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
        usage = self._extract_usage_metrics(output_lines, selected_model)

        if timed_out:
            await self._mark_task_timeout(task_id=task_id, reason=timeout_reason, usage=usage)
            return

        if return_code == 0:
            summary = self._summarize_output(output_lines)
            await self._mark_task_succeeded(task_id=task_id, summary=summary, usage=usage)
        else:
            reason = f"{executor_source} exited with code {return_code}"
            await self._mark_task_failed(
                task_id=task_id,
                reason=reason,
                output_lines=output_lines,
                usage=usage,
            )

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

    async def _mark_task_succeeded(
        self,
        *,
        task_id: str,
        summary: str | None,
        usage: UsageMetrics | None = None,
    ) -> None:
        executor_source = self._executor_source()
        events_out: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            task.summary = summary or f"Task completed successfully ({executor_source})."
            self._apply_usage_metrics_locked(task=task, usage=usage, events_out=events_out)
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
                payload={"source": executor_source},
                events_out=events_out,
            )
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
        for event in events_out:
            await self._broadcast(event, subscribers)

    async def _mark_task_timeout(
        self,
        *,
        task_id: str,
        reason: str,
        usage: UsageMetrics | None = None,
    ) -> None:
        executor_source = self._executor_source()
        events_out: list[dict[str, Any]] = []
        schedule_auto_retry = False
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            self._apply_usage_metrics_locked(task=task, usage=usage, events_out=events_out)
            self._transition_locked(
                task=task,
                target_status=TaskStatus.TIMEOUT,
                payload={"source": executor_source, "reason": "timeout"},
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
        usage: UsageMetrics | None = None,
    ) -> None:
        executor_source = self._executor_source()
        events_out: list[dict[str, Any]] = []
        async with self._lock:
            task = self._repo.get(task_id)
            if task is None or task.status not in {TaskStatus.RUNNING, TaskStatus.QUEUED}:
                return
            if task.status == TaskStatus.QUEUED:
                self._transition_locked(
                    task=task,
                    target_status=TaskStatus.RUNNING,
                    payload={"source": executor_source, "reason": "bootstrap_failed"},
                    events_out=events_out,
                )
            self._apply_usage_metrics_locked(task=task, usage=usage, events_out=events_out)
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
                payload={"source": executor_source, "reason": reason},
                events_out=events_out,
            )
            self._append_log_event_locked(task=task, message=reason, events_out=events_out)
            self._persist_task_locked(task)
            subscribers = self._collect_subscribers_locked(task.id)
        for event in events_out:
            await self._broadcast(event, subscribers)

    @staticmethod
    def _extract_usage_metrics(lines: list[str], model_name: str | None = None) -> UsageMetrics | None:
        usage = UsageMetrics()
        context_percent: int | None = None

        for index, raw_line in enumerate(lines):
            line = _strip_ansi(raw_line).strip()
            if not line:
                continue

            tokens_used_match = _TOKENS_USED_LINE_PATTERN.match(line)
            if tokens_used_match:
                total_raw = tokens_used_match.group(1) or _next_number_only_value(lines, index + 1)
                total_tokens = _parse_scaled_number(total_raw)
                if total_tokens is not None:
                    usage.total_tokens = max(usage.total_tokens, total_tokens)

            prompt_match = _PROMPT_TOKENS_PATTERN.search(line)
            if prompt_match:
                prompt_tokens = _parse_scaled_number(prompt_match.group(1))
                if prompt_tokens is not None:
                    usage.prompt_tokens = max(usage.prompt_tokens, prompt_tokens)

            completion_match = _COMPLETION_TOKENS_PATTERN.search(line)
            if completion_match:
                completion_tokens = _parse_scaled_number(completion_match.group(1))
                if completion_tokens is not None:
                    usage.completion_tokens = max(usage.completion_tokens, completion_tokens)

            cache_read_match = _CACHE_READ_TOKENS_PATTERN.search(line)
            if cache_read_match:
                cache_read_tokens = _parse_scaled_number(cache_read_match.group(1))
                if cache_read_tokens is not None:
                    usage.cache_read_tokens = max(usage.cache_read_tokens, cache_read_tokens)

            total_match = _TOTAL_TOKENS_PATTERN.search(line)
            if total_match:
                total_tokens = _parse_scaled_number(total_match.group(1))
                if total_tokens is not None:
                    usage.total_tokens = max(usage.total_tokens, total_tokens)

            input_cost_match = _INPUT_COST_PATTERN.search(line)
            if input_cost_match:
                cost_value = _parse_cost_value(input_cost_match.group(1))
                if cost_value is not None:
                    usage.input_cost_usd = max(usage.input_cost_usd, cost_value)

            output_cost_match = _OUTPUT_COST_PATTERN.search(line)
            if output_cost_match:
                cost_value = _parse_cost_value(output_cost_match.group(1))
                if cost_value is not None:
                    usage.output_cost_usd = max(usage.output_cost_usd, cost_value)

            cache_read_cost_match = _CACHE_READ_COST_PATTERN.search(line)
            if cache_read_cost_match:
                cost_value = _parse_cost_value(cache_read_cost_match.group(1))
                if cost_value is not None:
                    usage.cache_read_cost_usd = max(usage.cache_read_cost_usd, cost_value)

            original_cost_match = _ORIGINAL_COST_PATTERN.search(line)
            if original_cost_match:
                cost_value = _parse_cost_value(original_cost_match.group(1))
                if cost_value is not None:
                    usage.original_cost_usd = max(usage.original_cost_usd, cost_value)

            billed_cost_match = _BILLED_COST_PATTERN.search(line)
            if billed_cost_match:
                cost_value = _parse_cost_value(billed_cost_match.group(1))
                if cost_value is not None:
                    usage.billed_cost_usd = max(usage.billed_cost_usd, cost_value)

            multiplier_match = _COST_MULTIPLIER_PATTERN.search(line)
            if multiplier_match:
                multiplier = _parse_cost_value(multiplier_match.group(1))
                if multiplier is not None and multiplier > 0:
                    usage.cost_multiplier = multiplier

            generic_cost_match = _GENERIC_COST_PATTERN.search(line)
            if generic_cost_match:
                cost_value = _parse_cost_value(generic_cost_match.group(1))
                if cost_value is not None:
                    usage.cost_usd = max(usage.cost_usd, cost_value)

            context_match = _CONTEXT_WINDOW_FRACTION_PATTERN.search(line)
            if context_match:
                context_used = _parse_scaled_number(context_match.group(1))
                context_total = _parse_scaled_number(context_match.group(2))
                if context_used is not None:
                    usage.context_window_used_tokens = context_used
                if context_total is not None:
                    usage.context_window_total_tokens = context_total

            context_text_match = _CONTEXT_WINDOW_TEXT_PATTERN.search(line)
            if context_text_match:
                context_used = _parse_scaled_number(context_text_match.group(1))
                context_total = _parse_scaled_number(context_text_match.group(2))
                if context_used is not None:
                    usage.context_window_used_tokens = context_used
                if context_total is not None:
                    usage.context_window_total_tokens = context_total

            context_percent_match = _CONTEXT_WINDOW_PERCENT_PATTERN.search(line)
            if context_percent_match:
                try:
                    context_percent = max(0, min(100, int(context_percent_match.group(1))))
                except ValueError:
                    pass

        if (
            usage.total_tokens <= 0
            and (usage.prompt_tokens > 0 or usage.completion_tokens > 0 or usage.cache_read_tokens > 0)
        ):
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens + usage.cache_read_tokens
        if (
            usage.context_window_used_tokens is None
            and usage.context_window_total_tokens
            and context_percent is not None
        ):
            usage.context_window_used_tokens = int(
                usage.context_window_total_tokens * (context_percent / 100.0)
            )
        if usage.context_window_total_tokens is None and usage.total_tokens > 0:
            context_total = _context_window_for_model(model_name)
            if context_total is not None:
                usage.context_window_total_tokens = context_total
                usage.context_window_used_tokens = min(context_total, usage.total_tokens)

        pricing = _price_tuple_for_model(model_name)
        if pricing:
            in_price, out_price, cache_price = pricing
            if usage.input_cost_usd <= 0 and usage.prompt_tokens > 0:
                usage.input_cost_usd = _usd_from_tokens(usage.prompt_tokens, in_price)
            if usage.output_cost_usd <= 0 and usage.completion_tokens > 0:
                usage.output_cost_usd = _usd_from_tokens(usage.completion_tokens, out_price)
            if usage.cache_read_cost_usd <= 0 and usage.cache_read_tokens > 0:
                usage.cache_read_cost_usd = _usd_from_tokens(usage.cache_read_tokens, cache_price)
            if (
                usage.total_tokens > 0
                and usage.prompt_tokens <= 0
                and usage.completion_tokens <= 0
                and usage.cache_read_tokens <= 0
                and usage.input_cost_usd <= 0
                and usage.output_cost_usd <= 0
                and usage.cache_read_cost_usd <= 0
                and usage.original_cost_usd <= 0
                and usage.billed_cost_usd <= 0
                and usage.cost_usd <= 0
            ):
                usage.input_cost_usd = _usd_from_tokens(usage.total_tokens, in_price)

        line_item_total = usage.input_cost_usd + usage.output_cost_usd + usage.cache_read_cost_usd
        if usage.original_cost_usd <= 0 and line_item_total > 0:
            usage.original_cost_usd = line_item_total
        if usage.billed_cost_usd <= 0 and usage.original_cost_usd > 0:
            usage.billed_cost_usd = usage.original_cost_usd * max(usage.cost_multiplier, 0.0)
        if usage.cost_usd <= 0 and usage.billed_cost_usd > 0:
            usage.cost_usd = usage.billed_cost_usd

        usage.input_cost_usd = round(usage.input_cost_usd, 6)
        usage.output_cost_usd = round(usage.output_cost_usd, 6)
        usage.cache_read_cost_usd = round(usage.cache_read_cost_usd, 6)
        usage.original_cost_usd = round(usage.original_cost_usd, 6)
        usage.billed_cost_usd = round(usage.billed_cost_usd, 6)
        usage.cost_usd = round(usage.cost_usd, 6)

        return usage if usage.has_values() else None

    def _apply_usage_metrics_locked(
        self,
        *,
        task: Task,
        usage: UsageMetrics | None,
        events_out: list[dict[str, Any]],
    ) -> None:
        if usage is None or not usage.has_values():
            return

        current_run = self._current_run(task)
        payload: dict[str, Any] = {}
        if usage.prompt_tokens > 0:
            task.prompt_tokens += usage.prompt_tokens
            payload["prompt_tokens"] = usage.prompt_tokens
        if usage.completion_tokens > 0:
            task.completion_tokens += usage.completion_tokens
            payload["completion_tokens"] = usage.completion_tokens
        if usage.cache_read_tokens > 0:
            task.cache_read_tokens += usage.cache_read_tokens
            payload["cache_read_tokens"] = usage.cache_read_tokens
        if usage.total_tokens > 0:
            task.total_tokens += usage.total_tokens
            payload["total_tokens"] = usage.total_tokens
        if usage.input_cost_usd > 0:
            task.input_cost_usd = round(task.input_cost_usd + usage.input_cost_usd, 6)
            payload["input_cost_usd"] = round(usage.input_cost_usd, 6)
        if usage.output_cost_usd > 0:
            task.output_cost_usd = round(task.output_cost_usd + usage.output_cost_usd, 6)
            payload["output_cost_usd"] = round(usage.output_cost_usd, 6)
        if usage.cache_read_cost_usd > 0:
            task.cache_read_cost_usd = round(task.cache_read_cost_usd + usage.cache_read_cost_usd, 6)
            payload["cache_read_cost_usd"] = round(usage.cache_read_cost_usd, 6)
        if usage.cost_multiplier > 0:
            task.cost_multiplier = usage.cost_multiplier
            payload["cost_multiplier"] = usage.cost_multiplier
        if usage.original_cost_usd > 0:
            task.original_cost_usd = round(task.original_cost_usd + usage.original_cost_usd, 6)
            payload["original_cost_usd"] = round(usage.original_cost_usd, 6)
        if usage.billed_cost_usd > 0:
            task.billed_cost_usd = round(task.billed_cost_usd + usage.billed_cost_usd, 6)
            payload["billed_cost_usd"] = round(usage.billed_cost_usd, 6)
        if usage.cost_usd > 0:
            task.cost_usd = round(task.cost_usd + usage.cost_usd, 6)
            payload["cost_usd"] = round(usage.cost_usd, 6)
        if usage.context_window_used_tokens is not None:
            task.context_window_used_tokens = usage.context_window_used_tokens
            payload["context_window_used_tokens"] = usage.context_window_used_tokens
        if usage.context_window_total_tokens is not None:
            task.context_window_total_tokens = usage.context_window_total_tokens
            payload["context_window_total_tokens"] = usage.context_window_total_tokens

        if current_run is not None:
            current_run.prompt_tokens = usage.prompt_tokens
            current_run.completion_tokens = usage.completion_tokens
            current_run.cache_read_tokens = usage.cache_read_tokens
            current_run.total_tokens = usage.total_tokens
            current_run.input_cost_usd = round(usage.input_cost_usd, 6)
            current_run.output_cost_usd = round(usage.output_cost_usd, 6)
            current_run.cache_read_cost_usd = round(usage.cache_read_cost_usd, 6)
            current_run.cost_multiplier = usage.cost_multiplier
            current_run.original_cost_usd = round(usage.original_cost_usd, 6)
            current_run.billed_cost_usd = round(usage.billed_cost_usd, 6)
            current_run.cost_usd = round(usage.cost_usd, 6)
            current_run.context_window_used_tokens = usage.context_window_used_tokens
            current_run.context_window_total_tokens = usage.context_window_total_tokens

        if not payload:
            return
        self._append_event_locked(
            task=task,
            event_type="task.usage.updated",
            status=task.status,
            payload=payload,
            events_out=events_out,
        )

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
        preface_parts: list[str] = []
        if task.model:
            preface_parts.append(f"Preferred model: {task.model}")
        if task.reasoning_effort:
            preface_parts.append(f"Reasoning effort: {task.reasoning_effort}")
        if task.enable_parallel_agents:
            preface_parts.append(
                "Execution strategy: use multiple parallel sub-agents/workers for independent subtasks."
            )
        preface = ""
        if preface_parts:
            preface = "\n".join(preface_parts) + "\n\n"

        if not task.messages:
            return f"{preface}{task.prompt}" if preface else task.prompt
        latest_followup = task.messages[-1].message.strip()
        context_followups = "\n".join(f"- {item.message}" for item in task.messages[-5:])
        return (
            f"{preface}"
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
