import { TaskDetailShell } from "@/components/task-detail-shell";

interface TaskPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function TaskPage({ params }: TaskPageProps) {
  const { id } = await params;
  return <TaskDetailShell taskId={id} />;
}
