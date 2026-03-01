"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { createTask, Task } from "@/lib/api";
import { bi } from "@/lib/i18n";
import { resetTaskListClickCount, setTaskNavigationContext } from "@/lib/telemetry";

const DEFAULT_PRIORITY = 5;
const DEFAULT_TIMEOUT_SECONDS = 180;
const WORKDIR_HISTORY_KEY = "pocket_codex_workdir_history";
const MAX_WORKDIR_HISTORY = 30;

interface TaskCreatorProps {
  onCreated?: (task: Task) => void;
  workdirSuggestions?: string[];
}

function normalizeWorkdirList(items: string[]): string[] {
  return Array.from(new Set(items.map((item) => item.trim()).filter((item) => item.length > 0)));
}

export function TaskCreator({ onCreated, workdirSuggestions = [] }: TaskCreatorProps) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [priority, setPriority] = useState(DEFAULT_PRIORITY);
  const [timeoutSeconds, setTimeoutSeconds] = useState(DEFAULT_TIMEOUT_SECONDS);
  const [workdir, setWorkdir] = useState("");
  const [workdirHistory, setWorkdirHistory] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = window.localStorage.getItem(WORKDIR_HISTORY_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return;
      }
      const loaded = normalizeWorkdirList(
        parsed.filter((item): item is string => typeof item === "string")
      ).slice(0, MAX_WORKDIR_HISTORY);
      setWorkdirHistory(loaded);
    } catch {
      // Ignore malformed history payload.
    }
  }, []);

  const disabled = useMemo(() => {
    return submitting || prompt.trim().length === 0;
  }, [submitting, prompt]);

  const mergedWorkdirOptions = useMemo(() => {
    return normalizeWorkdirList([...workdirHistory, ...workdirSuggestions]).slice(0, MAX_WORKDIR_HISTORY);
  }, [workdirHistory, workdirSuggestions]);

  function saveWorkdirHistory(nextWorkdir: string): void {
    const trimmed = nextWorkdir.trim();
    if (!trimmed || typeof window === "undefined") {
      return;
    }
    const next = normalizeWorkdirList([trimmed, ...workdirHistory]).slice(0, MAX_WORKDIR_HISTORY);
    setWorkdirHistory(next);
    window.localStorage.setItem(WORKDIR_HISTORY_KEY, JSON.stringify(next));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (disabled) {
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const created = await createTask({
        prompt: prompt.trim(),
        priority,
        timeout_seconds: timeoutSeconds,
        workdir: workdir.trim() || undefined
      });

      const savedWorkdir = created.workdir || workdir.trim();
      if (savedWorkdir) {
        saveWorkdirHistory(savedWorkdir);
      }
      setTaskNavigationContext(created.id, "create", 0);
      resetTaskListClickCount();
      setPrompt("");
      setWorkdir("");
      onCreated?.(created);
      router.push(`/tasks/${created.id}`);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : bi("创建任务失败。", "Failed to create task.")
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel animate-rise" id="create-task-panel">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("创建任务", "Create Task")}</h2>
        <span className="chip">{bi("移动优先", "Mobile First")}</span>
      </div>
      <form className="stack" onSubmit={handleSubmit}>
        <label className="field">
          <span>{bi("任务指令", "Prompt")}</span>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={4}
            placeholder={bi("请输入可执行的任务指令...", "Ask Codex to do something actionable...")}
            required
          />
        </label>

        <div className="row">
          <label className="field">
            <span>{bi("优先级", "Priority")}</span>
            <input
              type="number"
              min={1}
              max={10}
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value) || DEFAULT_PRIORITY)}
            />
          </label>
          <label className="field">
            <span>{bi("超时(秒)", "Timeout (sec)")}</span>
            <input
              type="number"
              min={5}
              max={3600}
              value={timeoutSeconds}
              onChange={(event) => setTimeoutSeconds(Number(event.target.value) || DEFAULT_TIMEOUT_SECONDS)}
            />
          </label>
        </div>

        <div className="row">
          <label className="field">
            <span>{bi("历史目录快速选择", "Quick pick from history")}</span>
            <select
              defaultValue=""
              disabled={mergedWorkdirOptions.length === 0}
              onChange={(event) => {
                const selected = event.target.value;
                if (selected) {
                  setWorkdir(selected);
                }
              }}
            >
              <option value="">
                {mergedWorkdirOptions.length > 0
                  ? bi("请选择历史工作目录", "Select a previous workdir")
                  : bi("暂无历史目录", "No workdir history yet")}
              </option>
              {mergedWorkdirOptions.map((path) => (
                <option key={path} value={path}>
                  {path}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{bi("工作目录(可选)", "Workdir (optional)")}</span>
            <input
              type="text"
              value={workdir}
              onChange={(event) => setWorkdir(event.target.value)}
              list="workdir-history-options"
              placeholder="/Users/slg/workspace/Pocket-Codex"
            />
            <datalist id="workdir-history-options">
              {mergedWorkdirOptions.map((path) => (
                <option key={`hint-${path}`} value={path} />
              ))}
            </datalist>
          </label>
        </div>

        {error ? <p className="error">{error}</p> : null}

        <div className="mobile-sticky-actions">
          <button className="button" type="submit" disabled={disabled}>
            {submitting ? bi("创建中...", "Creating...") : bi("创建任务", "Create Task")}
          </button>
        </div>
      </form>
    </section>
  );
}
