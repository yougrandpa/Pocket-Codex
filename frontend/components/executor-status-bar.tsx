"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { HealthStatus, getHealthStatus } from "@/lib/api";
import { bi } from "@/lib/i18n";

type ConnectionState = "loading" | "ready" | "error";

function formatHealthTimestamp(value: string): string {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

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
  const checkedAt = formatHealthTimestamp(health?.timestamp || "");

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
      </div>
      {executorMode === "simulator" ? (
        <p className="note">
          {bi(
            "当前为模拟模式，发送消息后不会真正执行本地 Codex 命令。",
            "Simulator mode does not execute real local Codex commands."
          )}
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
