from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import JSON, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import Task, TaskEvent, TaskMessage, TaskRun, TaskStatus, utc_now_iso


class Base(DeclarativeBase):
    pass


class TaskSnapshotRecord(Base):
    __tablename__ = "task_snapshots"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)
    task_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditLogRecord(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    detail_json: Mapped[str] = mapped_column(Text)


def _make_engine(database_url: str):
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        if database_url.startswith("sqlite:///"):
            raw_path = database_url.removeprefix("sqlite:///")
            if raw_path and raw_path != ":memory:":
                Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(database_url, future=True, connect_args=connect_args)


class Storage:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        Base.metadata.create_all(self._engine)

    def load_tasks(self) -> list[Task]:
        with Session(self._engine) as session:
            records = session.scalars(
                select(TaskSnapshotRecord).order_by(TaskSnapshotRecord.created_at.desc())
            ).all()
            return [self._task_from_dict(record.task_json) for record in records]

    def save_task(self, task: Task) -> None:
        payload = self._task_to_dict(task)
        with Session(self._engine) as session:
            existing = session.get(TaskSnapshotRecord, task.id)
            if existing is None:
                existing = TaskSnapshotRecord(
                    task_id=task.id,
                    status=task.status.value,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                    task_json=payload,
                )
                session.add(existing)
            else:
                existing.status = task.status.value
                existing.updated_at = task.updated_at
                existing.task_json = payload
            session.commit()

    def append_audit(self, *, actor: str, action: str, task_id: str | None, detail: dict[str, Any]) -> None:
        with Session(self._engine) as session:
            record = AuditLogRecord(
                timestamp=utc_now_iso(),
                actor=actor,
                action=action,
                task_id=task_id,
                detail_json=json.dumps(detail, ensure_ascii=True, separators=(",", ":")),
            )
            session.add(record)
            session.commit()

    def list_audits(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        actor: str | None = None,
        task_id: str | None = None,
        action: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = []
        if actor:
            filters.append(AuditLogRecord.actor.ilike(f"%{actor}%"))
        if task_id:
            filters.append(AuditLogRecord.task_id.ilike(f"%{task_id}%"))
        if action:
            filters.append(AuditLogRecord.action.ilike(f"%{action}%"))

        with Session(self._engine) as session:
            count_query = select(func.count(AuditLogRecord.id))
            records_query = select(AuditLogRecord)
            for query_filter in filters:
                count_query = count_query.where(query_filter)
                records_query = records_query.where(query_filter)

            total = session.scalar(count_query) or 0
            records = session.scalars(
                records_query.order_by(AuditLogRecord.id.desc()).offset(offset).limit(limit)
            ).all()
            items = [
                {
                    "id": record.id,
                    "timestamp": record.timestamp,
                    "actor": record.actor,
                    "action": record.action,
                    "task_id": record.task_id,
                    "detail": json.loads(record.detail_json) if record.detail_json else {},
                }
                for record in records
            ]
            return items, int(total)

    @staticmethod
    def _task_to_dict(task: Task) -> dict[str, Any]:
        payload = asdict(task)
        payload["status"] = task.status.value
        for event in payload.get("events", []):
            if isinstance(event.get("status"), TaskStatus):
                event["status"] = event["status"].value
        for run in payload.get("runs", []):
            if isinstance(run.get("status"), TaskStatus):
                run["status"] = run["status"].value
        return payload

    @staticmethod
    def _task_from_dict(payload: dict[str, Any]) -> Task:
        messages = [
            TaskMessage(
                id=str(item.get("id", "")),
                message=str(item.get("message", "")),
                created_at=str(item.get("created_at", "")),
            )
            for item in payload.get("messages", [])
        ]
        events = [
            TaskEvent(
                id=str(item.get("id", "")),
                stream_id=int(item.get("stream_id", 0)),
                seq=int(item.get("seq", 0)),
                task_id=str(item.get("task_id", "")),
                event_type=str(item.get("event_type", "task.event")),
                status=TaskStatus(item["status"]) if item.get("status") else None,
                timestamp=str(item.get("timestamp", "")),
                payload=dict(item.get("payload", {})),
            )
            for item in payload.get("events", [])
        ]
        runs = [
            TaskRun(
                run_id=str(item.get("run_id", "")),
                sequence=int(item.get("sequence", 0)),
                reason=str(item.get("reason", "")),
                created_at=str(item.get("created_at", "")),
                status=TaskStatus(item["status"]) if item.get("status") else TaskStatus.QUEUED,
                started_at=str(item["started_at"]) if item.get("started_at") is not None else None,
                finished_at=str(item["finished_at"]) if item.get("finished_at") is not None else None,
                summary=str(item["summary"]) if item.get("summary") is not None else None,
            )
            for item in payload.get("runs", [])
        ]
        return Task(
            id=str(payload.get("id", "")),
            prompt=str(payload.get("prompt", "")),
            priority=int(payload.get("priority", 0)),
            workdir=str(payload["workdir"]) if payload.get("workdir") is not None else None,
            status=TaskStatus(payload.get("status", TaskStatus.QUEUED.value)),
            created_at=str(payload.get("created_at", utc_now_iso())),
            updated_at=str(payload.get("updated_at", utc_now_iso())),
            summary=str(payload["summary"]) if payload.get("summary") is not None else None,
            started_at=str(payload["started_at"]) if payload.get("started_at") is not None else None,
            finished_at=str(payload["finished_at"]) if payload.get("finished_at") is not None else None,
            last_heartbeat_at=(
                str(payload["last_heartbeat_at"])
                if payload.get("last_heartbeat_at") is not None
                else None
            ),
            paused_at=str(payload["paused_at"]) if payload.get("paused_at") is not None else None,
            retry_count=int(payload.get("retry_count", 0)),
            timeout_seconds=int(payload.get("timeout_seconds", 20)),
            current_run_id=(
                str(payload["current_run_id"]) if payload.get("current_run_id") is not None else None
            ),
            run_sequence=int(payload.get("run_sequence", 0)),
            runs=runs,
            messages=messages,
            events=events,
        )
