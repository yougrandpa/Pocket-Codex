#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def as_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


@dataclass
class AuditRow:
    id: int
    timestamp: datetime
    action: str
    task_id: Optional[str]
    detail: dict[str, Any]


def load_audits(db_path: Path, since_days: Optional[int]) -> list[AuditRow]:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    since: Optional[datetime] = None
    if isinstance(since_days, int) and since_days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)

    rows: list[AuditRow] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        for record in conn.execute(
            "SELECT id, timestamp, action, task_id, detail_json FROM audit_logs ORDER BY id ASC"
        ):
            timestamp = parse_iso(str(record["timestamp"]))
            if since and timestamp < since:
                continue
            try:
                detail = json.loads(record["detail_json"] or "{}")
            except json.JSONDecodeError:
                detail = {}
            rows.append(
                AuditRow(
                    id=int(record["id"]),
                    timestamp=timestamp,
                    action=str(record["action"]),
                    task_id=str(record["task_id"]) if record["task_id"] is not None else None,
                    detail=detail if isinstance(detail, dict) else {},
                )
            )
    return rows


def metric_create_to_detail_median_seconds(rows: list[AuditRow]) -> tuple[Optional[float], int]:
    created_at_by_task: dict[str, datetime] = {}
    opened_at_by_task: dict[str, datetime] = {}

    for row in rows:
        if row.task_id and row.action == "task.create" and row.task_id not in created_at_by_task:
            created_at_by_task[row.task_id] = row.timestamp
        if row.task_id and row.action == "ui.event.task.detail.opened" and row.task_id not in opened_at_by_task:
            opened_at_by_task[row.task_id] = row.timestamp

    durations: list[float] = []
    for task_id, created_at in created_at_by_task.items():
        opened_at = opened_at_by_task.get(task_id)
        if opened_at is None:
            continue
        delta = (opened_at - created_at).total_seconds()
        if delta >= 0:
            durations.append(delta)

    if not durations:
        return None, 0
    return float(statistics.median(durations)), len(durations)


def metric_avg_clicks_to_find_target(rows: list[AuditRow]) -> tuple[Optional[float], int]:
    counts: list[float] = []
    for row in rows:
        if row.action != "ui.event.task.detail.opened":
            continue
        if str(row.detail.get("source", "")) != "list":
            continue
        value = as_number(row.detail.get("list_click_count"))
        if value is None or value < 1:
            continue
        counts.append(value)

    if not counts:
        return None, 0
    return float(sum(counts) / len(counts)), len(counts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report key Pocket Codex funnel metrics from audit logs."
    )
    parser.add_argument(
        "--db",
        default="backend/pocket_codex.db",
        help="SQLite database path (default: backend/pocket_codex.db)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=0,
        help="Only include records from recent N days (0 = all)",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    rows = load_audits(db_path, args.since_days if args.since_days > 0 else None)

    median_seconds, sample_2 = metric_create_to_detail_median_seconds(rows)
    avg_clicks, sample_3 = metric_avg_clicks_to_find_target(rows)

    print("Pocket Codex Funnel Metrics")
    print(f"- db: {db_path}")
    print(f"- records: {len(rows)}")
    print(
        "- metric_2.create_to_detail_median_seconds: "
        + (f"{median_seconds:.2f}s (samples={sample_2})" if median_seconds is not None else "N/A (samples=0)")
    )
    print(
        "- metric_3.avg_clicks_to_find_target_task: "
        + (f"{avg_clicks:.2f} (samples={sample_3})" if avg_clicks is not None else "N/A (samples=0)")
    )

    result = {
        "metric_2": {
            "name": "create_to_detail_median_seconds",
            "value": median_seconds,
            "samples": sample_2,
        },
        "metric_3": {
            "name": "avg_clicks_to_find_target_task",
            "value": avg_clicks,
            "samples": sample_3,
        },
    }
    print("\nJSON")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
