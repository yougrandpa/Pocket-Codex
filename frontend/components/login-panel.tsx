"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { getMobileLoginStatus, login, requestMobileLogin } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface LoginPanelProps {
  onLoggedIn: () => void;
}

function defaultDeviceName(): string {
  if (typeof window === "undefined") {
    return "";
  }
  const value = window.navigator.userAgent || "mobile-browser";
  return value.slice(0, 120);
}

export function LoginPanel({ onLoggedIn }: LoginPanelProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [deviceName, setDeviceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null);
  const [pendingExpiresAt, setPendingExpiresAt] = useState<string | null>(null);
  const [pollIntervalSeconds, setPollIntervalSeconds] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const formInvalid = useMemo(
    () => username.trim().length === 0 || password.trim().length === 0,
    [password, username]
  );

  useEffect(() => {
    setDeviceName(defaultDeviceName());
  }, []);

  useEffect(() => {
    if (!pendingRequestId) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      void (async () => {
        if (cancelled) {
          return;
        }
        try {
          const status = await getMobileLoginStatus(pendingRequestId);
          if (cancelled) {
            return;
          }
          if (status.status === "COMPLETED" && status.access_token && status.refresh_token) {
            setNote(null);
            setError(null);
            setPendingRequestId(null);
            onLoggedIn();
            return;
          }
          if (status.status === "REJECTED") {
            setPendingRequestId(null);
            setError(
              bi("电脑端已拒绝此次手机登录请求。", "Desktop rejected this mobile sign-in request.")
            );
            setNote(null);
            return;
          }
          if (status.status === "EXPIRED") {
            setPendingRequestId(null);
            setError(bi("授权请求已过期，请重新发起。", "Approval request expired. Please start again."));
            setNote(null);
            return;
          }
          setNote(
            bi(
              "等待电脑端授权中，请在电脑控制台点击“允许登录”。",
              "Waiting for desktop approval. Approve from desktop dashboard."
            )
          );
        } catch (pollError) {
          if (cancelled) {
            return;
          }
          setPendingRequestId(null);
          setError(
            pollError instanceof Error
              ? pollError.message
              : bi("轮询授权状态失败。", "Failed to poll approval status.")
          );
        }
      })();
    }, Math.max(1, pollIntervalSeconds) * 1000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [onLoggedIn, pendingRequestId, pollIntervalSeconds]);

  async function handleDesktopLogin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting || formInvalid || pendingRequestId) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setNote(null);
    try {
      await login(username.trim(), password);
      onLoggedIn();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : bi("登录失败。", "Sign in failed."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMobileLoginRequest(): Promise<void> {
    if (submitting || formInvalid || pendingRequestId) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setNote(null);
    try {
      const requestResult = await requestMobileLogin(
        username.trim(),
        password,
        deviceName.trim() || "mobile-browser"
      );
      setPendingRequestId(requestResult.request_id);
      setPendingExpiresAt(requestResult.expires_at);
      setPollIntervalSeconds(requestResult.poll_interval_seconds || 2);
      setNote(
        bi(
          "手机登录请求已发送，请在电脑端“手机登录授权”面板中批准。",
          "Mobile sign-in request sent. Approve it from desktop Mobile Login Approvals panel."
        )
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : bi("发起手机登录请求失败。", "Failed to request mobile sign-in.")
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("登录", "Sign In")}</h2>
        <span className="chip">{bi("电脑授权手机", "Desktop Approval")}</span>
      </div>
      <p className="muted">
        {bi(
          "本系统默认只允许本机直接登录；手机端需要先发起请求，再由电脑端批准。",
          "Direct login is localhost-only by default. Mobile login requires desktop approval."
        )}
      </p>
      <form className="stack" onSubmit={handleDesktopLogin}>
        <label className="field">
          <span>{bi("用户名", "Username")}</span>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>{bi("密码", "Password")}</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>{bi("手机设备名", "Mobile device name")}</span>
          <input
            type="text"
            value={deviceName}
            onChange={(event) => setDeviceName(event.target.value.slice(0, 120))}
            placeholder={bi("例如：iPhone-15-Pro", "Example: iPhone-15-Pro")}
          />
        </label>

        {pendingRequestId ? (
          <div className="detail-block">
            <h3>{bi("待审批请求", "Pending approval")}</h3>
            <p>
              ID: {pendingRequestId}
              <br />
              {bi("到期", "Expires")}: {formatDateTime(pendingExpiresAt)}
            </p>
          </div>
        ) : null}

        {error ? <p className="error">{error}</p> : null}
        {note ? <p className="note">{note}</p> : null}

        <div className="pagination-actions">
          <button className="button" type="submit" disabled={submitting || formInvalid || Boolean(pendingRequestId)}>
            {submitting ? bi("登录中...", "Signing in...") : bi("电脑端直接登录", "Desktop direct sign-in")}
          </button>
          <button
            className="button button-secondary"
            type="button"
            disabled={submitting || formInvalid || Boolean(pendingRequestId)}
            onClick={() => {
              void handleMobileLoginRequest();
            }}
          >
            {submitting ? bi("提交中...", "Submitting...") : bi("手机登录（需电脑授权）", "Mobile sign-in (needs approval)")}
          </button>
          {pendingRequestId ? (
            <button
              className="button button-secondary"
              type="button"
              onClick={() => {
                setPendingRequestId(null);
                setPendingExpiresAt(null);
                setNote(null);
                setError(null);
              }}
            >
              {bi("取消等待", "Cancel waiting")}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}
