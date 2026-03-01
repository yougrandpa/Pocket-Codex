from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Optional, Protocol

from .config import settings

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - optional dependency at runtime
    Redis = None  # type: ignore[assignment]


class ExecutionQueueBackend(Protocol):
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def enqueue(self, task_id: str, *, delay_seconds: float, priority: int) -> None:
        ...

    async def dequeue(self, timeout_seconds: int = 1) -> Optional[str]:
        ...


class LocalExecutionQueue:
    def __init__(self) -> None:
        self._queue: Optional[asyncio.PriorityQueue[tuple[int, int, str]]] = None
        self._loop_id: int | None = None
        self._delayed_tasks: set[asyncio.Task[None]] = set()
        self._enqueue_seq = 0

    async def start(self) -> None:
        loop_id = id(asyncio.get_running_loop())
        if self._queue is None or self._loop_id != loop_id:
            await self.stop()
            self._queue = asyncio.PriorityQueue()
            self._loop_id = loop_id

    async def stop(self) -> None:
        for task in list(self._delayed_tasks):
            task.cancel()
        for task in list(self._delayed_tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._delayed_tasks.clear()
        self._queue = None
        self._loop_id = None

    async def enqueue(self, task_id: str, *, delay_seconds: float, priority: int) -> None:
        queue = self._require_queue()
        self._enqueue_seq += 1
        item = (-int(priority), self._enqueue_seq, task_id)
        if delay_seconds <= 0:
            await queue.put(item)
            return

        async def _delayed_put() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                await queue.put(item)
            finally:
                self._delayed_tasks.discard(task)

        task = asyncio.create_task(_delayed_put())
        self._delayed_tasks.add(task)

    async def dequeue(self, timeout_seconds: int = 1) -> Optional[str]:
        try:
            queue = self._require_queue()
            _, _, task_id = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
            return task_id
        except asyncio.TimeoutError:
            return None

    def _require_queue(self) -> asyncio.PriorityQueue[tuple[int, int, str]]:
        if self._queue is None:
            raise RuntimeError("Local execution queue is not started")
        return self._queue


class RedisExecutionQueue:
    def __init__(self, *, redis_url: str, queue_prefix: str) -> None:
        self._redis_url = redis_url
        self._queue_ready = f"{queue_prefix}:ready"
        self._queue_scheduled = f"{queue_prefix}:scheduled"
        self._redis: Optional[Redis] = None

    async def start(self) -> None:
        if Redis is None:
            raise RuntimeError("redis package is not installed")
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()

    async def stop(self) -> None:
        if self._redis is None:
            return
        await self._redis.aclose()
        self._redis = None

    async def enqueue(self, task_id: str, *, delay_seconds: float, priority: int) -> None:
        redis = self._require_redis()
        priority = int(priority)
        if delay_seconds <= 0:
            score = self._ready_score(priority)
            await redis.zadd(self._queue_ready, {task_id: score})
            return
        due_at = time.time() + delay_seconds
        member = f"{priority}:{task_id}"
        await redis.zadd(self._queue_scheduled, {member: due_at})

    async def dequeue(self, timeout_seconds: int = 1) -> Optional[str]:
        redis = self._require_redis()
        await self._promote_due_jobs(redis)
        item = await redis.bzpopmin(self._queue_ready, timeout=timeout_seconds)
        if item is None:
            return None
        _, task_id, _ = item
        return task_id

    async def _promote_due_jobs(self, redis: Redis, batch_size: int = 50) -> None:
        now = time.time()
        due_members = await redis.zrangebyscore(
            self._queue_scheduled,
            min="-inf",
            max=now,
            start=0,
            num=batch_size,
        )
        if not due_members:
            return
        pipe = redis.pipeline()
        for member in due_members:
            priority, task_id = self._parse_scheduled_member(member)
            pipe.zrem(self._queue_scheduled, member)
            pipe.zadd(self._queue_ready, {task_id: self._ready_score(priority)})
        await pipe.execute()

    @staticmethod
    def _parse_scheduled_member(member: str) -> tuple[int, str]:
        if ":" not in member:
            return 0, member
        priority_raw, task_id = member.split(":", 1)
        try:
            priority = int(priority_raw)
        except ValueError:
            priority = 0
        return priority, task_id

    @staticmethod
    def _ready_score(priority: int) -> float:
        bounded = max(-1000, min(priority, 1000))
        return float(1000 - bounded) + (time.time() / 1_000_000_000)

    def _require_redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("Redis execution queue is not started")
        return self._redis


def create_execution_queue() -> ExecutionQueueBackend:
    if settings.execution_backend == "redis":
        return RedisExecutionQueue(
            redis_url=settings.redis_url,
            queue_prefix=settings.redis_queue_prefix,
        )
    return LocalExecutionQueue()
