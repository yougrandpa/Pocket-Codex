import Link from "next/link";
import { TaskDetail } from "@/components/task-detail";
import { getTask, Task } from "@/lib/api";

interface TaskPageProps {
  params: Promise<{ id: string }>;
}

export default async function TaskPage({ params }: TaskPageProps): Promise<JSX.Element> {
  const { id } = await params;

  let task: Task | null = null;
  let error: string | null = null;

  try {
    task = await getTask(id);
  } catch (requestError) {
    error = requestError instanceof Error ? requestError.message : "Failed to load task.";
  }

  if (!task) {
    return (
      <section className="panel animate-rise">
        <h2 className="panel-title">Task not available</h2>
        <p className="error">{error || "Task was not found."}</p>
        <Link href="/" className="link">
          Back to dashboard
        </Link>
      </section>
    );
  }

  return <TaskDetail task={task} />;
}
