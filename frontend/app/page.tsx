import { TaskCreator } from "@/components/task-creator";
import { TaskList } from "@/components/task-list";
import { getTasks, Task } from "@/lib/api";

export default async function HomePage(): Promise<JSX.Element> {
  let tasks: Task[] = [];
  let error: string | null = null;

  try {
    tasks = await getTasks();
  } catch (requestError) {
    error = requestError instanceof Error ? requestError.message : "Failed to load tasks.";
  }

  return (
    <div className="page-grid">
      <TaskCreator />
      <TaskList tasks={tasks} error={error} />
    </div>
  );
}
