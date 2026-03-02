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
  model?: string | null;
  reasoning_effort?: string | null;
  enable_parallel_agents?: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
  cache_read_tokens?: number;
  total_tokens?: number;
  input_cost_usd?: number;
  output_cost_usd?: number;
  cache_read_cost_usd?: number;
  cost_multiplier?: number;
  original_cost_usd?: number;
  billed_cost_usd?: number;
  cost_usd?: number;
  context_window_used_tokens?: number | null;
  context_window_total_tokens?: number | null;
  current_run_id?: string | null;
  run_sequence?: number;
}

export interface TaskEvent {
  id: string;
  stream_id?: number;
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

export interface TaskListResult {
  total: number;
  limit: number;
  offset: number;
  items: Task[];
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

export interface AuditLogList {
  total: number;
  limit: number;
  offset: number;
  items: AuditLog[];
}

export interface AuditLogFilters {
  actor?: string;
  task_id?: string;
  action?: string;
}

export type MobileLoginRequestStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "CANCELED"
  | "EXPIRED"
  | "COMPLETED";

export interface MobileLoginRequestResult {
  request_id: string;
  request_token: string;
  status: MobileLoginRequestStatus;
  expires_at: string;
  poll_interval_seconds: number;
}

export interface MobileLoginStatus {
  request_id: string;
  status: MobileLoginRequestStatus;
  device_name: string;
  request_ip: string;
  created_at: string;
  expires_at: string;
  approved_at?: string | null;
  approved_by?: string | null;
  completed_at?: string | null;
  access_token?: string | null;
  refresh_token?: string | null;
  expires_in_seconds?: number | null;
}

export interface PendingMobileLoginRequest {
  request_id: string;
  status: MobileLoginRequestStatus;
  username: string;
  device_name: string;
  request_ip: string;
  created_at: string;
  expires_at: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  risk_reasons: string[];
  known_device: boolean;
  known_ip: boolean;
  device_approval_count: number;
  device_last_approved_at?: string | null;
  ip_seen_count: number;
  ip_last_seen_at?: string | null;
  ip_risk_level: "LOW" | "MEDIUM" | "HIGH";
}

export interface HealthStatus {
  status: string;
  timestamp: string;
  task_executor: string;
  execution_backend: string;
  worker_concurrency?: number;
  sse_replay_limit?: number;
  workdir_whitelist?: string[];
  codex_min_timeout_seconds?: number;
  codex_hard_timeout_seconds?: number;
  codex_cli_path?: string;
  codex_cli_exists?: boolean;
  require_loopback_direct_login?: boolean;
  mobile_login_request_ttl_seconds?: number;
}

export interface CreateTaskInput {
  prompt: string;
  priority?: number;
  timeout_seconds?: number;
  workdir?: string;
  model?: string;
  reasoning_effort?: string;
  enable_parallel_agents?: boolean;
}

export interface ExecutorCapability {
  source: string;
  model_options: string[];
  reasoning_effort_options: string[];
  supports_parallel_agents: boolean;
}

const API_BASE_URL = "";
const SESSION_STORAGE_KEY = "pocket_codex_session";
const LEGACY_LOCAL_STORAGE_KEY = "pocket_codex_session";
let inMemorySession: SessionTokens | null = null;
const DIRECT_LOGIN_LOOPBACK_HINT = "Direct login is only allowed from localhost";
const REQUEST_TIMEOUT_MS = 20_000;

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

function isLoopbackHostname(value: string): boolean {
  const hostname = value.trim().toLowerCase();
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1" || hostname === "[::1]";
}

function getLoopbackBackendApiBase(): string | null {
  if (!isBrowser()) {
    return null;
  }
  if (!isLoopbackHostname(window.location.hostname)) {
    return null;
  }
  return "http://127.0.0.1:8000";
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
  if (inMemorySession) {
    return inMemorySession;
  }
  if (!isBrowser()) {
    return null;
  }
  const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (raw) {
    try {
      const parsed = parseSession(JSON.parse(raw));
      if (parsed) {
        inMemorySession = parsed;
      }
      return parsed;
    } catch {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }
  }

  const legacyRaw = window.localStorage.getItem(LEGACY_LOCAL_STORAGE_KEY);
  if (!legacyRaw) {
    return null;
  }
  try {
    const parsed = parseSession(JSON.parse(legacyRaw));
    if (parsed) {
      inMemorySession = parsed;
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(parsed));
      window.localStorage.removeItem(LEGACY_LOCAL_STORAGE_KEY);
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveSession(tokens: SessionTokens): void {
  inMemorySession = tokens;
  if (!isBrowser()) {
    return;
  }
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(tokens));
  window.localStorage.removeItem(LEGACY_LOCAL_STORAGE_KEY);
}

export function clearSession(): void {
  inMemorySession = null;
  if (!isBrowser()) {
    return;
  }
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  window.localStorage.removeItem(LEGACY_LOCAL_STORAGE_KEY);
}

interface JsonRequestInit extends RequestInit {
  timeoutMs?: number;
}

function normalizeFetchFailure(error: unknown): Error {
  if (error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")) {
    return new Error(
      bi("请求超时，请检查网络后重试。", "Request timed out. Please check your network and retry.")
    );
  }
  if (error instanceof TypeError) {
    return new Error(
      bi(
        "网络连接失败，请确认后端服务已启动并可访问。",
        "Network request failed. Ensure backend service is running and reachable."
      )
    );
  }
  return error instanceof Error ? error : new Error(bi("请求失败。", "Request failed."));
}

async function fetchJson<T>(input: RequestInfo, init: JsonRequestInit = {}): Promise<T> {
  const { timeoutMs = REQUEST_TIMEOUT_MS, signal, ...requestInit } = init;
  const controller = new AbortController();
  let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  const abortFromOuterSignal = () => controller.abort(signal?.reason);

  if (signal?.aborted) {
    controller.abort(signal.reason);
  } else if (signal) {
    signal.addEventListener("abort", abortFromOuterSignal, { once: true });
  }
  if (timeoutMs > 0) {
    timeoutHandle = setTimeout(() => {
      controller.abort(new DOMException("timeout", "TimeoutError"));
    }, timeoutMs);
  }

  let response: Response;
  try {
    response = await fetch(input, {
      ...requestInit,
      signal: controller.signal
    });
  } catch (error) {
    throw normalizeFetchFailure(error);
  } finally {
    if (timeoutHandle) {
      clearTimeout(timeoutHandle);
    }
    signal?.removeEventListener("abort", abortFromOuterSignal);
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

interface RawTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in_seconds: number;
}

interface RawMobileLoginRequestResult {
  request_id: string;
  request_token: string;
  status: MobileLoginRequestStatus;
  expires_at: string;
  poll_interval_seconds: number;
}

interface RawMobileLoginStatus {
  request_id: string;
  status: MobileLoginRequestStatus;
  device_name: string;
  request_ip: string;
  created_at: string;
  expires_at: string;
  approved_at?: string | null;
  approved_by?: string | null;
  completed_at?: string | null;
  access_token?: string | null;
  refresh_token?: string | null;
  expires_in_seconds?: number | null;
}

function normalizeToken(raw: RawTokenResponse): SessionTokens {
  return {
    accessToken: raw.access_token,
    refreshToken: raw.refresh_token,
    expiresInSeconds: raw.expires_in_seconds
  };
}

function normalizeMobileLoginStatus(raw: RawMobileLoginStatus): MobileLoginStatus {
  return {
    request_id: raw.request_id,
    status: raw.status,
    device_name: raw.device_name,
    request_ip: raw.request_ip,
    created_at: raw.created_at,
    expires_at: raw.expires_at,
    approved_at: raw.approved_at ?? null,
    approved_by: raw.approved_by ?? null,
    completed_at: raw.completed_at ?? null,
    access_token: raw.access_token ?? null,
    refresh_token: raw.refresh_token ?? null,
    expires_in_seconds: raw.expires_in_seconds ?? null
  };
}

export async function login(username: string, password: string): Promise<SessionTokens> {
  const payload = JSON.stringify({ username, password });

  const tryLogin = async (endpoint: string): Promise<SessionTokens> => {
    const response = await fetchJson<RawTokenResponse>(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: payload
    });
    const tokens = normalizeToken(response);
    saveSession(tokens);
    return tokens;
  };

  try {
    return await tryLogin(`${API_BASE_URL}/api/v1/auth/login`);
  } catch (error) {
    const fallbackBase = getLoopbackBackendApiBase();
    if (
      !(error instanceof Error) ||
      !fallbackBase ||
      !error.message.includes(DIRECT_LOGIN_LOOPBACK_HINT)
    ) {
      throw error;
    }
    return await tryLogin(`${fallbackBase}/api/v1/auth/login`);
  }
}

export async function requestMobileLogin(
  username: string,
  password: string,
  deviceName: string
): Promise<MobileLoginRequestResult> {
  return await fetchJson<RawMobileLoginRequestResult>(`${API_BASE_URL}/api/v1/auth/mobile/request`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      username,
      password,
      device_name: deviceName
    })
  });
}

