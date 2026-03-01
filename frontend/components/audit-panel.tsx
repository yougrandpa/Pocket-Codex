"use client";

import { FormEvent, useEffect, useState } from "react";
import { AuditLog, AuditLogFilters } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface AuditPanelProps {
  logs: AuditLog[];
  total: number;
  limit: number;
  offset: number;
  loading?: boolean;
  filters: AuditLogFilters;
  onFilterChange?: (filters: AuditLogFilters) => void;
  onPageChange?: (page: number) => void;
  onExport?: (format: "csv" | "json") => void;
}

export function AuditPanel({
  logs,
  total,
  limit,
  offset,
  loading = false,
  filters,
  onFilterChange,
  onPageChange,
  onExport
}: AuditPanelProps) {
  const [actorInput, setActorInput] = useState(filters.actor ?? "");
  const [taskInput, setTaskInput] = useState(filters.task_id ?? "");
  const [actionInput, setActionInput] = useState(filters.action ?? "");

  useEffect(() => {
    setActorInput(filters.actor ?? "");
    setTaskInput(filters.task_id ?? "");
    setActionInput(filters.action ?? "");
  }, [filters.action, filters.actor, filters.task_id]);

  const safeLimit = Math.max(1, limit || 20);
  const currentPage = Math.floor(Math.max(0, offset) / safeLimit) + 1;
  const totalPages = Math.max(1, Math.ceil(Math.max(total, 0) / safeLimit));

  function emitFilterChange(event?: FormEvent<HTMLFormElement>): void {
    if (event) {
      event.preventDefault();
    }
    onFilterChange?.({
      actor: actorInput,
      task_id: taskInput,
      action: actionInput
    });
  }

  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("审计日志", "Audit Logs")}</h2>
        <span className="chip">{total}</span>
      </div>

      <form className="stack" onSubmit={emitFilterChange}>
        <div className="audit-filter-grid">
          <label className="field">
            <span>{bi("操作者", "Actor")}</span>
            <input
              type="text"
              value={actorInput}
              onChange={(event) => setActorInput(event.target.value)}
              placeholder={bi("按操作者检索", "Filter by actor")}
            />
          </label>
          <label className="field">
            <span>{bi("任务 ID", "Task ID")}</span>
            <input
              type="text"
              value={taskInput}
              onChange={(event) => setTaskInput(event.target.value)}
              placeholder={bi("按任务 ID 检索", "Filter by task id")}
            />
          </label>
          <label className="field">
            <span>{bi("动作", "Action")}</span>
            <input
              type="text"
              value={actionInput}
              onChange={(event) => setActionInput(event.target.value)}
              placeholder={bi("按动作检索", "Filter by action")}
            />
          </label>
        </div>
        <div className="pagination-actions">
          <button className="button button-secondary" type="submit" disabled={loading}>
            {bi("检索", "Search")}
          </button>
          <button
            className="button button-secondary"
            type="button"
            disabled={loading}
            onClick={() => {
              setActorInput("");
              setTaskInput("");
              setActionInput("");
              onFilterChange?.({});
            }}
          >
            {bi("清空筛选", "Clear")}
          </button>
          <button
            className="button button-secondary"
            type="button"
            disabled={loading || total === 0}
            onClick={() => onExport?.("csv")}
          >
            {bi("导出 CSV", "Export CSV")}
          </button>
          <button
            className="button button-secondary"
            type="button"
            disabled={loading || total === 0}
            onClick={() => onExport?.("json")}
          >
            {bi("导出 JSON", "Export JSON")}
          </button>
        </div>
      </form>

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
                      {log.task_id ? ` | ${bi("任务", "Task")}: ${log.task_id.slice(0, 16)}` : ""}
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
