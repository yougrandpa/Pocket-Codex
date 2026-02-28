import Link from "next/link";
import { Task } from "@/lib/api";

interface TaskListProps {
  tasks: Task[];
  error?: string | null;
  loading?: boolean;
}

function formatTime(value?: string | null): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }

  return date.toLocaleString();
}

export function TaskList({ tasks, error = null, loading = false }: TaskListProps) {
  return (
    <section className="panel animate-rise delay-1">
      <div className="panel-title-row">
        <h2 className="panel-title">Task Queue</h2>
        <span className="chip">{tasks.length}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {loading ? <p className="muted">Loading tasks...</p> : null}

      {!loading && !error && tasks.length === 0 ? (
        <p className="muted">No tasks yet. Create one to start monitoring from mobile.</p>
      ) : null}

      <ul className="task-list">
        {tasks.map((task) => (
          <li key={task.id} className="task-item">
            <div className="task-item-top">
              <span className={`status status-${task.status.toLowerCase()}`}>{task.status}</span>
              <time dateTime={task.updated_at}>{formatTime(task.updated_at)}</time>
            </div>
            <p className="task-prompt">{task.prompt || "(empty prompt)"}</p>
            <div className="task-item-bottom">
              <span className="muted">#{task.id.slice(0, 8)}</span>
              <Link href={`/tasks/${task.id}`} className="link">
                View detail
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
