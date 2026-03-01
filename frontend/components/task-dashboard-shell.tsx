"use client";

import { useEffect, useState } from "react";
import { TaskDashboard } from "@/components/task-dashboard";

export function TaskDashboardShell() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <section className="panel animate-rise">
        <p className="muted">Loading dashboard...</p>
      </section>
    );
  }

  return <TaskDashboard />;
}
