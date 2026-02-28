export type TaskStatus =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_INPUT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "TIMEOUT"
  | "RETRYING";

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
}

export interface CreateTaskInput {
  prompt: string;
  priority?: number;
  workdir?: string;
}

const DEFAULT_API_BASE_URL = "http://localhost:8000";
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_API_BASE_URL;

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object") {
    return value as Record<string, unknown>;
  }

  return {};
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const fallbackMessage = `HTTP ${response.status}: ${response.statusText}`;
    let message = fallbackMessage;

    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) {
        message = body.detail;
      }
    } catch {
      // Ignore invalid JSON and return fallback.
    }

    throw new Error(message);
  }

  return (await response.json()) as T;
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
      typeof value.last_heartbeat_at === "string" ? value.last_heartbeat_at : null
  };
}

export async function getTasks(status?: TaskStatus): Promise<Task[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks${query}`, {
    cache: "no-store"
  });
  const body = await parseJsonResponse<unknown>(response);

  if (Array.isArray(body)) {
    return body.map(normalizeTask);
  }

  const objectBody = asRecord(body);
  if (Array.isArray(objectBody.items)) {
    return objectBody.items.map(normalizeTask);
  }

  return [];
}

export async function getTask(taskId: string): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks/${taskId}`, {
    cache: "no-store"
  });
  const body = await parseJsonResponse<unknown>(response);

  return normalizeTask(body);
}

export async function createTask(input: CreateTaskInput): Promise<Task> {
  const response = await fetch(`${API_BASE_URL}/api/v1/tasks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(input)
  });

  const body = await parseJsonResponse<unknown>(response);
  return normalizeTask(body);
}
