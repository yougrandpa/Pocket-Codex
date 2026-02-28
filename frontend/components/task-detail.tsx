import Link from "next/link";
import { Task } from "@/lib/api";

interface TaskDetailProps {
  task: Task;
}

function formatValue(value?: string | null): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }

  return date.toLocaleString();
}

export function TaskDetail({ task }: TaskDetailProps): JSX.Element {
  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">Task Detail</h2>
        <span className={`status status-${task.status.toLowerCase()}`}>{task.status}</span>
      </div>

      <div className="detail-grid">
        <div className="detail-block">
          <h3>Prompt</h3>
          <p>{task.prompt}</p>
        </div>
        <div className="detail-block">
          <h3>Summary</h3>
          <p>{task.summary || "No summary yet."}</p>
        </div>
      </div>

      <dl className="meta-list">
        <div>
          <dt>Task ID</dt>
          <dd>{task.id}</dd>
        </div>
        <div>
          <dt>Priority</dt>
          <dd>{task.priority ?? "-"}</dd>
        </div>
        <div>
          <dt>Workdir</dt>
          <dd>{task.workdir || "-"}</dd>
        </div>
        <div>
          <dt>Created At</dt>
          <dd>{formatValue(task.created_at)}</dd>
        </div>
        <div>
          <dt>Updated At</dt>
          <dd>{formatValue(task.updated_at)}</dd>
        </div>
        <div>
          <dt>Started At</dt>
          <dd>{formatValue(task.started_at)}</dd>
        </div>
        <div>
          <dt>Finished At</dt>
          <dd>{formatValue(task.finished_at)}</dd>
        </div>
        <div>
          <dt>Last Heartbeat</dt>
          <dd>{formatValue(task.last_heartbeat_at)}</dd>
        </div>
      </dl>

      <Link href="/" className="link">
        Back to dashboard
      </Link>
    </section>
  );
}
