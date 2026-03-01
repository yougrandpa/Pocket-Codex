"use client";

import Link from "next/link";
import { useState } from "react";
import { Task, TaskControlAction, controlTask } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi, statusText } from "@/lib/i18n";
import {
  fireAndForgetUiEvent,
  nextTaskListClickCount,
  setTaskNavigationContext
} from "@/lib/telemetry";

interface TaskListProps {
  tasks: Task[];
  total: number;
  limit: number;
  offset: number;
  error?: string | null;
  loading?: boolean;
  onPageChange?: (page: number) => void;
  onTaskMutated?: () => void;
}

function supportedQuickActions(task: Task): TaskControlAction[] {
  if (["RUNNING", "WAITING_INPUT", "QUEUED", "RETRYING"].includes(task.status)) {
    return ["cancel"];
  }
  if (["FAILED", "CANCELED", "TIMEOUT", "SUCCEEDED"].includes(task.status)) {
    return ["retry"];
  }
  return [];
}

function actionLabel(action: TaskControlAction): string {
  if (action === "retry") {
    return bi("重试", "Retry");
  }
  if (action === "cancel") {
    return bi("取消", "Cancel");
  }
  return action;
}

async function copyToClipboard(value: string): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }
  if (window.navigator?.clipboard?.writeText) {
    await window.navigator.clipboard.writeText(value);
    return;
  }
  const area = window.document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "true");
  area.style.position = "absolute";
  area.style.left = "-9999px";
  window.document.body.append(area);
  area.select();
  window.document.execCommand("copy");
  area.remove();
}

export function TaskList({
  tasks,
  total,
  limit,
  offset,
  error = null,
  loading = false,
  onPageChange,
  onTaskMutated
}: TaskListProps) {
  const [workingKey, setWorkingKey] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const safeLimit = Math.max(1, limit || 20);
  const currentPage = Math.floor(Math.max(0, offset) / safeLimit) + 1;
  const totalPages = Math.max(1, Math.ceil(Math.max(total, 0) / safeLimit));

  async function handleTaskAction(task: Task, action: TaskControlAction): Promise<void> {
    setWorkingKey(`${task.id}:${action}`);
    setActionError(null);
    setNote(null);
    try {
      const result = await controlTask(task.id, action);
      setNote(result.message || bi("操作已提交。", "Action submitted."));
      onTaskMutated?.();
    } catch (submitError) {
      setActionError(
        submitError instanceof Error
          ? submitError.message
          : bi("任务操作失败。", "Task action failed.")
      );
    } finally {
      setWorkingKey(null);
    }
  }

  async function handleCopyTaskId(taskId: string): Promise<void> {
    setActionError(null);
    setNote(null);
    try {
      await copyToClipboard(taskId);
      setNote(bi("任务 ID 已复制。", "Task ID copied."));
    } catch {
      setActionError(bi("复制任务 ID 失败。", "Failed to copy task ID."));
    }
  }

  return (
    <section className="panel animate-rise delay-1">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("任务队列", "Task Queue")}</h2>
        <span className="chip">{total}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {actionError ? <p className="error">{actionError}</p> : null}
      {note ? <p className="note">{note}</p> : null}

      {loading ? <p className="muted">{bi("任务加载中...", "Loading tasks...")}</p> : null}

      {!loading && !error && total === 0 ? (
        <div className="empty-cta">
          <p className="muted">
            {bi("暂无任务，请先创建一个任务开始监控。", "No tasks yet. Create one to start monitoring from mobile.")}
          </p>
          <a className="link" href="#create-task-panel">
            {bi("去创建首个任务", "Create your first task")}
          </a>
        </div>
      ) : null}

      {!loading && !error && total > 0 ? (
        <div className="pagination-row">
          <p className="muted">
            {bi("第", "Page")} {currentPage} / {totalPages} · {bi("共", "Total")} {total} {bi("个任务", "tasks")}
          </p>
          <div className="pagination-actions">
            <button
              className="button button-secondary"
              type="button"
              disabled={currentPage <= 1}
              onClick={() => onPageChange?.(Math.max(1, currentPage - 1))}
            >
              {bi("上一页", "Previous")}
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => onPageChange?.(Math.min(totalPages, currentPage + 1))}
            >
              {bi("下一页", "Next")}
            </button>
          </div>
        </div>
      ) : null}

      <div className="task-list-scroll">
        <ul className="task-list">
          {tasks.map((task) => (
            <li key={task.id} className="task-item">
              <div className="task-item-top">
                <span className={`status status-${task.status.toLowerCase()}`}>
                  {statusText(task.status)}
                </span>
                <time dateTime={task.updated_at}>{formatDateTime(task.updated_at)}</time>
              </div>
              <p className="task-prompt">{task.prompt || bi("(空指令)", "(empty prompt)")}</p>
              <div className="task-item-bottom">
                <span className="muted">#{task.id.slice(0, 8)}</span>
                <Link
                  href={`/tasks/${task.id}`}
                  className="link"
                  onClick={() => {
                    const clickCount = nextTaskListClickCount();
                    setTaskNavigationContext(task.id, "list", clickCount);
                    fireAndForgetUiEvent(
                      "task.list.item.clicked",
                      {
                        list_click_count: clickCount,
                        page: currentPage,
                        page_size: safeLimit
                      },
                      task.id
                    );
                  }}
                >
                  {bi("查看详情", "View detail")}
                </Link>
              </div>
              <div className="task-quick-actions">
                {supportedQuickActions(task).map((action) => {
                  const working = workingKey === `${task.id}:${action}`;
                  return (
                    <button
                      key={`${task.id}:${action}`}
                      className="button button-secondary"
                      type="button"
                      disabled={Boolean(workingKey)}
                      onClick={() => {
                        void handleTaskAction(task, action);
                      }}
                    >
                      {working ? bi("处理中...", "Working...") : actionLabel(action)}
                    </button>
                  );
                })}
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={Boolean(workingKey)}
                  onClick={() => {
                    void handleCopyTaskId(task.id);
                  }}
                >
                  {bi("复制任务ID", "Copy ID")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
