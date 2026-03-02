#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
from typing import Any

from app.config import settings
from app.models import Task, TaskRun
from app.services import task_service as task_service_module
from app.storage import Storage


def _set_if_changed(obj: object, attr: str, value: Any) -> bool:
    if getattr(obj, attr) == value:
        return False
    setattr(obj, attr, value)
    return True


def _normalize_run_usage_from_total(run: TaskRun) -> bool:
    changed = False
    if run.total_tokens > 0 and run.prompt_tokens <= 0 and run.completion_tokens <= 0 and run.cache_read_tokens <= 0:
        changed |= _set_if_changed(run, "prompt_tokens", run.total_tokens)
    return changed


def _apply_usage_to_run(run: TaskRun, usage: Any) -> bool:
    changed = False
    changed |= _set_if_changed(run, "prompt_tokens", int(usage.prompt_tokens))
    changed |= _set_if_changed(run, "completion_tokens", int(usage.completion_tokens))
    changed |= _set_if_changed(run, "cache_read_tokens", int(usage.cache_read_tokens))
    changed |= _set_if_changed(run, "total_tokens", int(usage.total_tokens))
    changed |= _set_if_changed(run, "input_cost_usd", float(usage.input_cost_usd))
    changed |= _set_if_changed(run, "output_cost_usd", float(usage.output_cost_usd))
    changed |= _set_if_changed(run, "cache_read_cost_usd", float(usage.cache_read_cost_usd))
    changed |= _set_if_changed(run, "cost_multiplier", float(usage.cost_multiplier))
    changed |= _set_if_changed(run, "original_cost_usd", float(usage.original_cost_usd))
    changed |= _set_if_changed(run, "billed_cost_usd", float(usage.billed_cost_usd))
    changed |= _set_if_changed(run, "cost_usd", float(usage.cost_usd))
    changed |= _set_if_changed(run, "context_window_used_tokens", usage.context_window_used_tokens)
    changed |= _set_if_changed(run, "context_window_total_tokens", usage.context_window_total_tokens)
    return changed


def _aggregate_task_from_runs(task: Task) -> bool:
    changed = False
    prompt_tokens = sum(max(0, run.prompt_tokens) for run in task.runs)
    completion_tokens = sum(max(0, run.completion_tokens) for run in task.runs)
    cache_read_tokens = sum(max(0, run.cache_read_tokens) for run in task.runs)
    total_tokens = sum(max(0, run.total_tokens) for run in task.runs)
    if total_tokens <= 0 and (prompt_tokens > 0 or completion_tokens > 0 or cache_read_tokens > 0):
        total_tokens = prompt_tokens + completion_tokens + cache_read_tokens
    input_cost_usd = round(sum(max(0.0, run.input_cost_usd) for run in task.runs), 6)
    output_cost_usd = round(sum(max(0.0, run.output_cost_usd) for run in task.runs), 6)
    cache_read_cost_usd = round(sum(max(0.0, run.cache_read_cost_usd) for run in task.runs), 6)
    original_cost_usd = round(sum(max(0.0, run.original_cost_usd) for run in task.runs), 6)
    billed_cost_usd = round(sum(max(0.0, run.billed_cost_usd) for run in task.runs), 6)
    cost_usd = round(sum(max(0.0, run.cost_usd) for run in task.runs), 6)

    chosen_context_used: int | None = None
    chosen_context_total: int | None = None
    current_run = next((run for run in task.runs if run.run_id == task.current_run_id), None)
    context_candidates = list(task.runs)
    context_candidates.sort(key=lambda item: item.sequence, reverse=True)
    if current_run is not None:
        context_candidates = [current_run, *[item for item in context_candidates if item.run_id != current_run.run_id]]
    for run in context_candidates:
        if run.context_window_total_tokens is not None or run.context_window_used_tokens is not None:
            chosen_context_used = run.context_window_used_tokens
            chosen_context_total = run.context_window_total_tokens
            break

    if chosen_context_total is None and total_tokens > 0:
        context_total = task_service_module._context_window_for_model(task.model)
        if context_total is None and current_run is not None:
            context_total = task_service_module._context_window_for_model(current_run.model)
        if context_total is not None:
            chosen_context_total = context_total
            chosen_context_used = min(context_total, total_tokens)

    if (
        total_tokens > 0
        and prompt_tokens <= 0
        and completion_tokens <= 0
        and cache_read_tokens <= 0
    ):
        prompt_tokens = total_tokens

    changed |= _set_if_changed(task, "prompt_tokens", prompt_tokens)
    changed |= _set_if_changed(task, "completion_tokens", completion_tokens)
    changed |= _set_if_changed(task, "cache_read_tokens", cache_read_tokens)
    changed |= _set_if_changed(task, "total_tokens", total_tokens)
    changed |= _set_if_changed(task, "input_cost_usd", input_cost_usd)
    changed |= _set_if_changed(task, "output_cost_usd", output_cost_usd)
    changed |= _set_if_changed(task, "cache_read_cost_usd", cache_read_cost_usd)
    changed |= _set_if_changed(task, "original_cost_usd", original_cost_usd)
    changed |= _set_if_changed(task, "billed_cost_usd", billed_cost_usd)
    changed |= _set_if_changed(task, "cost_usd", cost_usd)
    changed |= _set_if_changed(task, "context_window_used_tokens", chosen_context_used)
    changed |= _set_if_changed(task, "context_window_total_tokens", chosen_context_total)
    if current_run is not None:
        changed |= _set_if_changed(task, "cost_multiplier", current_run.cost_multiplier)
    return changed


