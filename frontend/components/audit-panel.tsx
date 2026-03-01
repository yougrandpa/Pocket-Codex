import { AuditLog } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface AuditPanelProps {
  logs: AuditLog[];
}

export function AuditPanel({ logs }: AuditPanelProps) {
  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("审计日志", "Audit Logs")}</h2>
        <span className="chip">{logs.length}</span>
      </div>
      {logs.length === 0 ? (
        <p className="muted">{bi("暂无审计记录。", "No audit records yet.")}</p>
      ) : (
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
      )}
    </section>
  );
}
