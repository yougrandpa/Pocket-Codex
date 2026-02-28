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

    async def enqueue(self, task_id: str, delay_seconds: float) -> None:
        ...

    async def dequeue(self, timeout_seconds: int = 1) -> Optional[str]:
        ...


class LocalExecutionQueue:
    def __init__(self) -> None:
        self._queue: Optional[asyncio.Queue[str]] = None
        self._loop_id: int | None = None
        self._delayed_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        loop_id = id(asyncio.get_running_loop())
        if self._queue is None or self._loop_id != loop_id:
            await self.stop()
            self._queue = asyncio.Queue()
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

    async def enqueue(self, task_id: str, delay_seconds: float) -> None:
        queue = self._require_queue()
        if delay_seconds <= 0:
            await queue.put(task_id)
            return

        async def _delayed_put() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                await queue.put(task_id)
            finally:
                self._delayed_tasks.discard(task)

        task = asyncio.create_task(_delayed_put())
        self._delayed_tasks.add(task)

    async def dequeue(self, timeout_seconds: int = 1) -> Optional[str]:
        try:
            queue = self._require_queue()
            return await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None

    def _require_queue(self) -> asyncio.Queue[str]:
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

    async def enqueue(self, task_id: str, delay_seconds: float) -> None:
        redis = self._require_redis()
        if delay_seconds <= 0:
            await redis.lpush(self._queue_ready, task_id)
            return
        due_at = time.time() + delay_seconds
        await redis.zadd(self._queue_scheduled, {task_id: due_at})

    async def dequeue(self, timeout_seconds: int = 1) -> Optional[str]:
        redis = self._require_redis()
        await self._promote_due_jobs(redis)
        item = await redis.brpop(self._queue_ready, timeout=timeout_seconds)
        if item is None:
            return None
        _, task_id = item
        return task_id

    async def _promote_due_jobs(self, redis: Redis, batch_size: int = 50) -> None:
        now = time.time()
        due_jobs = await redis.zrangebyscore(
            self._queue_scheduled,
            min="-inf",
            max=now,
            start=0,
            num=batch_size,
        )
        if not due_jobs:
            return
        pipe = redis.pipeline()
        for task_id in due_jobs:
            pipe.zrem(self._queue_scheduled, task_id)
            pipe.lpush(self._queue_ready, task_id)
        await pipe.execute()

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