export async function getMobileLoginStatus(
  requestId: string,
  requestToken: string
): Promise<MobileLoginStatus> {
  const response = await fetchJson<RawMobileLoginStatus>(
    `${API_BASE_URL}/api/v1/auth/mobile/requests/${encodeURIComponent(requestId)}`,
    {
      cache: "no-store",
      headers: {
        "X-Mobile-Request-Token": requestToken
      }
    }
  );
  const normalized = normalizeMobileLoginStatus(response);
  if (
    normalized.access_token &&
    normalized.refresh_token &&
    typeof normalized.expires_in_seconds === "number"
  ) {
    saveSession({
      accessToken: normalized.access_token,
      refreshToken: normalized.refresh_token,
      expiresInSeconds: normalized.expires_in_seconds
    });
  }
  return normalized;
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
    worker_concurrency:
      typeof value.worker_concurrency === "number" ? value.worker_concurrency : undefined,
    sse_replay_limit:
      typeof value.sse_replay_limit === "number" ? value.sse_replay_limit : undefined,
    workdir_whitelist: Array.isArray(value.workdir_whitelist)
      ? value.workdir_whitelist.filter((item): item is string => typeof item === "string")
      : undefined,
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
      typeof value.codex_cli_exists === "boolean" ? value.codex_cli_exists : undefined,
    require_loopback_direct_login:
      typeof value.require_loopback_direct_login === "boolean"
        ? value.require_loopback_direct_login
        : undefined,
    mobile_login_request_ttl_seconds:
      typeof value.mobile_login_request_ttl_seconds === "number"
        ? value.mobile_login_request_ttl_seconds
        : undefined
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
      typeof value.timeout_seconds === "number" ? value.timeout_seconds : undefined,
    model: typeof value.model === "string" ? value.model : null,
    reasoning_effort: typeof value.reasoning_effort === "string" ? value.reasoning_effort : null,
    enable_parallel_agents:
      typeof value.enable_parallel_agents === "boolean" ? value.enable_parallel_agents : false,
    prompt_tokens: typeof value.prompt_tokens === "number" ? value.prompt_tokens : 0,
    completion_tokens: typeof value.completion_tokens === "number" ? value.completion_tokens : 0,
    cache_read_tokens: typeof value.cache_read_tokens === "number" ? value.cache_read_tokens : 0,
    total_tokens: typeof value.total_tokens === "number" ? value.total_tokens : 0,
    input_cost_usd: typeof value.input_cost_usd === "number" ? value.input_cost_usd : 0,
    output_cost_usd: typeof value.output_cost_usd === "number" ? value.output_cost_usd : 0,
    cache_read_cost_usd:
      typeof value.cache_read_cost_usd === "number" ? value.cache_read_cost_usd : 0,
    cost_multiplier: typeof value.cost_multiplier === "number" ? value.cost_multiplier : 1,
    original_cost_usd: typeof value.original_cost_usd === "number" ? value.original_cost_usd : 0,
    billed_cost_usd: typeof value.billed_cost_usd === "number" ? value.billed_cost_usd : 0,
    cost_usd: typeof value.cost_usd === "number" ? value.cost_usd : 0,
    context_window_used_tokens:
      typeof value.context_window_used_tokens === "number"
        ? value.context_window_used_tokens
        : null,
    context_window_total_tokens:
      typeof value.context_window_total_tokens === "number"
        ? value.context_window_total_tokens
        : null,
    current_run_id: typeof value.current_run_id === "string" ? value.current_run_id : null,
    run_sequence: typeof value.run_sequence === "number" ? value.run_sequence : undefined
  };
}

