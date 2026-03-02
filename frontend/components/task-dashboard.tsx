"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AuditPanel } from "@/components/audit-panel";
import { ExecutorStatusBar } from "@/components/executor-status-bar";
import { LoginPanel } from "@/components/login-panel";
import { MobileLoginApprovals } from "@/components/mobile-login-approvals";
import { NotificationCenter } from "@/components/notification-center";
import { TaskCreator } from "@/components/task-creator";
import { TaskList } from "@/components/task-list";
import { bi, useLanguage } from "@/lib/i18n";
import {
  AuditLog,
  AuditLogFilters,
  AuditLogList,
  TaskEvent,
  Task,
  TaskDetail,
  TaskListResult,
  clearSession,
  getAuditLogs,
  getTask,
  getTasks,
  openEventStream,
  TaskEventStream,
  readSession
} from "@/lib/api";

const AUDIT_PAGE_SIZE = 20;
const TASK_PAGE_SIZE = 20;
const EXPORT_PAGE_SIZE = 500;
const DASHBOARD_MODE_STORAGE_KEY = "pocket_codex_dashboard_mode";

type DashboardMode = "beginner" | "advanced";

function parseTaskPage(raw: string | null): number {
  if (!raw) {
    return 1;
  }
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value < 1) {
    return 1;
  }
  return value;
}

function readTaskPageFromLocation(): number {
  if (typeof window === "undefined") {
    return 1;
  }
  const params = new URLSearchParams(window.location.search);
  return parseTaskPage(params.get("taskPage"));
}

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
  if (event.event_type === "task.usage.updated") {
    const keys: Array<keyof Task> = [
      "prompt_tokens",
      "completion_tokens",
      "cache_read_tokens",
      "total_tokens",
      "input_cost_usd",
      "output_cost_usd",
      "cache_read_cost_usd",
      "cost_multiplier",
      "original_cost_usd",
      "billed_cost_usd",
      "cost_usd",
      "context_window_used_tokens",
      "context_window_total_tokens"
    ];
    for (const key of keys) {
      const value = event.payload[key as string];
      if (typeof value === "number") {
        (current as Record<string, unknown>)[key] = value;
      }
    }
  }
  next[index] = current;
  return next;
}

function normalizeAuditFilters(filters: AuditLogFilters): AuditLogFilters {
  const normalized: AuditLogFilters = {};
  if (filters.actor?.trim()) {
    normalized.actor = filters.actor.trim();
  }
  if (filters.task_id?.trim()) {
    normalized.task_id = filters.task_id.trim();
  }
  if (filters.action?.trim()) {
    normalized.action = filters.action.trim();
  }
  return normalized;
}

