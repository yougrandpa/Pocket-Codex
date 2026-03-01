"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { ContextWindowIndicator } from "@/components/context-window-indicator";
import {
  Task,
  TaskControlAction,
  TaskEvent,
  TaskEventStream,
  appendTaskMessage,
  controlTask,
  getTask,
  openEventStream
} from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi, statusText, useLanguage } from "@/lib/i18n";
import { formatTokenCompact, formatTokenDetailed, formatUsdDetailed } from "@/lib/usage";
import {
  consumeTaskNavigationContext,
  fireAndForgetUiEvent,
  resetTaskListClickCount
} from "@/lib/telemetry";

interface TaskDetailLiveProps {
  taskId: string;
}

const LOG_PAGE_SIZE = 20;
const LIFECYCLE_PAGE_SIZE = 20;
type TaskDetailTab = "conversation" | "controls" | "cost" | "events";

function mergeTaskFromStatus(task: Task, event: TaskEvent): Task {
  const next = { ...task };
  next.updated_at = event.timestamp;
  next.last_heartbeat_at = event.timestamp;
  if (event.event_type === "task.status.changed") {
    const to = event.payload.to;
    if (typeof to === "string") {
      next.status = to as Task["status"];
      if (to === "RUNNING" && !next.started_at) {
        next.started_at = event.timestamp;
      }
      if (["SUCCEEDED", "FAILED", "CANCELED", "TIMEOUT"].includes(to)) {
        next.finished_at = event.timestamp;
      }
    }
  }
  if (event.event_type === "task.summary.updated") {
    const summary = event.payload.summary;
    if (typeof summary === "string") {
      next.summary = summary;
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
        (next as Record<string, unknown>)[key] = value;
      }
    }
  }
  return next;
}

function controlActions(task: Task): TaskControlAction[] {
  if (task.status === "RUNNING") {
    return ["pause", "cancel"];
  }
  if (task.status === "WAITING_INPUT") {
    return ["resume", "cancel"];
  }
  if (["FAILED", "CANCELED", "TIMEOUT", "SUCCEEDED"].includes(task.status)) {
    return ["retry"];
  }
  return [];
}

function actionLabel(action: TaskControlAction): string {
  const map: Record<TaskControlAction, string> = {
    pause: bi("暂停", "pause"),
    resume: bi("继续", "resume"),
    cancel: bi("取消", "cancel"),
    retry: bi("重试", "retry")
  };
  return map[action];
}

function tabLabel(tab: TaskDetailTab): string {
  if (tab === "conversation") {
    return bi("对话", "Conversation");
  }
  if (tab === "controls") {
    return bi("控制", "Controls");
  }
  if (tab === "cost") {
    return bi("成本", "Cost");
  }
  return bi("事件日志", "Events");
}

const URL_PATTERN = /(https?:\/\/[^\s]+)/g;

interface ConversationTurn {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  timestamp?: string | null;
}

