"use client";

import { useEffect, useState } from "react";
import { TaskDetailLive } from "@/components/task-detail-live";

interface TaskDetailShellProps {
  taskId: string;
}

export function TaskDetailShell({ taskId }: TaskDetailShellProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <section className="panel animate-rise">
        <p className="muted">Loading task detail...</p>
      </section>
    );
  }

  return <TaskDetailLive taskId={taskId} />;
}
