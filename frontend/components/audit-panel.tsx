"use client";

import { useEffect, useMemo, useState } from "react";
import { AuditLog } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface AuditPanelProps {
  logs: AuditLog[];
}

const AUDIT_PAGE_SIZE = 20;

export function AuditPanel({ logs }: AuditPanelProps) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(logs.length / AUDIT_PAGE_SIZE));
  const pagedLogs = useMemo(() => {
    const start = (page - 1) * AUDIT_PAGE_SIZE;
    return logs.slice(start, start + AUDIT_PAGE_SIZE);
  }, [logs, page]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    setPage(1);
  }, [logs.length]);

  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("审计日志", "Audit Logs")}</h2>
        <span className="chip">{logs.length}</span>
      </div>
      {logs.length === 0 ? (
        <p className="muted">{bi("暂无审计记录。", "No audit records yet.")}</p>
      ) : (
        <>
          <div className="pagination-row">
            <p className="muted">
              {bi("第", "Page")} {page} / {totalPages} · {bi("共", "Total")} {logs.length} {bi("条日志", "logs")}
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
          <div className="audit-list-scroll">
            <ul className="notification-list">
              {pagedLogs.map((log) => (
                <li key={log.id} className="notification-item audit-item">
                  <div className="task-item-top">
                    <strong className="audit-action">{log.action}</strong>
                    <time dateTime={log.timestamp}>{formatDateTime(log.timestamp)}</time>
                  </div>
                  <p className="muted audit-meta">
                    {bi("操作者", "Actor")}: {log.actor}
                    {log.task_id ? ` | ${bi("任务", "Task")}: ${log.task_id.slice(0, 10)}` : ""}
                  </p>
                  {Object.keys(log.detail || {}).length > 0 ? (
                    <code className="audit-detail">{JSON.stringify(log.detail)}</code>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