function renderInlineText(text: string): ReactNode[] {
  if (!text) {
    return [""];
  }
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  URL_PATTERN.lastIndex = 0;
  while ((match = URL_PATTERN.exec(text)) !== null) {
    const url = match[0];
    const start = match.index;
    if (start > lastIndex) {
      nodes.push(text.slice(lastIndex, start));
    }
    nodes.push(
      <a key={`${url}-${start}`} href={url} target="_blank" rel="noreferrer" className="rich-link">
        {url}
      </a>
    );
    lastIndex = start + url.length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function RichText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("- ")) {
      const items: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith("- ")) {
        items.push(lines[index].trim().slice(2));
        index += 1;
      }
      blocks.push(
        <ul key={`list-${index}`} className="rich-list">
          {items.map((item, itemIndex) => (
            <li key={`item-${itemIndex}`}>{renderInlineText(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    blocks.push(
      <p key={`line-${index}`} className="rich-line">
        {renderInlineText(line)}
      </p>
    );
    index += 1;
  }

  if (blocks.length === 0) {
    return <p className="rich-line">-</p>;
  }
  return <>{blocks}</>;
}

function roleLabel(role: ConversationTurn["role"]): string {
  if (role === "user") {
    return bi("你", "You");
  }
  if (role === "assistant") {
    return bi("助手", "Assistant");
  }
  return bi("系统", "System");
}

export function TaskDetailLive({ taskId }: TaskDetailLiveProps) {
  const [language] = useLanguage();
  const searchParams = useSearchParams();
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [logPage, setLogPage] = useState(1);
  const [lifecyclePage, setLifecyclePage] = useState(1);
  const [activeTab, setActiveTab] = useState<TaskDetailTab>("conversation");
  const [message, setMessage] = useState("");
  const [workingAction, setWorkingAction] = useState<TaskControlAction | null>(null);
  const [busyMessage, setBusyMessage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const hasTrackedOpenRef = useRef(false);
  const messageInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTask(taskId)
      .then((detail) => {
        if (cancelled) {
          return;
        }
        setTask(detail.task);
        setEvents(detail.events.slice().reverse());
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : bi("任务加载失败。", "Failed to load task.")
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  useEffect(() => {
    if (!task || hasTrackedOpenRef.current) {
      return;
    }
    hasTrackedOpenRef.current = true;
    const navigation = consumeTaskNavigationContext(task.id);
    fireAndForgetUiEvent(
      "task.detail.opened",
      {
        source: navigation.source,
        list_click_count: navigation.listClickCount
      },
      task.id
    );
    resetTaskListClickCount();
  }, [task]);

  useEffect(() => {
    let stream: TaskEventStream | null = null;
    try {
      stream = openEventStream({
        taskId,
        onEvent: (event) => {
          setEvents((previous) => [event, ...previous].slice(0, 400));
          setTask((previous) => (previous ? mergeTaskFromStatus(previous, event) : previous));
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
          : bi("实时流连接失败。", "Unable to open stream.")
      );
    }
    return () => {
      stream?.close();
    };
  }, [taskId]);

  const availableActions = useMemo(() => (task ? controlActions(task) : []), [task]);
  const logEvents = useMemo(
    () => events.filter((event) => event.event_type === "task.log.appended"),
    [events]
  );
  const timelineEvents = useMemo(
    () => events.filter((event) => event.event_type !== "task.log.appended"),
    [events]
  );
  const totalLogPages = Math.max(1, Math.ceil(logEvents.length / LOG_PAGE_SIZE));
  const totalLifecyclePages = Math.max(1, Math.ceil(timelineEvents.length / LIFECYCLE_PAGE_SIZE));
  const pagedLogEvents = useMemo(() => {
    const start = (logPage - 1) * LOG_PAGE_SIZE;
    return logEvents.slice(start, start + LOG_PAGE_SIZE);
  }, [logEvents, logPage]);
  const pagedLifecycleEvents = useMemo(() => {
    const start = (lifecyclePage - 1) * LIFECYCLE_PAGE_SIZE;
    return timelineEvents.slice(start, start + LIFECYCLE_PAGE_SIZE);
  }, [lifecyclePage, timelineEvents]);

  useEffect(() => {
    setLogPage(1);
    setLifecyclePage(1);
    setActiveTab("conversation");
    hasTrackedOpenRef.current = false;
  }, [taskId]);

  useEffect(() => {
    if (logPage > totalLogPages) {
      setLogPage(totalLogPages);
    }
  }, [logPage, totalLogPages]);

  useEffect(() => {
    if (lifecyclePage > totalLifecyclePages) {
      setLifecyclePage(totalLifecyclePages);
    }
  }, [lifecyclePage, totalLifecyclePages]);

  const backHref = useMemo(() => {
    const rawPage = searchParams.get("fromPage");
    if (!rawPage) {
      return "/";
    }
    const parsed = Number.parseInt(rawPage, 10);
    if (!Number.isFinite(parsed) || parsed <= 1) {
      return "/";
    }
    return `/?taskPage=${parsed}`;
  }, [searchParams]);

  const conversationTurns = useMemo<ConversationTurn[]>(() => {
    if (!task) {
      return [];
    }
    const turns: ConversationTurn[] = [
      {
        id: `${task.id}-prompt`,
        role: "user",
        text: task.prompt,
        timestamp: task.created_at
      }
    ];

    const orderedEvents = [...events].reverse();
    for (const event of orderedEvents) {
      if (event.event_type !== "task.message.appended") {
        continue;
      }
      const message = event.payload.message;
      if (typeof message !== "string" || !message.trim()) {
        continue;
      }
      turns.push({
        id: event.id,
        role: "user",
        text: message,
        timestamp: event.timestamp
      });
    }

    if (typeof task.summary === "string" && task.summary.trim()) {
      turns.push({
        id: `${task.id}-summary`,
        role: "assistant",
        text: task.summary,
        timestamp: task.updated_at
      });
    } else if (task.status === "RUNNING") {
      turns.push({
        id: `${task.id}-running`,
        role: "assistant",
        text: bi("正在处理你的消息，请稍候...", "Processing your message, please wait..."),
        timestamp: task.updated_at
      });
    }

    return turns;
  }, [events, task]);

  const showConversation = activeTab === "conversation";
  const showControls = activeTab === "controls";
  const showCost = activeTab === "cost";
  const showEvents = activeTab === "events";
  const primaryAction = availableActions[0] ?? null;

  function focusMessageComposer(): void {
    setActiveTab("conversation");
    window.setTimeout(() => {
      messageInputRef.current?.focus();
      messageInputRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);
  }

  async function handleControl(action: TaskControlAction): Promise<void> {
    setWorkingAction(action);
    setError(null);
    setNote(null);
    try {
      const result = await controlTask(taskId, action);
      setTask((previous) =>
        previous
          ? {
              ...previous,
              status: result.status,
              updated_at: new Date().toISOString()
            }
          : previous
      );
      setNote(result.message);
    } catch (controlError) {
      setError(
        controlError instanceof Error
          ? controlError.message
          : bi("控制动作执行失败。", "Control action failed.")
      );
    } finally {
      setWorkingAction(null);
    }
  }

  async function handleAppendMessage(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!message.trim()) {
      return;
    }
    setBusyMessage(true);
    setError(null);
    setNote(null);
    try {
      await appendTaskMessage(taskId, message.trim());
      setMessage("");
      setNote(bi("消息已发送。", "Message sent."));
    } catch (appendError) {
      setError(
        appendError instanceof Error
          ? appendError.message
          : bi("追加消息失败。", "Failed to append message.")
      );
    } finally {
      setBusyMessage(false);
    }
  }

  if (!task) {
    return (
      <section className="panel animate-rise">
        <h2 className="panel-title">{bi("任务不可用", "Task not available")}</h2>
        <p className="error">{error || bi("任务不存在。", "Task was not found.")}</p>
        <Link href={backHref} className="link" prefetch={false}>
          {bi("返回控制台", "Back to dashboard")}
        </Link>
      </section>
    );
  }

  return (
    <section className="panel animate-rise task-detail-panel" data-lang={language}>
      <Link href={backHref} prefetch={false} className="button button-secondary back-dashboard-button">
        {bi("返回控制台", "Back to dashboard")}
      </Link>

      <div className="panel-title-row">
        <h2 className="panel-title">{bi("任务详情", "Task Detail")}</h2>
        <div className="task-usage-row">
          <ContextWindowIndicator
            usedTokens={task.context_window_used_tokens}
            totalTokens={task.context_window_total_tokens}
          />
          <span className={`status status-${task.status.toLowerCase()}`}>{statusText(task.status)}</span>
        </div>
      </div>

      <div className="detail-tab-bar">
        {(["conversation", "controls", "cost", "events"] as TaskDetailTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`detail-tab ${activeTab === tab ? "detail-tab-active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tabLabel(tab)}
          </button>
        ))}
      </div>

      {error ? <p className="error">{error}</p> : null}
      {note ? <p className="note">{note}</p> : null}

      {showConversation ? (
        <>
          <section className="chat-panel">
            <h3>{bi("对话", "Conversation")}</h3>
            {conversationTurns.length === 0 ? (
              <p className="muted">{bi("暂无对话内容。", "No conversation yet.")}</p>
            ) : (
              <ul className="chat-list">
                {conversationTurns.map((turn) => (
                  <li key={turn.id} className={`chat-item chat-item-${turn.role}`}>
                    <div className="chat-meta">
                      <strong>{roleLabel(turn.role)}</strong>
                      <time dateTime={turn.timestamp || undefined}>{formatDateTime(turn.timestamp)}</time>
                    </div>
                    <div className="chat-body">
                      <RichText text={turn.text} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <form className="stack" onSubmit={handleAppendMessage}>
            <label className="field">
              <span>{bi("追加指令", "Append instruction")}</span>
              <textarea
                ref={messageInputRef}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={3}
                placeholder={bi("补充指令...", "Add follow-up instruction...")}
              />
            </label>
            <div className="mobile-sticky-actions">
              <button className="button" type="submit" disabled={busyMessage || !message.trim()}>
                {busyMessage ? bi("发送中...", "Sending...") : bi("发送消息", "Send Message")}
              </button>
            </div>
          </form>
        </>
      ) : null}

      {showControls ? (
        <>
          <div className="control-row">
            {availableActions.length === 0 ? (
              <p className="muted">
                {bi("当前状态没有可用控制动作。", "No control action available for current state.")}
              </p>
            ) : (
              availableActions.map((action) => (
                <button
                  key={action}
                  className="button button-secondary"
                  type="button"
                  disabled={workingAction !== null}
                  onClick={() => handleControl(action)}
                >
                  {workingAction === action ? bi("执行中...", "Working...") : actionLabel(action)}
                </button>
              ))
            )}
          </div>
          <dl className="meta-list">
            <div>
              <dt>{bi("任务 ID", "Task ID")}</dt>
              <dd>{task.id}</dd>
            </div>
            <div>
              <dt>{bi("优先级", "Priority")}</dt>
              <dd>{task.priority ?? "-"}</dd>
            </div>
            <div>
              <dt>{bi("超时", "Timeout")}</dt>
              <dd>{task.timeout_seconds ? `${task.timeout_seconds}s` : "-"}</dd>
            </div>
            <div>
              <dt>{bi("工作目录", "Workdir")}</dt>
              <dd>{task.workdir || "-"}</dd>
            </div>
            <div>
              <dt>{bi("模型", "Model")}</dt>
              <dd>{task.model || "-"}</dd>
            </div>
            <div>
              <dt>{bi("推理强度", "Reasoning Effort")}</dt>
              <dd>{task.reasoning_effort || "-"}</dd>
            </div>
            <div>
              <dt>{bi("并行多代理", "Parallel Multi-agent")}</dt>
              <dd>{task.enable_parallel_agents ? bi("启用", "Enabled") : bi("关闭", "Disabled")}</dd>
            </div>
            <div>
              <dt>{bi("当前运行", "Current Run")}</dt>
              <dd>{task.current_run_id ? `${task.current_run_id} (#${task.run_sequence ?? "-"})` : "-"}</dd>
            </div>
            <div>
              <dt>{bi("创建时间", "Created At")}</dt>
              <dd>{formatDateTime(task.created_at)}</dd>
            </div>
            <div>
              <dt>{bi("更新时间", "Updated At")}</dt>
              <dd>{formatDateTime(task.updated_at)}</dd>
            </div>
            <div>
              <dt>{bi("开始时间", "Started At")}</dt>
              <dd>{formatDateTime(task.started_at)}</dd>
            </div>
            <div>
              <dt>{bi("完成时间", "Finished At")}</dt>
              <dd>{formatDateTime(task.finished_at)}</dd>
            </div>
            <div>
              <dt>{bi("最后心跳", "Last Heartbeat")}</dt>
              <dd>{formatDateTime(task.last_heartbeat_at)}</dd>
            </div>
          </dl>
        </>
      ) : null}

      {showCost ? (
        <dl className="meta-list">
          <div>
            <dt>{bi("总 Tokens", "Total Tokens")}</dt>
            <dd>{formatTokenDetailed(task.total_tokens)}</dd>
          </div>
          <div>
            <dt>{bi("输入 Tokens", "Prompt Tokens")}</dt>
            <dd>{formatTokenDetailed(task.prompt_tokens)}</dd>
          </div>
          <div>
            <dt>{bi("输出 Tokens", "Completion Tokens")}</dt>
            <dd>{formatTokenDetailed(task.completion_tokens)}</dd>
          </div>
          <div>
            <dt>{bi("缓存读取 Tokens", "Cache Read Tokens")}</dt>
            <dd>{formatTokenDetailed(task.cache_read_tokens)}</dd>
          </div>
          <div>
            <dt>{bi("输入成本", "Input Cost")}</dt>
            <dd>{formatUsdDetailed(task.input_cost_usd)}</dd>
          </div>
          <div>
            <dt>{bi("输出成本", "Output Cost")}</dt>
            <dd>{formatUsdDetailed(task.output_cost_usd)}</dd>
          </div>
          <div>
            <dt>{bi("缓存读取成本", "Cache Read Cost")}</dt>
            <dd>{formatUsdDetailed(task.cache_read_cost_usd)}</dd>
          </div>
          <div>
            <dt>{bi("倍率", "Multiplier")}</dt>
            <dd>{typeof task.cost_multiplier === "number" ? `${task.cost_multiplier.toFixed(2)}x` : "1.00x"}</dd>
          </div>
          <div>
            <dt>{bi("原始成本", "Original Cost")}</dt>
            <dd>{formatUsdDetailed(task.original_cost_usd)}</dd>
          </div>
          <div>
            <dt>{bi("计费成本", "Billed Cost")}</dt>
            <dd>{formatUsdDetailed(task.billed_cost_usd)}</dd>
          </div>
          <div>
            <dt>{bi("累计花费", "Cost (USD)")}</dt>
            <dd>{formatUsdDetailed(task.cost_usd)}</dd>
          </div>
          <div>
            <dt>{bi("背景窗口", "Context Window")}</dt>
            <dd>
              {formatTokenCompact(task.context_window_used_tokens)} /{" "}
              {formatTokenCompact(task.context_window_total_tokens)}
            </dd>
          </div>
        </dl>
      ) : null}

      {showEvents ? (
        <>
          <section className="event-panel">
            <h3>{bi("状态事件", "Lifecycle Events")}</h3>
            {timelineEvents.length === 0 ? (
              <p className="muted">{bi("暂无状态事件。", "No lifecycle events yet.")}</p>
            ) : (
              <>
                <div className="pagination-row">
                  <p className="muted">
                    {bi("第", "Page")} {lifecyclePage} / {totalLifecyclePages} · {bi("共", "Total")}{" "}
                    {timelineEvents.length} {bi("条", "items")}
                  </p>
                  <div className="pagination-actions">
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={lifecyclePage <= 1}
                      onClick={() => setLifecyclePage((previous) => Math.max(1, previous - 1))}
                    >
                      {bi("上一页", "Previous")}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={lifecyclePage >= totalLifecyclePages}
                      onClick={() =>
                        setLifecyclePage((previous) => Math.min(totalLifecyclePages, previous + 1))
                      }
                    >
                      {bi("下一页", "Next")}
                    </button>
                  </div>
                </div>
                <ul className="notification-list">
                  {pagedLifecycleEvents.map((event) => (
                    <li key={`${event.id}-${event.seq}`} className="notification-item">
                      <div className="task-item-top">
                        <span className={`status status-${(event.status || "queued").toLowerCase()}`}>
                          {event.event_type}
                        </span>
                        <time dateTime={event.timestamp}>{formatDateTime(event.timestamp)}</time>
                      </div>
                      {typeof event.payload.run_id === "string" ? (
                        <p className="muted">
                          {bi("运行", "Run")}: {event.payload.run_id}
                        </p>
                      ) : null}
                      <code>{JSON.stringify(event.payload)}</code>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section className="event-panel">
            <h3>{bi("执行日志", "Execution Logs")}</h3>
            {logEvents.length === 0 ? (
              <p className="muted">{bi("暂无执行日志。", "No execution logs yet.")}</p>
            ) : (
              <>
                <div className="pagination-row">
                  <p className="muted">
                    {bi("第", "Page")} {logPage} / {totalLogPages} · {bi("共", "Total")} {logEvents.length}{" "}
                    {bi("条", "items")}
                  </p>
                  <div className="pagination-actions">
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={logPage <= 1}
                      onClick={() => setLogPage((previous) => Math.max(1, previous - 1))}
                    >
                      {bi("上一页", "Previous")}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={logPage >= totalLogPages}
                      onClick={() => setLogPage((previous) => Math.min(totalLogPages, previous + 1))}
                    >
                      {bi("下一页", "Next")}
                    </button>
                  </div>
                </div>
                <ul className="notification-list">
                  {pagedLogEvents.map((event) => {
                    const source =
                      typeof event.payload.source === "string" ? event.payload.source : bi("系统", "system");
                    const level =
                      typeof event.payload.level === "string" ? event.payload.level : bi("信息", "info");
                    const runId =
                      typeof event.payload.run_id === "string" ? event.payload.run_id : task.current_run_id;
                    const messageText =
                      typeof event.payload.message === "string"
                        ? event.payload.message
                        : JSON.stringify(event.payload);
                    return (
                      <li key={`${event.id}-${event.seq}`} className="notification-item">
                        <div className="task-item-top">
                          <span className="chip">
                            {source}
                            {runId ? ` · ${runId.slice(0, 8)}` : ""}
                          </span>
                          <time dateTime={event.timestamp}>{formatDateTime(event.timestamp)}</time>
                        </div>
                        <p className="muted">{bi("级别", "Level")}: {level}</p>
                        <code>{messageText}</code>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </section>
        </>
      ) : null}

      <div className="detail-bottom-dock">
        <button className="button button-secondary" type="button" onClick={() => setActiveTab("conversation")}>
          {bi("对话", "Chat")}
        </button>
        <button className="button button-secondary" type="button" onClick={() => setActiveTab("controls")}>
          {bi("控制", "Control")}
        </button>
        <button
          className="button button-secondary"
          type="button"
          disabled={primaryAction === null || workingAction !== null}
          onClick={() => {
            if (primaryAction) {
              void handleControl(primaryAction);
            }
          }}
        >
          {primaryAction ? actionLabel(primaryAction) : bi("无动作", "No action")}
        </button>
        <button className="button" type="button" onClick={focusMessageComposer}>
          {bi("发消息", "Message")}
        </button>
      </div>
    </section>
  );
}