function normalizeEvent(raw: unknown): TaskEvent {
  const value = asRecord(raw);
  const payload = asRecord(value.payload);
  return {
    id: String(value.id ?? ""),
    stream_id: typeof value.stream_id === "number" ? value.stream_id : undefined,
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

interface GetTasksOptions {
  limit?: number;
  offset?: number;
}

export async function getTasks(
  status?: TaskStatus,
  options: GetTasksOptions = {}
): Promise<TaskListResult> {
  const params = new URLSearchParams();
  if (status) {
    params.set("status", status);
  }
  const safeLimit =
    typeof options.limit === "number" && Number.isFinite(options.limit)
      ? Math.max(1, Math.floor(options.limit))
      : 20;
  const safeOffset =
    typeof options.offset === "number" && Number.isFinite(options.offset)
      ? Math.max(0, Math.floor(options.offset))
      : 0;
  params.set("limit", String(safeLimit));
  params.set("offset", String(safeOffset));
  const query = params.toString();
  const body = await authorizedFetchJson<{
    items?: unknown[];
    total?: number;
    limit?: number;
    offset?: number;
  }>(
    `/api/v1/tasks${query ? `?${query}` : ""}`,
    {
      cache: "no-store"
    }
  );
  const items = Array.isArray(body.items) ? body.items : [];
  return {
    total: typeof body.total === "number" ? body.total : items.length,
    limit: typeof body.limit === "number" ? body.limit : safeLimit,
    offset: typeof body.offset === "number" ? body.offset : safeOffset,
    items: items.map(normalizeTask)
  };
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

export async function trackUiEvent(
  eventName: string,
  detail: Record<string, unknown> = {},
  taskId?: string
): Promise<void> {
  await authorizedFetchJson("/api/v1/tasks/telemetry/event", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      event_name: eventName,
      task_id: taskId,
      detail
    })
  });
}

