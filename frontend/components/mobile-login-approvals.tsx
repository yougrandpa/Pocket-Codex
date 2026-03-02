"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  PendingMobileLoginRequest,
  approveMobileLoginRequest,
  getPendingMobileLoginRequests,
  rejectMobileLoginRequest
} from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface MobileLoginApprovalsProps {
  enabled?: boolean;
}

const POLL_FAST_MS = 2000;
const POLL_IDLE_MS = 8000;
const POLL_HIDDEN_MS = 30000;
const POLL_MAX_BACKOFF_MS = 60000;

function riskLevelText(level: PendingMobileLoginRequest["risk_level"]): string {
  if (level === "HIGH") {
    return bi("高风险", "High risk");
  }
  if (level === "MEDIUM") {
    return bi("中风险", "Medium risk");
  }
  return bi("低风险", "Low risk");
}

function riskClassName(level: PendingMobileLoginRequest["risk_level"]): string {
  if (level === "HIGH") {
    return "risk-chip risk-chip-high";
  }
  if (level === "MEDIUM") {
    return "risk-chip risk-chip-medium";
  }
  return "risk-chip risk-chip-low";
}

function riskReasonText(reason: string): string {
  if (reason === "NEW_DEVICE") {
    return bi("新设备首次请求", "New device request");
  }
  if (reason === "NEW_IP") {
    return bi("新 IP 首次请求", "New IP request");
  }
  if (reason === "PUBLIC_SOURCE_IP") {
    return bi("公网来源 IP", "Public source IP");
  }
  if (reason === "NON_GLOBAL_SOURCE_IP") {
    return bi("非公网可路由来源 IP", "Non-global source IP");
  }
  if (reason === "UNTRUSTED_PROXY") {
    return bi("来源代理不可识别", "Untrusted proxy source");
  }
  if (reason === "UNKNOWN_SOURCE_IP") {
    return bi("来源 IP 未知", "Unknown source IP");
  }
  if (reason === "INVALID_SOURCE_IP") {
    return bi("来源 IP 非法", "Invalid source IP");
  }
  return reason;
}

