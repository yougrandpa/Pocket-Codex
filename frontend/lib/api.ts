import { bi } from "@/lib/i18n";

export type TaskStatus =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_INPUT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "TIMEOUT"
  | "RETRYING";

export type TaskControlAction = "pause" | "resume" | "cancel" | "retry";

export interface SessionTokens {
  accessToken: string;
  refreshToken: string;
  expiresInSeconds: number;
}

export interface Task {
  id: string;
  prompt: string;
  status: TaskStatus;
  priority?: number;
  workdir?: string | null;
  summary?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  last_heartbeat_at?: string | null;
  paused_at?: string | null;
  retry_count?: number;
  timeout_seconds?: number;
}

export interface TaskEvent {
  id: string;
  seq: number;
  task_id: string;
  event_type: string;
  status: TaskStatus | null;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface TaskDetail {
  task: Task;
  events: TaskEvent[];
}

export interface TaskControlResult {
  task_id: string;
  action: TaskControlAction;
  accepted: boolean;
  status: TaskStatus;
  message: string;
}

export interface AuditLog {
  id: number;
  timestamp: string;
  actor: string;
  action: string;
  task_id?: string | null;
  detail: Record<string, unknown>;
}

export interface HealthStatus {
  status: string;
  timestamp: string;
  task_executor: string;
  execution_backend: string;
  codex_min_timeout_seconds?: number;
  codex_hard_timeout_seconds?: number;
  codex_cli_path?: string;
  codex_cli_exists?: boolean;
}

export interface CreateTaskInput {
  prompt: string;
  priority?: number;
  timeout_seconds?: number;
  workdir?: string;
}

const DEFAULT_API_BASE_URL = "http://localhost:8000";
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_API_BASE_URL;
const SESSION_STORAGE_KEY = "pocket_codex_session";

interface ErrorPayload {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
  detail?: string;
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function parseErrorMessage(value: unknown, fallback: string): string {
  if (!value || typeof value !== "object") {
    return fallback;
  }
  const payload = value as ErrorPayload;
  if (payload.error?.message) {
    return payload.error.message;
  }
  if (payload.detail) {
    return payload.detail;
  }
  return fallback;
}

function parseSession(value: unknown): SessionTokens | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.accessToken !== "string" ||
    typeof record.refreshToken !== "string" ||
    typeof record.expiresInSeconds !== "number"
  ) {
    return null;
  }
  return {
    accessToken: record.accessToken,
    refreshToken: record.refreshToken,
    expiresInSeconds: record.expiresInSeconds
  };
}

export function readSession(): SessionTokens | null {
  if (!isBrowser()) {
    return null;
  }
  const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return parseSession(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function saveSession(tokens: SessionTokens): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(tokens));
}

export function clearSession(): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const fallback = `HTTP ${response.status}: ${response.statusText}`;
    let message = fallback;
    try {
      const body = (await response.json()) as ErrorPayload;
      message = parseErrorMessage(body, fallback);
    } catch {
      message = fallback;
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

interface RawTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in_seconds: number;
}

function normalizeToken(raw: RawTokenResponse): SessionTokens {
  return {
    accessToken: raw.access_token,
    refreshToken: raw.refresh_token,
    expiresInSeconds: raw.expires_in_seconds
  };
}

export async function login(username: string, password: string): Promise<SessionTokens> {
  const response = await fetchJson<RawTokenResponse>(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ username, password })
  });
  const tokens = normalizeToken(response);
  saveSession(tokens);
  return tokens;
}