export async function getAuditLogs(
  limit = 20,
  offset = 0,
  filters: AuditLogFilters = {}
): Promise<AuditLogList> {
  const safeLimit = Math.max(1, Math.floor(limit));
  const safeOffset = Math.max(0, Math.floor(offset));
  const params = new URLSearchParams();
  params.set("limit", String(safeLimit));
  params.set("offset", String(safeOffset));
  if (filters.actor?.trim()) {
    params.set("actor", filters.actor.trim());
  }
  if (filters.task_id?.trim()) {
    params.set("task_id", filters.task_id.trim());
  }
  if (filters.action?.trim()) {
    params.set("action", filters.action.trim());
  }
  const body = await authorizedFetchJson<{
    items?: AuditLog[];
    total?: number;
    limit?: number;
    offset?: number;
  }>(`/api/v1/tasks/audit/logs?${params.toString()}`);
  const items = Array.isArray(body.items) ? body.items : [];
  return {
    total: typeof body.total === "number" ? body.total : items.length,
    limit: typeof body.limit === "number" ? body.limit : safeLimit,
    offset: typeof body.offset === "number" ? body.offset : safeOffset,
    items
  };
}

export async function getHealthStatus(): Promise<HealthStatus> {
  const body = await fetchJson<unknown>(`${API_BASE_URL}/healthz`, { cache: "no-store" });
  return normalizeHealth(body);
}

