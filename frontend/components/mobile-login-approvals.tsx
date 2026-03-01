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

  async function handleDecision(requestId: string, action: "approve" | "reject"): Promise<void> {
    setActingId(requestId);
    setError(null);
    try {
      if (action === "approve") {
        await approveMobileLoginRequest(requestId);
      } else {
        await rejectMobileLoginRequest(requestId);
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
              <p className="muted">
                IP: {item.request_ip} · ID: {item.request_id.slice(0, 10)} · {bi("到期", "Expires")}: {" "}
                {formatDateTime(item.expires_at)}
              </p>
              <div className="pagination-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={actingId === item.request_id}
                  onClick={() => {
                    void handleDecision(item.request_id, "reject");
                  }}
                >
                  {actingId === item.request_id ? bi("处理中...", "Working...") : bi("拒绝", "Reject")}
                </button>
                <button
                  className="button"
                  type="button"
                  disabled={actingId === item.request_id}
                  onClick={() => {
                    void handleDecision(item.request_id, "approve");
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