export function MobileLoginApprovals({ enabled = true }: MobileLoginApprovalsProps) {
  const [requests, setRequests] = useState<PendingMobileLoginRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);
  const pendingCountRef = useRef(0);

  useEffect(() => {
    pendingCountRef.current = requests.length;
  }, [requests.length]);

  const loadRequests = useCallback(
    async (silent = false): Promise<boolean> => {
      if (!enabled) {
        setRequests([]);
        setLoading(false);
        setError(null);
        return true;
      }
      if (!silent) {
        setLoading(true);
      }
      try {
        const items = await getPendingMobileLoginRequests();
        setRequests(items);
        setError(null);
        return true;
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : bi("读取授权请求失败。", "Failed to load approval requests.")
        );
        return false;
      } finally {
        if (!silent) {
          setLoading(false);
        }
      }
    },
    [enabled]
  );

  useEffect(() => {
    if (!enabled) {
      void loadRequests(false);
      return;
    }

    let cancelled = false;
    let timer: number | null = null;
    let consecutiveFailures = 0;

    const schedule = (delayMs: number): void => {
      if (cancelled) {
        return;
      }
      if (timer) {
        window.clearTimeout(timer);
      }
      timer = window.setTimeout(() => {
        void tick();
      }, delayMs);
    };

    const computeBaseDelay = (): number => {
      if (typeof document !== "undefined" && document.hidden) {
        return POLL_HIDDEN_MS;
      }
      return pendingCountRef.current > 0 ? POLL_FAST_MS : POLL_IDLE_MS;
    };

    const tick = async (): Promise<void> => {
      if (cancelled) {
        return;
      }
      const ok = await loadRequests(true);
      if (cancelled) {
        return;
      }
      if (ok) {
        consecutiveFailures = 0;
        schedule(computeBaseDelay());
        return;
      }
      consecutiveFailures = Math.min(consecutiveFailures + 1, 6);
      const backoff = computeBaseDelay() * 2 ** (consecutiveFailures - 1);
      schedule(Math.min(POLL_MAX_BACKOFF_MS, backoff));
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

    void loadRequests(false).then((ok) => {
      if (cancelled) {
        return;
      }
      if (!ok) {
        consecutiveFailures = 1;
      }
      schedule(ok ? computeBaseDelay() : Math.min(POLL_MAX_BACKOFF_MS, computeBaseDelay() * 2));
    });

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, loadRequests]);

  async function handleDecision(item: PendingMobileLoginRequest, action: "approve" | "reject"): Promise<void> {
    if (action === "approve" && item.risk_level === "HIGH") {
      const confirmed = window.confirm(
        bi(
          `高风险授权确认：\n设备 ${item.device_name}\n来源 ${item.request_ip}\n风险因素：${item.risk_reasons
            .map(riskReasonText)
            .join("、")}\n\n请确认这是你本人设备后再继续。`,
          `High-risk approval confirmation:\nDevice ${item.device_name}\nSource ${item.request_ip}\nRisk factors: ${item.risk_reasons
            .map(riskReasonText)
            .join(", ")}\n\nOnly continue if this is your own trusted device.`
        )
      );
      if (!confirmed) {
        return;
      }
    }

    setActingId(item.request_id);
    setError(null);
    try {
      if (action === "approve") {
        await approveMobileLoginRequest(item.request_id);
      } else {
        await rejectMobileLoginRequest(item.request_id);
      }
      await loadRequests(true);
    } catch (decisionError) {
      setError(
        decisionError instanceof Error
          ? decisionError.message
          : bi("提交授权操作失败。", "Failed to submit approval decision.")
      );
    } finally {
      setActingId(null);
    }
  }

  return (
    <section className="panel animate-rise delay-2">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("手机登录授权", "Mobile Login Approvals")}</h2>
        <span className="chip">{requests.length}</span>
      </div>
      <p className="muted">
        {bi(
          "仅在你确认设备可信时授权，超时请求会自动失效。",
          "Approve only trusted devices. Expired requests are automatically rejected."
        )}
      </p>
      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="muted">{bi("加载中...", "Loading...")}</p> : null}
      {!loading && requests.length === 0 ? (
        <p className="muted">{bi("当前没有待处理的手机登录请求。", "No pending mobile login requests.")}</p>
      ) : null}
      {requests.length > 0 ? (
        <ul className="notification-list">
          {requests.map((item) => (
            <li key={item.request_id} className="notification-item">
              <div className="task-item-top">
                <strong>{item.device_name}</strong>
                <time dateTime={item.created_at}>{formatDateTime(item.created_at)}</time>
              </div>
              <div className="risk-summary">
                <span className={riskClassName(item.risk_level)}>{riskLevelText(item.risk_level)}</span>
                <span className={riskClassName(item.ip_risk_level)}>
                  {bi("IP 风险", "IP risk")}: {riskLevelText(item.ip_risk_level)}
                </span>
              </div>
              <p className="muted">
                IP: {item.request_ip} · ID: {item.request_id.slice(0, 10)} · {bi("到期", "Expires")}: {" "}
                {formatDateTime(item.expires_at)}
              </p>
              <p className="muted">
                {item.known_device
                  ? bi(
                      `设备历史：已授权 ${item.device_approval_count} 次`,
                      `Device history: approved ${item.device_approval_count} times`
                    )
                  : bi("设备历史：首次授权设备", "Device history: first-time device")}
                {item.device_last_approved_at
                  ? ` · ${bi("最近", "Last")}: ${formatDateTime(item.device_last_approved_at)}`
                  : ""}
              </p>
              <p className="muted">
                {item.known_ip
                  ? bi(
                      `IP 历史：已出现 ${item.ip_seen_count} 次`,
                      `IP history: seen ${item.ip_seen_count} times`
                    )
                  : bi("IP 历史：首次来源 IP", "IP history: first-time source IP")}
                {item.ip_last_seen_at ? ` · ${bi("最近", "Last")}: ${formatDateTime(item.ip_last_seen_at)}` : ""}
              </p>
              {item.risk_reasons.length > 0 ? (
                <p className="muted">
                  {bi("风险提示", "Risk signals")}: {item.risk_reasons.map(riskReasonText).join(" · ")}
                </p>
              ) : null}
              <div className="pagination-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={actingId === item.request_id}
                  onClick={() => {
                    void handleDecision(item, "reject");
                  }}
                >
                  {actingId === item.request_id ? bi("处理中...", "Working...") : bi("拒绝", "Reject")}
                </button>
                <button
                  className="button"
                  type="button"
                  disabled={actingId === item.request_id}
                  onClick={() => {
                    void handleDecision(item, "approve");
                  }}
                >
                  {actingId === item.request_id ? bi("处理中...", "Working...") : bi("允许登录", "Approve")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
