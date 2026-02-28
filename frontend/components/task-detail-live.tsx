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
          setError(requestError instanceof Error ? requestError.message : "Failed to load task.");
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
        setError("Realtime stream disconnected. Retrying automatically...");
      };
    } catch (streamError) {
      setError(streamError instanceof Error ? streamError.message : "Unable to open stream.");
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
      setError(controlError instanceof Error ? controlError.message : "Control action failed.");
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
      setNote("Message sent.");
    } catch (appendError) {
      setError(appendError instanceof Error ? appendError.message : "Failed to append message.");
    } finally {
      setBusyMessage(false);
    }
  }

  if (!task) {
    return (
      <section className="panel animate-rise">
        <h2 className="panel-title">Task not available</h2>
        <p className="error">{error || "Task was not found."}</p>
        <Link href="/" className="link">
          Back to dashboard
        </Link>
      </section>
    );
  }

  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">Task Detail</h2>
        <span className={`status status-${task.status.toLowerCase()}`}>{task.status}</span>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {note ? <p className="note">{note}</p> : null}

      <div className="detail-grid">
        <div className="detail-block">
          <h3>Prompt</h3>
          <p>{task.prompt}</p>
        </div>
        <div className="detail-block">
          <h3>Summary</h3>
          <p>{task.summary || "No summary yet."}</p>
        </div>
      </div>

      <div className="control-row">
        {availableActions.length === 0 ? (
          <p className="muted">No control action available for current state.</p>
        ) : (
          availableActions.map((action) => (
            <button
              key={action}
              className="button button-secondary"
              type="button"
              disabled={workingAction !== null}
              onClick={() => handleControl(action)}
            >
              {workingAction === action ? "Working..." : action}
            </button>
          ))
        )}
      </div>

      <form className="stack" onSubmit={handleAppendMessage}>
        <label className="field">
          <span>Append instruction</span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={3}
            placeholder="补充指令..."
          />
        </label>
        <button className="button" type="submit" disabled={busyMessage || !message.trim()}>
          {busyMessage ? "Sending..." : "Send Message"}
        </button>
      </form>

      <dl className="meta-list">
        <div>
          <dt>Task ID</dt>
          <dd>{task.id}</dd>
        </div>
        <div>
          <dt>Priority</dt>
          <dd>{task.priority ?? "-"}</dd>
        </div>
        <div>
          <dt>Timeout</dt>
          <dd>{task.timeout_seconds ? `${task.timeout_seconds}s` : "-"}</dd>
        </div>
        <div>
          <dt>Workdir</dt>
          <dd>{task.workdir || "-"}</dd>
        </div>
        <div>
          <dt>Created At</dt>
          <dd>{formatValue(task.created_at)}</dd>
        </div>
        <div>
          <dt>Updated At</dt>
          <dd>{formatValue(task.updated_at)}</dd>
        </div>
        <div>
          <dt>Started At</dt>
          <dd>{formatValue(task.started_at)}</dd>
        </div>
        <div>
          <dt>Finished At</dt>
          <dd>{formatValue(task.finished_at)}</dd>
        </div>
        <div>
          <dt>Last Heartbeat</dt>
          <dd>{formatValue(task.last_heartbeat_at)}</dd>
        </div>
      </dl>

      <section className="event-panel">
        <h3>Recent Events</h3>
        {events.length === 0 ? (
          <p className="muted">No events yet.</p>
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
        Back to dashboard
      </Link>
    </section>
  );
}
