import { TaskEvent } from "@/lib/api";
import { bi, statusText } from "@/lib/i18n";

interface NotificationCenterProps {
  events: TaskEvent[];
}

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

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return date.toLocaleTimeString();
}

export function NotificationCenter({ events }: NotificationCenterProps) {
  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("通知", "Notifications")}</h2>
        <span className="chip">{events.length}</span>
      </div>
      {events.length === 0 ? (
        <p className="muted">{bi("暂无通知。", "No notifications yet.")}</p>
      ) : (
        <ul className="notification-list">
          {events.map((event) => (
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
      )}
    </section>
  );
}
