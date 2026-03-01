"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { HealthStatus, getHealthStatus } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

type ConnectionState = "loading" | "ready" | "error";

export function ExecutorStatusBar() {
  const [connectionState, setConnectionState] = useState<ConnectionState>("loading");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setConnectionState("loading");
    }
    try {
      const nextHealth = await getHealthStatus();
      setHealth(nextHealth);
      setError(null);
      setConnectionState("ready");
    } catch (loadError) {
      setConnectionState("error");
      setError(
        loadError instanceof Error ? loadError.message : bi("无法读取后端状态。", "Failed to load backend status.")
      );
    }
  }, []);

  useEffect(() => {
    void load(false);
    const timer = window.setInterval(() => {
      void load(true);
    }, 10000);
    return () => {
      window.clearInterval(timer);
    };
  }, [load]);

  const executorMode = (health?.task_executor || "unknown").toLowerCase();
  const executorBackend = health?.execution_backend || "unknown";
  const checkedAt = formatDateTime(health?.timestamp || "", "--");
  const workerConcurrency = health?.worker_concurrency;
  const replayLimit = health?.sse_replay_limit;
  const workdirWhitelist = health?.workdir_whitelist ?? [];
  const codexMinTimeout = health?.codex_min_timeout_seconds;
  const codexHardTimeout = health?.codex_hard_timeout_seconds;
  const codexCliPath = health?.codex_cli_path || "codex";
  const codexCliExists = health?.codex_cli_exists;
  const requireLoopbackDirectLogin = health?.require_loopback_direct_login;
  const mobileLoginRequestTtl = health?.mobile_login_request_ttl_seconds;

  const executorText = useMemo(() => {
    if (executorMode === "codex") {
      return bi("Codex（真实执行）", "Codex (real execution)");
    }
    if (executorMode === "simulator") {
      return bi("Simulator（模拟执行）", "Simulator (mock execution)");
    }
    return bi("未知", "Unknown");
  }, [executorMode]);

  const modeClassName =
    executorMode === "codex"
      ? "executor-pill executor-pill-codex"
      : executorMode === "simulator"
        ? "executor-pill executor-pill-simulator"
        : "executor-pill executor-pill-unknown";

  const indicatorClassName =
    connectionState === "error"
      ? "executor-indicator executor-indicator-error"
      : "executor-indicator";

  return (
    <section className="panel full-span animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("执行器状态", "Executor Status")}</h2>
        <button className="button button-secondary" type="button" onClick={() => void load(false)}>
          {bi("刷新", "Refresh")}
        </button>
      </div>
      <div className="executor-status-row">
        <div className="executor-status-main">
          <span className={indicatorClassName} aria-hidden="true" />
          <span className="muted">{bi("当前模式", "Current Mode")}</span>
          <span className={modeClassName}>{connectionState === "error" ? bi("不可用", "Unavailable") : executorText}</span>
        </div>
        <p className="muted executor-meta">
          {bi("队列后端", "Execution Backend")}: {executorBackend} · {bi("更新时间", "Updated")}: {checkedAt}
        </p>
        {typeof workerConcurrency === "number" ? (
          <p className="muted executor-meta">
            {bi("Worker 并发", "Worker Concurrency")}: {workerConcurrency}
            {typeof replayLimit === "number" ? ` · ${bi("SSE 重放上限", "SSE Replay Limit")}: ${replayLimit}` : ""}
          </p>
        ) : null}
        {workdirWhitelist.length > 0 ? (
          <p className="muted executor-meta">
            {bi("允许目录", "Allowed Workdirs")}: {workdirWhitelist.join(" | ")}
          </p>
        ) : null}
        <p className="muted executor-meta">
          {bi("Codex 路径", "Codex Path")}: <code>{codexCliPath}</code>
        </p>
        {typeof requireLoopbackDirectLogin === "boolean" ? (
          <p className="muted executor-meta">
            {bi("直接登录策略", "Direct Login Policy")}:{" "}
            {requireLoopbackDirectLogin
              ? bi("仅本机回环地址可直接登录", "localhost-only direct sign-in")
              : bi("允许任意来源直接登录", "direct sign-in from any source")}
            {typeof mobileLoginRequestTtl === "number"
              ? ` · ${bi("手机授权有效期", "Mobile approval TTL")}: ${mobileLoginRequestTtl}s`
              : ""}
          </p>
        ) : null}
        {executorMode === "codex" && typeof codexMinTimeout === "number" ? (
          <p className="muted executor-meta">
            {bi("Codex 空闲超时", "Codex Idle Timeout")}: {codexMinTimeout}s
          </p>
        ) : null}
        {executorMode === "codex" && typeof codexHardTimeout === "number" ? (
          <p className="muted executor-meta">
            {bi("Codex 硬超时", "Codex Hard Timeout")}: {codexHardTimeout}s
          </p>
        ) : null}
      </div>
      {executorMode === "simulator" ? (
        <p className="note">
          {bi(
            "当前为模拟模式，发送消息后不会真正执行本地 Codex 命令。",
            "Simulator mode does not execute real local Codex commands."
          )}
        </p>
      ) : null}
      {executorMode === "codex" && codexCliExists === false ? (
        <p className="error">
          {bi(
            "Codex 可执行文件不存在，请检查 CODEX_CLI_PATH。",
            "Codex executable not found. Check CODEX_CLI_PATH."
          )}
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