function toCsvField(value: string): string {
  const escaped = value.replace(/"/g, '""');
  return `"${escaped}"`;
}

function buildAuditCsv(items: AuditLog[]): string {
  const header = ["id", "timestamp", "actor", "action", "task_id", "detail"];
  const rows = items.map((item) => {
    return [
      String(item.id),
      item.timestamp,
      item.actor,
      item.action,
      item.task_id ?? "",
      JSON.stringify(item.detail ?? {})
    ]
      .map(toCsvField)
      .join(",");
  });
  return [header.join(","), ...rows].join("\n");
}

function downloadTextFile(fileName: string, content: string, contentType: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const blob = new Blob([content], { type: contentType });
  const url = window.URL.createObjectURL(blob);
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  window.document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export function TaskDashboard() {
  const [language] = useLanguage();
  const [authed, setAuthed] = useState(false);
  const [mode, setMode] = useState<DashboardMode>("beginner");
  const [taskState, setTaskState] = useState<TaskListResult>({
    total: 0,
    limit: TASK_PAGE_SIZE,
    offset: 0,
    items: []
  });
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [auditState, setAuditState] = useState<AuditLogList>({
    total: 0,
    limit: AUDIT_PAGE_SIZE,
    offset: 0,
    items: []
  });
  const [auditFilters, setAuditFilters] = useState<AuditLogFilters>({});
  const [auditLoading, setAuditLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskLoading, setTaskLoading] = useState(true);

  const taskPage = Math.floor(taskState.offset / Math.max(1, taskState.limit)) + 1;
  const taskPageRef = useRef(taskPage);
  const backfillingTaskIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    taskPageRef.current = taskPage;
  }, [taskPage]);

  useEffect(() => {
    const session = readSession();
    setAuthed(Boolean(session?.accessToken));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = window.localStorage.getItem(DASHBOARD_MODE_STORAGE_KEY);
    if (raw === "beginner" || raw === "advanced") {
      setMode(raw);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(DASHBOARD_MODE_STORAGE_KEY, mode);
  }, [mode]);

  const updateTaskPageQuery = useCallback((page: number): void => {
    if (typeof window === "undefined") {
      return;
    }
    const url = new URL(window.location.href);
    if (page <= 1) {
      url.searchParams.delete("taskPage");
    } else {
      url.searchParams.set("taskPage", String(page));
    }
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

  const loadTaskPage = useCallback(
    async (page: number, silent = false, persistPage = !silent): Promise<void> => {
      if (!authed) {
        return;
      }
      const safePage = Math.max(1, page);
      const offset = (safePage - 1) * TASK_PAGE_SIZE;
      if (persistPage) {
        updateTaskPageQuery(safePage);
      }
      if (!silent) {
        setTaskLoading(true);
      }
      try {
        const result = await getTasks(undefined, { limit: TASK_PAGE_SIZE, offset });
        setTaskState(result);
        setError(null);
      } catch (requestError) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : bi("任务加载失败。", "Failed to load tasks.")
        );
      } finally {
        if (!silent) {
          setTaskLoading(false);
        }
      }
    },
    [authed, updateTaskPageQuery]
  );

  const loadAuditPage = useCallback(
    async (page: number, filters: AuditLogFilters, silent = false): Promise<void> => {
      if (!authed) {
        return;
      }
      const safePage = Math.max(1, page);
      const offset = (safePage - 1) * AUDIT_PAGE_SIZE;
      if (!silent) {
        setAuditLoading(true);
      }
      try {
        const logs = await getAuditLogs(AUDIT_PAGE_SIZE, offset, filters);
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
    },
    [authed]
  );

  const backfillUnknownTask = useCallback(
    async (taskId: string): Promise<void> => {
      if (!authed || !taskId || backfillingTaskIdsRef.current.has(taskId)) {
        return;
      }
      backfillingTaskIdsRef.current.add(taskId);
      try {
        const detail: TaskDetail = await getTask(taskId);
        if (taskPageRef.current === 1) {
          setTaskState((previous) => {
            const existing = previous.items.filter((item) => item.id !== detail.task.id);
            const nextItems = [detail.task, ...existing].slice(0, previous.limit || TASK_PAGE_SIZE);
            return { ...previous, items: nextItems };
          });
        }
        await loadTaskPage(taskPageRef.current, true);
      } catch {
        await loadTaskPage(taskPageRef.current, true);
      } finally {
        backfillingTaskIdsRef.current.delete(taskId);
      }
    },
    [authed, loadTaskPage]
  );

  useEffect(() => {
    if (!authed) {
      setTaskLoading(false);
      setAuditLoading(false);
      return;
    }
    let cancelled = false;
    setTaskLoading(true);
    setAuditLoading(true);
    const initialTaskPage = readTaskPageFromLocation();

    Promise.all([
      getTasks(undefined, { limit: TASK_PAGE_SIZE, offset: (initialTaskPage - 1) * TASK_PAGE_SIZE }),
      getAuditLogs(AUDIT_PAGE_SIZE, 0, auditFilters)
    ])
      .then(([taskResult, logs]) => {
        if (cancelled) {
          return;
        }
        setTaskState(taskResult);
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
          setTaskLoading(false);
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
          let missingTask = false;
          setTaskState((previous) => {
            const merged = mergeTaskFromEvent(previous.items, parsed);
            if (merged === previous.items) {
              missingTask = true;
              return previous;
            }
            return { ...previous, items: merged };
          });
          setEvents((previous) => [parsed, ...previous].slice(0, 80));
          if (missingTask) {
            void backfillUnknownTask(parsed.task_id);
          }
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
  }, [authed, backfillUnknownTask]);

  const sortedTasks = useMemo(
    () => [...taskState.items].sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1)),
    [taskState.items]
  );

  const workdirSuggestions = useMemo(() => {
    const values = taskState.items
      .map((task) => task.workdir?.trim() || "")
      .filter((item) => item.length > 0);
    return Array.from(new Set(values));
  }, [taskState.items]);

  async function handleExportAudit(format: "csv" | "json"): Promise<void> {
    if (!authed) {
      return;
    }
    setAuditLoading(true);
    try {
      const activeFilters = normalizeAuditFilters(auditFilters);
      const allItems: AuditLog[] = [];
      let offset = 0;
      let total = 1;
      while (offset < total) {
        const page = await getAuditLogs(EXPORT_PAGE_SIZE, offset, activeFilters);
        total = Math.max(page.total, 0);
        allItems.push(...page.items);
        if (page.items.length === 0) {
          break;
        }
        offset += page.items.length;
      }

      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      if (format === "json") {
        downloadTextFile(
          `audit-logs-${timestamp}.json`,
          JSON.stringify(allItems, null, 2),
          "application/json;charset=utf-8"
        );
      } else {
        downloadTextFile(
          `audit-logs-${timestamp}.csv`,
          buildAuditCsv(allItems),
          "text/csv;charset=utf-8"
        );
      }
    } catch (exportError) {
      setError(
        exportError instanceof Error
          ? exportError.message
          : bi("导出审计日志失败。", "Failed to export audit logs.")
      );
    } finally {
      setAuditLoading(false);
    }
  }

  if (!authed) {
    return <LoginPanel onLoggedIn={() => setAuthed(true)} />;
  }

  const isBeginnerMode = mode === "beginner";
  const taskAuditClassName = isBeginnerMode
    ? "task-audit-columns task-audit-columns-single"
    : "task-audit-columns";

  return (
    <div className="page-grid" data-lang={language}>
      <section className="panel animate-rise">
        <div className="panel-title-row">
          <h2 className="panel-title">{bi("首页模式", "Home mode")}</h2>
          <span className="chip">
            {isBeginnerMode ? bi("新手", "Beginner") : bi("高级", "Advanced")}
          </span>
        </div>
        <p className="muted">
          {bi(
            "新手模式聚焦核心操作，高级模式展示完整控制台。",
            "Beginner mode keeps essentials only, while advanced mode shows the full console."
          )}
        </p>
        <div className="mode-switch-grid">
          <button
            className={`button button-secondary mode-switch-button ${isBeginnerMode ? "mode-switch-active" : ""}`}
            type="button"
            onClick={() => setMode("beginner")}
          >
            {bi("新手模式", "Beginner mode")}
          </button>
          <button
            className={`button button-secondary mode-switch-button ${!isBeginnerMode ? "mode-switch-active" : ""}`}
            type="button"
            onClick={() => setMode("advanced")}
          >
            {bi("高级模式", "Advanced mode")}
          </button>
        </div>
      </section>
      <div className="dashboard-columns">
        <div className="dashboard-column">
          <TaskCreator
            onCreated={() => {
              void loadTaskPage(1, true);
            }}
            workdirSuggestions={workdirSuggestions}
          />
          {!isBeginnerMode ? <ExecutorStatusBar /> : null}
          <MobileLoginApprovals enabled={authed} />
          {isBeginnerMode ? (
            <section className="panel animate-rise delay-1">
              <div className="panel-title-row">
                <h2 className="panel-title">{bi("新手引导", "Quick start")}</h2>
                <span className="chip">{bi("3 步", "3 steps")}</span>
              </div>
              <ol className="login-steps">
                <li>{bi("填写任务并点击“创建任务”。", "Fill a prompt and create the task.")}</li>
                <li>{bi("在任务列表点击任务进入详情。", "Open the task detail from the task list.")}</li>
                <li>{bi("需要手机授权时在本卡片允许登录。", "Approve phone login requests in this panel.")}</li>
              </ol>
            </section>
          ) : (
            <NotificationCenter events={events} />
          )}
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
                setTaskState({
                  total: 0,
                  limit: TASK_PAGE_SIZE,
                  offset: 0,
                  items: []
                });
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
          <div className={taskAuditClassName}>
            <TaskList
              tasks={sortedTasks}
              total={taskState.total}
              limit={taskState.limit || TASK_PAGE_SIZE}
              offset={taskState.offset}
              error={error}
              loading={taskLoading}
              onPageChange={(page) => {
                void loadTaskPage(page);
              }}
              onTaskMutated={() => {
                void loadTaskPage(taskPageRef.current, true);
              }}
            />
            {!isBeginnerMode ? (
              <AuditPanel
                logs={auditState.items}
                total={auditState.total}
                limit={auditState.limit || AUDIT_PAGE_SIZE}
                offset={auditState.offset}
                loading={auditLoading}
                filters={auditFilters}
                onFilterChange={(nextFilters) => {
                  const normalized = normalizeAuditFilters(nextFilters);
                  setAuditFilters(normalized);
                  void loadAuditPage(1, normalized);
                }}
                onPageChange={(page) => {
                  void loadAuditPage(page, auditFilters);
                }}
                onExport={(format) => {
                  void handleExportAudit(format);
                }}
              />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