export async function getExecutorOptions(): Promise<ExecutorCapability> {
  const body = await authorizedFetchJson<unknown>("/api/v1/tasks/executor/options", {
    cache: "no-store"
  });
  const value = asRecord(body);
  const modelOptions = Array.isArray(value.model_options)
    ? value.model_options.filter((item): item is string => typeof item === "string")
    : [];
  const reasoningEffortOptions = Array.isArray(value.reasoning_effort_options)
    ? value.reasoning_effort_options.filter((item): item is string => typeof item === "string")
    : [];
  return {
    source: typeof value.source === "string" ? value.source : "unknown",
    model_options: modelOptions,
    reasoning_effort_options: reasoningEffortOptions,
    supports_parallel_agents:
      typeof value.supports_parallel_agents === "boolean" ? value.supports_parallel_agents : true
  };
}

export async function getPendingMobileLoginRequests(): Promise<PendingMobileLoginRequest[]> {
  const body = await authorizedFetchJson<{ items?: PendingMobileLoginRequest[] }>(
    "/api/v1/auth/mobile/pending",
    { cache: "no-store" }
  );
  const items = Array.isArray(body.items) ? body.items : [];
  return items
    .filter((item): item is PendingMobileLoginRequest => {
      return (
        typeof item?.request_id === "string" &&
        typeof item?.status === "string" &&
        typeof item?.username === "string" &&
        typeof item?.device_name === "string" &&
        typeof item?.request_ip === "string" &&
        typeof item?.created_at === "string" &&
        typeof item?.expires_at === "string"
      );
    })
    .map((item) => ({
      ...item,
      risk_level: item.risk_level === "HIGH" || item.risk_level === "MEDIUM" ? item.risk_level : "LOW",
      risk_reasons: Array.isArray(item.risk_reasons)
        ? item.risk_reasons.filter((value): value is string => typeof value === "string")
        : [],
      known_device: Boolean(item.known_device),
      known_ip: Boolean(item.known_ip),
      device_approval_count:
        typeof item.device_approval_count === "number" ? Math.max(0, Math.floor(item.device_approval_count)) : 0,
      device_last_approved_at:
        typeof item.device_last_approved_at === "string" ? item.device_last_approved_at : null,
      ip_seen_count: typeof item.ip_seen_count === "number" ? Math.max(0, Math.floor(item.ip_seen_count)) : 0,
      ip_last_seen_at: typeof item.ip_last_seen_at === "string" ? item.ip_last_seen_at : null,
      ip_risk_level:
        item.ip_risk_level === "HIGH" || item.ip_risk_level === "MEDIUM" ? item.ip_risk_level : "LOW"
    }));
}

export async function approveMobileLoginRequest(requestId: string): Promise<void> {
  await authorizedFetchJson(`/api/v1/auth/mobile/requests/${encodeURIComponent(requestId)}/approve`, {
    method: "POST"
  });
}

export async function rejectMobileLoginRequest(requestId: string): Promise<void> {
  await authorizedFetchJson(`/api/v1/auth/mobile/requests/${encodeURIComponent(requestId)}/reject`, {
    method: "POST"
  });
}

export async function cancelMobileLoginRequest(requestId: string, requestToken: string): Promise<void> {
  await fetchJson(`${API_BASE_URL}/api/v1/auth/mobile/requests/${encodeURIComponent(requestId)}/cancel`, {
    method: "POST",
    headers: {
      "X-Mobile-Request-Token": requestToken
    }
  });
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

export function bindTaskEventStream(
  onEvent: (event: TaskEvent) => void
): (rawData: string) => TaskEvent | null {
  return (rawData: string) => {
    try {
      const parsed = JSON.parse(rawData) as unknown;
      const event = normalizeEvent(parsed);
      onEvent(event);
      return event;
    } catch {
      // Ignore malformed event payload.
      return null;
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
  let lastStreamId = 0;
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
          Authorization: `Bearer ${session.accessToken}`,
          ...(lastStreamId > 0 ? { "Last-Event-ID": String(lastStreamId) } : {})
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
            const event = consume(payload);
            if (event?.stream_id && event.stream_id > lastStreamId) {
              lastStreamId = event.stream_id;
            }
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
