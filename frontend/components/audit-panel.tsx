import { AuditLog } from "@/lib/api";
import { bi } from "@/lib/i18n";

interface AuditPanelProps {
  logs: AuditLog[];
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return date.toLocaleString();
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
            <li key={log.id} className="notification-item">
              <div className="task-item-top">
                <strong>{log.action}</strong>
                <time dateTime={log.timestamp}>{formatTime(log.timestamp)}</time>
              </div>
              <p className="muted">
                {bi("操作者", "Actor")}: {log.actor}
                {log.task_id ? ` | ${bi("任务", "Task")}: ${log.task_id.slice(0, 10)}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