def _repair_task(task: Task) -> tuple[Task, bool]:
    changed = False
    runs_by_id = {run.run_id: run for run in task.runs if run.run_id}
    logs_by_run: dict[str, list[str]] = defaultdict(list)
    unscoped_logs: list[str] = []
    for event in sorted(task.events, key=lambda item: item.seq):
        if event.event_type != "task.log.appended":
            continue
        message = (event.payload or {}).get("message")
        if not isinstance(message, str):
            continue
        run_id = (event.payload or {}).get("run_id")
        if isinstance(run_id, str) and run_id in runs_by_id:
            logs_by_run[run_id].append(message)
        else:
            unscoped_logs.append(message)

    if unscoped_logs:
        if len(task.runs) == 1:
            logs_by_run[task.runs[0].run_id].extend(unscoped_logs)
        elif task.current_run_id and task.current_run_id in runs_by_id:
            logs_by_run[task.current_run_id].extend(unscoped_logs)

    for run in task.runs:
        model_name = run.model or task.model
        lines = logs_by_run.get(run.run_id, [])
        if lines:
            usage = task_service_module.TaskService._extract_usage_metrics(lines, model_name=model_name)
            if usage is not None:
                changed |= _apply_usage_to_run(run, usage)
            else:
                changed |= _normalize_run_usage_from_total(run)
        else:
            changed |= _normalize_run_usage_from_total(run)

    changed |= _aggregate_task_from_runs(task)
    return task, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill and repair task usage metrics in snapshot storage.")
    parser.add_argument("--database-url", default=settings.database_url, help="SQLAlchemy database URL")
    parser.add_argument("--dry-run", action="store_true", help="Preview only without writing changes")
    args = parser.parse_args()

    storage = Storage(args.database_url)
    tasks = storage.load_tasks()
    total = len(tasks)
    changed_count = 0

    for task in tasks:
        before = Storage._task_to_dict(copy.deepcopy(task))
        repaired_task, changed = _repair_task(task)
        after = Storage._task_to_dict(repaired_task)
        if not changed and before == after:
            continue
        changed_count += 1
        if not args.dry_run:
            storage.save_task(repaired_task)

    mode = "dry-run" if args.dry_run else "apply"
    print(f"[backfill] mode={mode} total_tasks={total} changed_tasks={changed_count}")


if __name__ == "__main__":
    main()
