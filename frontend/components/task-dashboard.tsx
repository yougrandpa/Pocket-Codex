"use client";

import { useEffect, useMemo, useState } from "react";
import { AuditPanel } from "@/components/audit-panel";
import { ExecutorStatusBar } from "@/components/executor-status-bar";
import { LoginPanel } from "@/components/login-panel";
import { MobileLoginApprovals } from "@/components/mobile-login-approvals";
import { NotificationCenter } from "@/components/notification-center";
import { TaskCreator } from "@/components/task-creator";
import { TaskList } from "@/components/task-list";
import { bi, useLanguage } from "@/lib/i18n";
import {
  AuditLogList,
  TaskEvent,
  Task,
  clearSession,
  getAuditLogs,
  getTasks,
  openEventStream,
  TaskEventStream,
  readSession
} from "@/lib/api";

const AUDIT_PAGE_SIZE = 20;

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
  const [auditState, setAuditState] = useState<AuditLogList>({
    total: 0,
    limit: AUDIT_PAGE_SIZE,
    offset: 0,
    items: []
  });
  const [auditLoading, setAuditLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const session = readSession();
    setAuthed(Boolean(session?.accessToken));
  }, []);

  async function loadAuditPage(page: number, silent = false): Promise<void> {
    if (!authed) {
      return;
    }
    const safePage = Math.max(1, page);
    const offset = (safePage - 1) * AUDIT_PAGE_SIZE;
    if (!silent) {
      setAuditLoading(true);
    }
    try {
      const logs = await getAuditLogs(AUDIT_PAGE_SIZE, offset);
      setAuditState(logs);
      setError(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : bi("审计日志加载失败。", "Failed to load audit logs.")
      );
    } finally {
      if (!silent) {
        setAuditLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!authed) {
      setLoading(false);
      setAuditLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setAuditLoading(true);
    Promise.all([getTasks(undefined, { limit: 200 }), getAuditLogs(AUDIT_PAGE_SIZE, 0)])
      .then(([items, logs]) => {
        if (cancelled) {
          return;
        }
        setTasks(items);
        setAuditState(logs);
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
          setAuditLoading(false);
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
  const workdirSuggestions = useMemo(() => {
    const values = tasks
      .map((task) => task.workdir?.trim() || "")
      .filter((item) => item.length > 0);
    return Array.from(new Set(values));
  }, [tasks]);

  if (!authed) {
    return <LoginPanel onLoggedIn={() => setAuthed(true)} />;
  }

  return (
    <div className="page-grid" data-lang={language}>
      <ExecutorStatusBar />
      <div className="dashboard-columns">
        <div className="dashboard-column">
          <TaskCreator
            onCreated={(task) => {
              setTasks((prev) => [task, ...prev]);
            }}
            workdirSuggestions={workdirSuggestions}
          />
          <MobileLoginApprovals enabled={authed} />
          <NotificationCenter events={events} />
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
                setAuditState({
                  total: 0,
                  limit: AUDIT_PAGE_SIZE,
                  offset: 0,
                  items: []
                });
              }}
            >
              {bi("退出登录", "Sign Out")}
            </button>
          </section>
        </div>

        <div className="dashboard-column dashboard-column-right">
          <div className="task-audit-columns">
            <TaskList tasks={sortedTasks} error={error} loading={loading} />
            <AuditPanel
              logs={auditState.items}
              total={auditState.total}
              limit={auditState.limit || AUDIT_PAGE_SIZE}
              offset={auditState.offset}
              loading={auditLoading}
              onPageChange={(page) => {
                void loadAuditPage(page);
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
