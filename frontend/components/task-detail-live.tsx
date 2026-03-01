"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Task,
  TaskControlAction,
  TaskEvent,
  appendTaskMessage,
  controlTask,
  getTask,
  openEventStream
} from "@/lib/api";
import { bi, statusText } from "@/lib/i18n";

interface TaskDetailLiveProps {
  taskId: string;
}

function formatValue(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return date.toLocaleString();
}

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
  return next;
}

function controlActions(task: Task): TaskControlAction[] {
  if (task.status === "RUNNING") {
    return ["pause", "cancel"];
  }
  if (task.status === "WAITING_INPUT") {
    return ["resume", "cancel"];
  }
  if (["FAILED", "CANCELED", "TIMEOUT"].includes(task.status)) {
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

export function TaskDetailLive({ taskId }: TaskDetailLiveProps) {
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [message, setMessage] = useState("");
  const [workingAction, setWorkingAction] = useState<TaskControlAction | null>(null);
  const [busyMessage, setBusyMessage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

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
    let source: EventSource | null = null;
    try {
      source = openEventStream(taskId);
      const consume = (messageEvent: MessageEvent<string>) => {
        try {
          const event = JSON.parse(messageEvent.data) as TaskEvent;
          setEvents((previous) => [event, ...previous].slice(0, 100));
          setTask((previous) => (previous ? mergeTaskFromStatus(previous, event) : previous));
        } catch {
          // Ignore invalid frames.
        }
      };
      source.onmessage = consume;
      source.addEventListener("task.status.changed", consume as EventListener);
      source.addEventListener("task.log.appended", consume as EventListener);
      source.addEventListener("task.message.appended", consume as EventListener);
      source.addEventListener("task.summary.updated", consume as EventListener);
      source.onerror = () => {
        setError(bi("实时流已断开，正在自动重连...", "Realtime stream disconnected. Retrying automatically..."));
      };
    } catch (streamError) {
      setError(
        streamError instanceof Error
          ? streamError.message
          : bi("实时流连接失败。", "Unable to open stream.")
      );
    }
    return () => {
      source?.close();
    };
  }, [taskId]);

  const availableActions = useMemo(() => (task ? controlActions(task) : []), [task]);

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
        <Link href="/" className="link">
          {bi("返回控制台", "Back to dashboard")}
        </Link>
      </section>
    );
  }

  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("任务详情", "Task Detail")}</h2>
        <span className={`status status-${task.status.toLowerCase()}`}>{statusText(task.status)}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {note ? <p className="note">{note}</p> : null}

      <div className="detail-grid">
        <div className="detail-block">
          <h3>{bi("任务指令", "Prompt")}</h3>
          <p>{task.prompt}</p>
        </div>
        <div className="detail-block">
          <h3>{bi("任务摘要", "Summary")}</h3>
          <p>{task.summary || bi("暂无摘要。", "No summary yet.")}</p>
        </div>
      </div>

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

      <form className="stack" onSubmit={handleAppendMessage}>
        <label className="field">
          <span>{bi("追加指令", "Append instruction")}</span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={3}
            placeholder="补充指令..."
          />
        </label>
        <button className="button" type="submit" disabled={busyMessage || !message.trim()}>
          {busyMessage ? bi("发送中...", "Sending...") : bi("发送消息", "Send Message")}
        </button>
      </form>

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
          <dt>{bi("创建时间", "Created At")}</dt>
          <dd>{formatValue(task.created_at)}</dd>
        </div>
        <div>
          <dt>{bi("更新时间", "Updated At")}</dt>
          <dd>{formatValue(task.updated_at)}</dd>
        </div>
        <div>
          <dt>{bi("开始时间", "Started At")}</dt>
          <dd>{formatValue(task.started_at)}</dd>
        </div>
        <div>
          <dt>{bi("完成时间", "Finished At")}</dt>
          <dd>{formatValue(task.finished_at)}</dd>
        </div>
        <div>
          <dt>{bi("最后心跳", "Last Heartbeat")}</dt>
          <dd>{formatValue(task.last_heartbeat_at)}</dd>
        </div>
      </dl>

      <section className="event-panel">
        <h3>{bi("最近事件", "Recent Events")}</h3>
        {events.length === 0 ? (
          <p className="muted">{bi("暂无事件。", "No events yet.")}</p>
        ) : (
          <ul className="notification-list">
            {events.map((event) => (
              <li key={`${event.id}-${event.seq}`} className="notification-item">
                <div className="task-item-top">
                  <span className={`status status-${(event.status || "queued").toLowerCase()}`}>
                    {event.event_type}
                  </span>
                  <time dateTime={event.timestamp}>{formatValue(event.timestamp)}</time>
                </div>
                <code>{JSON.stringify(event.payload)}</code>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link href="/" className="link">
        {bi("返回控制台", "Back to dashboard")}
      </Link>
    </section>
  );
}
