"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Task } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi, statusText } from "@/lib/i18n";
import {
  fireAndForgetUiEvent,
  nextTaskListClickCount,
  setTaskNavigationContext
} from "@/lib/telemetry";

interface TaskListProps {
  tasks: Task[];
  error?: string | null;
  loading?: boolean;
}

const TASK_PAGE_SIZE = 20;

export function TaskList({ tasks, error = null, loading = false }: TaskListProps) {
  const [page, setPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(tasks.length / TASK_PAGE_SIZE));
  const pagedTasks = useMemo(() => {
    const start = (page - 1) * TASK_PAGE_SIZE;
    return tasks.slice(start, start + TASK_PAGE_SIZE);
  }, [page, tasks]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    setPage(1);
  }, [tasks.length]);

  return (
    <section className="panel animate-rise delay-1">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("任务队列", "Task Queue")}</h2>
        <span className="chip">{tasks.length}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {loading ? <p className="muted">{bi("任务加载中...", "Loading tasks...")}</p> : null}

      {!loading && !error && tasks.length === 0 ? (
        <div className="empty-cta">
          <p className="muted">
            {bi("暂无任务，请先创建一个任务开始监控。", "No tasks yet. Create one to start monitoring from mobile.")}
          </p>
          <a className="link" href="#create-task-panel">
            {bi("去创建首个任务", "Create your first task")}
          </a>
        </div>
      ) : null}

      {!loading && !error && tasks.length > 0 ? (
        <div className="pagination-row">
          <p className="muted">
            {bi("第", "Page")} {page} / {totalPages} · {bi("共", "Total")} {tasks.length} {bi("个任务", "tasks")}
          </p>
          <div className="pagination-actions">
            <button
              className="button button-secondary"
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((previous) => Math.max(1, previous - 1))}
            >
              {bi("上一页", "Previous")}
            </button>
            <button
              className="button button-secondary"
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((previous) => Math.min(totalPages, previous + 1))}
            >
              {bi("下一页", "Next")}
            </button>
          </div>
        </div>
      ) : null}

      <div className="task-list-scroll">
        <ul className="task-list">
          {pagedTasks.map((task) => (
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
                        page,
                        page_size: TASK_PAGE_SIZE
                      },
                      task.id
                    );
                  }}
                >
                  {bi("查看详情", "View detail")}
                </Link>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