async function refreshSession(refreshToken: string): Promise<SessionTokens> {
  const response = await fetchJson<RawTokenResponse>(`${API_BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  const tokens = normalizeToken(response);
  saveSession(tokens);
  return tokens;
}

async function authorizedFetchJson<T>(
  path: string,
  init: RequestInit = {},
  retried = false
): Promise<T> {
  const session = readSession();
  if (!session?.accessToken) {
    throw new Error(bi("请先登录。", "Please sign in first."));
  }

  const headers = new Headers(init.headers || {});
  headers.set("Authorization", `Bearer ${session.accessToken}`);

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

  if (response.status === 401 && !retried && session.refreshToken) {
    try {
      await refreshSession(session.refreshToken);
      return await authorizedFetchJson<T>(path, init, true);
    } catch {
      clearSession();
      throw new Error(bi("会话已过期，请重新登录。", "Session expired. Please sign in again."));
    }
  }

  if (!response.ok) {
    const fallback = `HTTP ${response.status}: ${response.statusText}`;
    let message = fallback;
    try {
      const body = (await response.json()) as ErrorPayload;
      message = parseErrorMessage(body, fallback);
    } catch {
      message = fallback;
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object") {
    return value as Record<string, unknown>;
  }
  return {};
}

function normalizeHealth(raw: unknown): HealthStatus {
  const value = asRecord(raw);
  return {
    status: typeof value.status === "string" ? value.status : "unknown",
    timestamp: typeof value.timestamp === "string" ? value.timestamp : "",
    task_executor: typeof value.task_executor === "string" ? value.task_executor : "unknown",
    execution_backend:
      typeof value.execution_backend === "string" ? value.execution_backend : "unknown",
    codex_min_timeout_seconds:
      typeof value.codex_min_timeout_seconds === "number"
        ? value.codex_min_timeout_seconds
        : undefined,
    codex_hard_timeout_seconds:
      typeof value.codex_hard_timeout_seconds === "number"
        ? value.codex_hard_timeout_seconds
        : undefined,
    codex_cli_path: typeof value.codex_cli_path === "string" ? value.codex_cli_path : undefined,
    codex_cli_exists:
      typeof value.codex_cli_exists === "boolean" ? value.codex_cli_exists : undefined
  };
}

function normalizeTask(raw: unknown): Task {
  const value = asRecord(raw);
  return {
    id: String(value.id ?? ""),
    prompt: String(value.prompt ?? ""),
    status: (value.status as TaskStatus) ?? "QUEUED",
    priority: typeof value.priority === "number" ? value.priority : undefined,
    workdir: typeof value.workdir === "string" ? value.workdir : null,
    summary: typeof value.summary === "string" ? value.summary : null,
    created_at: String(value.created_at ?? ""),
    updated_at: String(value.updated_at ?? ""),
    started_at: typeof value.started_at === "string" ? value.started_at : null,
    finished_at: typeof value.finished_at === "string" ? value.finished_at : null,
    last_heartbeat_at:
      typeof value.last_heartbeat_at === "string" ? value.last_heartbeat_at : null,
    paused_at: typeof value.paused_at === "string" ? value.paused_at : null,
    retry_count: typeof value.retry_count === "number" ? value.retry_count : undefined,
    timeout_seconds:
      typeof value.timeout_seconds === "number" ? value.timeout_seconds : undefined
  };
}

function normalizeEvent(raw: unknown): TaskEvent {
  const value = asRecord(raw);
  const payload = asRecord(value.payload);
  return {
    id: String(value.id ?? ""),
    seq: typeof value.seq === "number" ? value.seq : 0,
    task_id: String(value.task_id ?? ""),
    event_type: String(value.event_type ?? "task.event"),
    status: (value.status as TaskStatus | null) ?? null,
    timestamp: String(value.timestamp ?? ""),
    payload
  };
}

interface OpenEventStreamOptions {
  taskId?: string;
  onEvent: (event: TaskEvent) => void;
  onError?: (error: Error) => void;
}

export interface TaskEventStream {
  close: () => void;
}

export async function getTasks(status?: TaskStatus): Promise<Task[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const body = await authorizedFetchJson<{ items?: unknown[] }>(`/api/v1/tasks${query}`, {
    cache: "no-store"
  });
  const items = Array.isArray(body.items) ? body.items : [];
  return items.map(normalizeTask);
}

export async function getTask(taskId: string): Promise<TaskDetail> {
  const body = await authorizedFetchJson<{ task?: unknown; events?: unknown[] }>(
    `/api/v1/tasks/${taskId}`,
    { cache: "no-store" }
  );
  return {
    task: normalizeTask(body.task),
    events: Array.isArray(body.events) ? body.events.map(normalizeEvent) : []
  };
}

export async function createTask(input: CreateTaskInput): Promise<Task> {
  const body = await authorizedFetchJson<unknown>("/api/v1/tasks", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(input)
  });
  return normalizeTask(body);
}

export async function controlTask(taskId: string, action: TaskControlAction): Promise<TaskControlResult> {
  return await authorizedFetchJson<TaskControlResult>(`/api/v1/tasks/${taskId}/control`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ action })
  });
}

export async function appendTaskMessage(taskId: string, message: string): Promise<void> {
  await authorizedFetchJson(`/api/v1/tasks/${taskId}/message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ message })
  });
}

