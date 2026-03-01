"use client";

import { useEffect, useMemo, useState } from "react";
import { TaskEvent } from "@/lib/api";
import { formatTime } from "@/lib/datetime";
import { bi, statusText } from "@/lib/i18n";

interface NotificationCenterProps {
  events: TaskEvent[];
}

const NOTIFICATION_PAGE_SIZE = 15;

function describeEvent(event: TaskEvent): string {
  if (event.event_type === "task.status.changed") {
    const rawFrom = typeof event.payload.from === "string" ? event.payload.from : "unknown";
    const rawTo = typeof event.payload.to === "string" ? event.payload.to : "unknown";
    const from = rawFrom in STATUS_SET ? statusText(rawFrom as keyof typeof STATUS_SET) : rawFrom;
    const to = rawTo in STATUS_SET ? statusText(rawTo as keyof typeof STATUS_SET) : rawTo;
    return `${bi("状态变更", "Status")}: ${from} -> ${to}`;
  }
  if (event.event_type === "task.summary.updated") {
    return String(event.payload.summary ?? bi("摘要已更新", "Summary updated"));
  }
  if (event.event_type === "task.log.appended") {
    return String(event.payload.message ?? bi("日志已追加", "Log appended"));
  }
  return event.event_type;
}

const STATUS_SET = {
  QUEUED: true,
  RUNNING: true,
  WAITING_INPUT: true,
  SUCCEEDED: true,
  FAILED: true,
  CANCELED: true,
  TIMEOUT: true,
  RETRYING: true
} as const;

export function NotificationCenter({ events }: NotificationCenterProps) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(events.length / NOTIFICATION_PAGE_SIZE));
  const pagedEvents = useMemo(() => {
    const start = (page - 1) * NOTIFICATION_PAGE_SIZE;
    return events.slice(start, start + NOTIFICATION_PAGE_SIZE);
  }, [events, page]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    setPage(1);
  }, [events.length]);

  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("通知", "Notifications")}</h2>
        <span className="chip">{events.length}</span>
      </div>
      {events.length === 0 ? (
        <div className="empty-cta">
          <p className="muted">{bi("暂无通知。", "No notifications yet.")}</p>
          <a className="link" href="#create-task-panel">
            {bi("创建任务后在这里查看状态更新", "Create a task to receive updates here")}
          </a>
        </div>
      ) : (
        <>
          <div className="pagination-row">
            <p className="muted">
              {bi("第", "Page")} {page} / {totalPages} · {bi("共", "Total")} {events.length}{" "}
              {bi("条通知", "notifications")}
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
          <ul className="notification-list">
            {pagedEvents.map((event) => (
              <li key={`${event.id}-${event.seq}`} className="notification-item">
                <div className="task-item-top">
                  <span className={`status status-${(event.status || "queued").toLowerCase()}`}>
                    {event.status ? statusText(event.status) : bi("事件", "Event")}
                  </span>
                  <time dateTime={event.timestamp}>{formatTime(event.timestamp)}</time>
                </div>
                <p>{describeEvent(event)}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
