"use client";

import { AuditLog } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface AuditPanelProps {
  logs: AuditLog[];
  total: number;
  limit: number;
  offset: number;
  loading?: boolean;
  onPageChange?: (page: number) => void;
}

export function AuditPanel({
  logs,
  total,
  limit,
  offset,
  loading = false,
  onPageChange
}: AuditPanelProps) {
  const safeLimit = Math.max(1, limit || 20);
  const currentPage = Math.floor(Math.max(0, offset) / safeLimit) + 1;
  const totalPages = Math.max(1, Math.ceil(Math.max(total, 0) / safeLimit));

  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("审计日志", "Audit Logs")}</h2>
        <span className="chip">{total}</span>
      </div>
      {loading ? <p className="muted">{bi("审计日志加载中...", "Loading audit logs...")}</p> : null}
      {!loading ? (
        total === 0 ? (
          <div className="empty-cta">
            <p className="muted">{bi("暂无审计记录。", "No audit records yet.")}</p>
            <a className="link" href="#create-task-panel">
              {bi("创建或操作任务后可在此追踪审计", "Create or operate tasks to see audit trail")}
            </a>
          </div>
        ) : (
          <>
            <div className="pagination-row">
              <p className="muted">
                {bi("第", "Page")} {currentPage} / {totalPages} · {bi("共", "Total")} {total}{" "}
                {bi("条日志", "logs")}
              </p>
              <div className="pagination-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={loading || currentPage <= 1}
                  onClick={() => onPageChange?.(Math.max(1, currentPage - 1))}
                >
                  {bi("上一页", "Previous")}
                </button>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={loading || currentPage >= totalPages}
                  onClick={() => onPageChange?.(Math.min(totalPages, currentPage + 1))}
                >
                  {bi("下一页", "Next")}
                </button>
              </div>
            </div>
            <div className="audit-list-scroll">
              <ul className="notification-list">
                {logs.map((log) => (
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
        )
      ) : null}
    </section>
  );
}