export async function getAuditLogs(limit = 20): Promise<AuditLog[]> {
  const body = await authorizedFetchJson<{ items?: AuditLog[] }>(
    `/api/v1/tasks/audit/logs?limit=${encodeURIComponent(String(limit))}`
  );
  return Array.isArray(body.items) ? body.items : [];
}

export async function getHealthStatus(): Promise<HealthStatus> {
  const body = await fetchJson<unknown>(`${API_BASE_URL}/healthz`, { cache: "no-store" });
  return normalizeHealth(body);
}

function parseSseFrame(frame: string): string | null {
  const lines = frame.split(/\r?\n/);
  const dataLines: string[] = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  const payload = dataLines.join("\n").trim();
  return payload || null;
}

export function bindTaskEventStream(onEvent: (event: TaskEvent) => void): (rawData: string) => void {
  return (rawData: string) => {
    try {
      const parsed = JSON.parse(rawData) as unknown;
      onEvent(normalizeEvent(parsed));
    } catch {
      // Ignore malformed event payload.
    }
  };
}

export function openEventStream({
  taskId,
  onEvent,
  onError
}: OpenEventStreamOptions): TaskEventStream {
  let closed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;
  let reconnectAttempts = 0;
  const consume = bindTaskEventStream(onEvent);

  const scheduleReconnect = (immediate = false) => {
    if (closed) {
      return;
    }
    const delay = immediate ? 0 : Math.min(10_000, 800 * 2 ** reconnectAttempts);
    reconnectAttempts = Math.min(reconnectAttempts + 1, 8);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void connect();
    }, delay);
  };

  const connect = async () => {
    if (closed) {
      return;
    }
    const session = readSession();
    if (!session?.accessToken) {
      onError?.(new Error(bi("请先登录。", "Please sign in first.")));
      return;
    }

    controller = new AbortController();
    const params = new URLSearchParams();
    if (taskId) {
      params.set("task_id", taskId);
    }
    const query = params.toString();
    const endpoint = `${API_BASE_URL}/api/v1/stream${query ? `?${query}` : ""}`;

    try {
      const response = await fetch(endpoint, {
        method: "GET",
        headers: {
          Accept: "text/event-stream",
          Authorization: `Bearer ${session.accessToken}`
        },
        cache: "no-store",
        signal: controller.signal
      });

      if (response.status === 401 && session.refreshToken) {
        try {
          await refreshSession(session.refreshToken);
          reconnectAttempts = 0;
          scheduleReconnect(true);
          return;
        } catch {
          clearSession();
          onError?.(new Error(bi("会话已过期，请重新登录。", "Session expired. Please sign in again.")));
          return;
        }
      }

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      reconnectAttempts = 0;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!closed) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const payload = parseSseFrame(frame);
          if (payload) {
            consume(payload);
          }
        }
      }

      if (!closed) {
        onError?.(
          new Error(
            bi(
              "实时流已断开，正在自动重连...",
              "Realtime stream disconnected. Retrying automatically..."
            )
          )
        );
        scheduleReconnect();
      }
    } catch (error) {
      if (closed) {
        return;
      }
      const err = error instanceof Error ? error : new Error("Unknown stream error");
      if (err.name === "AbortError") {
        return;
      }
      onError?.(err);
      scheduleReconnect();
    }
  };

  scheduleReconnect(true);

  return {
    close: () => {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      controller?.abort();
    }
  };
}
