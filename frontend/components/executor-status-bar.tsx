"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { HealthStatus, getHealthStatus } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi, useLanguage } from "@/lib/i18n";

type ConnectionState = "loading" | "ready" | "error";

const POLL_VISIBLE_MS = 20_000;
const POLL_HIDDEN_MS = 60_000;

export function ExecutorStatusBar() {
  const [language] = useLanguage();
  const [connectionState, setConnectionState] = useState<ConnectionState>("loading");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);

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
    if (typeof window === "undefined") {
      return;
    }
    const media = window.matchMedia("(max-width: 719px)");
    const applyState = (): void => {
      setExpanded(!media.matches);
    };
    applyState();
    media.addEventListener("change", applyState);
    return () => {
      media.removeEventListener("change", applyState);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const schedule = (): void => {
      if (cancelled) {
        return;
      }
      const delay = typeof document !== "undefined" && document.hidden ? POLL_HIDDEN_MS : POLL_VISIBLE_MS;
      timer = window.setTimeout(() => {
        void tick();
      }, delay);
    };

    const tick = async (): Promise<void> => {
      if (cancelled) {
        return;
      }
      await load(true);
      if (!cancelled) {
        schedule();
      }
    };

    const handleVisibilityChange = (): void => {
      if (typeof document !== "undefined" && !document.hidden) {
        if (timer) {
          window.clearTimeout(timer);
          timer = null;
        }
        void tick();
      }
    };

    void load(false).finally(() => {
      if (!cancelled) {
        schedule();
      }
    });

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
      document.removeEventListener("visibilitychange", handleVisibilityChange);
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
    if (executorMode === "codex-cli") {
      return bi("Codex CLI（真实执行）", "Codex CLI (real execution)");
    }
    if (executorMode === "simulator") {
      return bi("Simulator（模拟执行）", "Simulator (mock execution)");
    }
    return bi("未知", "Unknown");
  }, [executorMode, language]);

  const modeClassName =
    executorMode === "codex" || executorMode === "codex-cli"
      ? "executor-pill executor-pill-codex"
      : executorMode === "simulator"
        ? "executor-pill executor-pill-simulator"
        : "executor-pill executor-pill-unknown";

  const indicatorClassName =
    connectionState === "error"
      ? "executor-indicator executor-indicator-error"
      : "executor-indicator";

  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("系统状态（高级）", "System Status (Advanced)")}</h2>
        <div className="pagination-actions compact-actions">
          <button className="button button-secondary" type="button" onClick={() => setExpanded((prev) => !prev)}>
            {expanded ? bi("收起", "Collapse") : bi("展开", "Expand")}
          </button>
          <button className="button button-secondary" type="button" onClick={() => void load(false)}>
            {bi("刷新", "Refresh")}
          </button>
        </div>
      </div>
      <div className="executor-status-row">
        <div className="executor-status-main">
          <span className={indicatorClassName} aria-hidden="true" />
          <span className="muted">{bi("当前模式", "Current mode")}</span>
          <span className={modeClassName}>{connectionState === "error" ? bi("不可用", "Unavailable") : executorText}</span>
        </div>
        <p className="muted executor-meta">
          {bi("队列后端", "Execution backend")}: {executorBackend} · {bi("更新时间", "Updated")}: {checkedAt}
        </p>
      </div>
      {expanded ? (
        <>
          {typeof workerConcurrency === "number" ? (
            <p className="muted executor-meta">
              {bi("Worker 并发", "Worker concurrency")}: {workerConcurrency}
              {typeof replayLimit === "number" ? ` · ${bi("SSE 重放上限", "SSE replay limit")}: ${replayLimit}` : ""}
            </p>
          ) : null}
          {workdirWhitelist.length > 0 ? (
            <p className="muted executor-meta">
              {bi("允许目录", "Allowed workdirs")}: {workdirWhitelist.join(" | ")}
            </p>
          ) : null}
          <p className="muted executor-meta">
            {bi("CLI 路径", "CLI path")}: <code>{codexCliPath}</code>
          </p>
          {typeof requireLoopbackDirectLogin === "boolean" ? (
            <p className="muted executor-meta">
              {bi("直接登录策略", "Direct login policy")}: {" "}
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
              {bi("Codex 空闲超时", "Codex idle timeout")}: {codexMinTimeout}s
            </p>
          ) : null}
          {executorMode === "codex" && typeof codexHardTimeout === "number" ? (
            <p className="muted executor-meta">
              {bi("Codex 硬超时", "Codex hard timeout")}: {codexHardTimeout}s
            </p>
          ) : null}
        </>
      ) : null}
      {executorMode === "simulator" ? (
        <p className="note">
          {bi(
            "当前为模拟模式，发送消息后不会真正执行本地 Codex 命令。",
            "Simulator mode does not execute real local Codex commands."
          )}
        </p>
      ) : null}
      {(executorMode === "codex" || executorMode === "codex-cli") && codexCliExists === false ? (
        <p className="error">
          {bi(
            "CLI 可执行文件不存在，请检查 CODEX_CLI_PATH。",
            "CLI executable not found. Check CODEX_CLI_PATH."
          )}
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
