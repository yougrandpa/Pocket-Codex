from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import JSON, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import Task, TaskEvent, TaskMessage, TaskStatus, utc_now_iso


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

    def list_audits(self, *, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        with Session(self._engine) as session:
            total = session.scalar(select(func.count(AuditLogRecord.id))) or 0
            records = session.scalars(
                select(AuditLogRecord)
                .order_by(AuditLogRecord.id.desc())
                .offset(offset)
                .limit(limit)
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
                seq=int(item.get("seq", 0)),
                task_id=str(item.get("task_id", "")),
                event_type=str(item.get("event_type", "task.event")),
                status=TaskStatus(item["status"]) if item.get("status") else None,
                timestamp=str(item.get("timestamp", "")),
                payload=dict(item.get("payload", {})),
            )
            for item in payload.get("events", [])
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
            messages=messages,
            events=events,
        )
