import Link from "next/link";
import { Task } from "@/lib/api";
import { bi, statusText } from "@/lib/i18n";

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
        <h2 className="panel-title">{bi("任务队列", "Task Queue")}</h2>
        <span className="chip">{tasks.length}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {loading ? <p className="muted">{bi("任务加载中...", "Loading tasks...")}</p> : null}

      {!loading && !error && tasks.length === 0 ? (
        <p className="muted">
          {bi("暂无任务，请先创建一个任务开始监控。", "No tasks yet. Create one to start monitoring from mobile.")}
        </p>
      ) : null}

      <ul className="task-list">
        {tasks.map((task) => (
          <li key={task.id} className="task-item">
            <div className="task-item-top">
              <span className={`status status-${task.status.toLowerCase()}`}>
                {statusText(task.status)}
              </span>
              <time dateTime={task.updated_at}>{formatTime(task.updated_at)}</time>
            </div>
            <p className="task-prompt">{task.prompt || bi("(空指令)", "(empty prompt)")}</p>
            <div className="task-item-bottom">
              <span className="muted">#{task.id.slice(0, 8)}</span>
              <Link href={`/tasks/${task.id}`} className="link">
                {bi("查看详情", "View detail")}
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
