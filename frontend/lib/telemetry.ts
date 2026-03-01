import { trackUiEvent } from "@/lib/api";

const TASK_NAV_CONTEXT_KEY = "pocket_codex_task_nav_context";
const TASK_LIST_CLICK_COUNT_KEY = "pocket_codex_task_list_click_count";

type TaskNavSource = "list" | "create" | "unknown";

interface TaskNavigationContext {
  task_id: string;
  source: TaskNavSource;
  list_click_count: number;
  created_at_ms: number;
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function setTaskNavigationContext(taskId: string, source: TaskNavSource, listClickCount: number): void {
  if (!isBrowser()) {
    return;
  }
  const context: TaskNavigationContext = {
    task_id: taskId,
    source,
    list_click_count: Math.max(0, Math.floor(listClickCount)),
    created_at_ms: Date.now()
  };
  window.sessionStorage.setItem(TASK_NAV_CONTEXT_KEY, JSON.stringify(context));
}

export function consumeTaskNavigationContext(taskId: string): {
  source: TaskNavSource;
  listClickCount: number;
} {
  if (!isBrowser()) {
    return { source: "unknown", listClickCount: 0 };
  }
  const raw = window.sessionStorage.getItem(TASK_NAV_CONTEXT_KEY);
  window.sessionStorage.removeItem(TASK_NAV_CONTEXT_KEY);
  if (!raw) {
    return { source: "unknown", listClickCount: 0 };
  }
  try {
    const parsed = JSON.parse(raw) as TaskNavigationContext;
    if (!parsed || parsed.task_id !== taskId) {
      return { source: "unknown", listClickCount: 0 };
    }
    const ageMs = Date.now() - Number(parsed.created_at_ms || 0);
    if (ageMs < 0 || ageMs > 10 * 60 * 1000) {
      return { source: "unknown", listClickCount: 0 };
    }
    return {
      source: parsed.source || "unknown",
      listClickCount: Math.max(0, Math.floor(parsed.list_click_count || 0))
    };
  } catch {
    return { source: "unknown", listClickCount: 0 };
  }
}

export function nextTaskListClickCount(): number {
  if (!isBrowser()) {
    return 1;
  }
  const raw = window.sessionStorage.getItem(TASK_LIST_CLICK_COUNT_KEY);
  const current = Number.parseInt(raw || "0", 10);
  const next = Number.isFinite(current) ? current + 1 : 1;
  window.sessionStorage.setItem(TASK_LIST_CLICK_COUNT_KEY, String(next));
  return next;
}

export function resetTaskListClickCount(): void {
  if (!isBrowser()) {
    return;
  }
  window.sessionStorage.setItem(TASK_LIST_CLICK_COUNT_KEY, "0");
}

export function fireAndForgetUiEvent(
  eventName: string,
  detail: Record<string, unknown> = {},
  taskId?: string
): void {
  void trackUiEvent(eventName, detail, taskId).catch(() => {
    // Intentionally ignored: telemetry should never block user flow.
  });
}
