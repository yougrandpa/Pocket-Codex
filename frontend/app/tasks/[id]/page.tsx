import { TaskDetailLive } from "@/components/task-detail-live";

interface TaskPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function TaskPage({ params }: TaskPageProps) {
  const { id } = await params;
  return <TaskDetailLive taskId={id} />;
}
