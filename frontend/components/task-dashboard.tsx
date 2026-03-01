"use client";

import { useEffect, useMemo, useState } from "react";
import { AuditPanel } from "@/components/audit-panel";
import { ExecutorStatusBar } from "@/components/executor-status-bar";
import { LoginPanel } from "@/components/login-panel";
import { NotificationCenter } from "@/components/notification-center";
import { TaskCreator } from "@/components/task-creator";
import { TaskList } from "@/components/task-list";
import { bi, useLanguage } from "@/lib/i18n";
import {
  Task,
  AuditLog,
  TaskEvent,
  clearSession,
  getAuditLogs,
  getTasks,
  openEventStream,
  TaskEventStream,
  readSession
} from "@/lib/api";

function mergeTaskFromEvent(tasks: Task[], event: TaskEvent): Task[] {
  const index = tasks.findIndex((task) => task.id === event.task_id);
  if (index < 0) {
    return tasks;
  }
  const next = [...tasks];
  const current = { ...next[index] };
  current.updated_at = event.timestamp;
  current.last_heartbeat_at = event.timestamp;
  if (event.event_type === "task.status.changed") {
    const to = event.payload.to;
    if (typeof to === "string") {
      current.status = to as Task["status"];
      if (to === "RUNNING" && !current.started_at) {
        current.started_at = event.timestamp;
      }
      if (["SUCCEEDED", "FAILED", "CANCELED", "TIMEOUT"].includes(to)) {
        current.finished_at = event.timestamp;
      }
    }
  }
  if (event.event_type === "task.summary.updated") {
    const summary = event.payload.summary;
    if (typeof summary === "string") {
      current.summary = summary;
    }
  }
  next[index] = current;
  return next;
}

export function TaskDashboard() {
  const [language] = useLanguage();
  const [authed, setAuthed] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const session = readSession();
    setAuthed(Boolean(session?.accessToken));
  }, []);

  useEffect(() => {
    if (!authed) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([getTasks(), getAuditLogs(20)])
      .then(([items, logs]) => {
        if (cancelled) {
          return;
        }
        setTasks(items);
        setAuditLogs(logs);
        setError(null);
      })
      .catch((requestError) => {
        if (cancelled) {
          return;
        }
        setError(
          requestError instanceof Error
            ? requestError.message
            : bi("任务加载失败。", "Failed to load tasks.")
        );
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authed]);

  useEffect(() => {
    if (!authed) {
      return;
    }
    let stream: TaskEventStream | null = null;
    try {
      stream = openEventStream({
        onEvent: (parsed) => {
          setTasks((previous) => mergeTaskFromEvent(previous, parsed));
          setEvents((previous) => [parsed, ...previous].slice(0, 80));
        },
        onError: () => {
          setError(
            bi(
              "实时流已断开，正在自动重连...",
              "Realtime stream disconnected. Retrying automatically..."
            )
          );
        }
      });
    } catch (streamError) {
      setError(
        streamError instanceof Error
          ? streamError.message
          : bi("实时流连接失败。", "Failed to open realtime stream.")
      );
    }
    return () => {
      stream?.close();
    };
  }, [authed]);

  const sortedTasks = useMemo(
    () => [...tasks].sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1)),
    [tasks]
  );

  if (!authed) {
    return <LoginPanel onLoggedIn={() => setAuthed(true)} />;
  }

  return (
    <div className="page-grid" data-lang={language}>
      <ExecutorStatusBar />
      <TaskCreator
        onCreated={(task) => {
          setTasks((prev) => [task, ...prev]);
        }}
      />
      <TaskList tasks={sortedTasks} error={error} loading={loading} />
      <NotificationCenter events={events} />
      <AuditPanel logs={auditLogs} />
      <section className="panel animate-rise delay-2">
        <div className="panel-title-row">
          <h2 className="panel-title">{bi("会话", "Session")}</h2>
          <span className="chip">{bi("已激活", "Active")}</span>
        </div>
        <p className="muted">
          {bi("当前使用单用户 JWT 鉴权登录。", "You are signed in with single-user JWT auth.")}
        </p>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => {
            clearSession();
            setAuthed(false);
            setTasks([]);
            setEvents([]);
          }}
        >
          {bi("退出登录", "Sign Out")}
        </button>
      </section>
    </div>
  );
}
