import { TaskEvent } from "@/lib/api";

interface NotificationCenterProps {
  events: TaskEvent[];
}

function describeEvent(event: TaskEvent): string {
  if (event.event_type === "task.status.changed") {
    const from = String(event.payload.from ?? "unknown");
    const to = String(event.payload.to ?? "unknown");
    return `Status ${from} -> ${to}`;
  }
  if (event.event_type === "task.summary.updated") {
    return String(event.payload.summary ?? "Summary updated");
  }
  if (event.event_type === "task.log.appended") {
    return String(event.payload.message ?? "Log appended");
  }
  return event.event_type;
}

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
        <h2 className="panel-title">Notifications</h2>
        <span className="chip">{events.length}</span>
      </div>
      {events.length === 0 ? (
        <p className="muted">No notifications yet.</p>
      ) : (
        <ul className="notification-list">
          {events.map((event) => (
            <li key={`${event.id}-${event.seq}`} className="notification-item">
              <div className="task-item-top">
                <span className={`status status-${(event.status || "queued").toLowerCase()}`}>
                  {event.status || "EVENT"}
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
