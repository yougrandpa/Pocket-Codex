"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { cancelMobileLoginRequest, getMobileLoginStatus, login, requestMobileLogin } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { bi } from "@/lib/i18n";

interface LoginPanelProps {
  onLoggedIn: () => void;
}

function defaultDeviceName(): string {
  if (typeof window === "undefined") {
    return "mobile-browser";
  }
  const ua = window.navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) {
    return "iPhone Safari";
  }
  if (/Android/i.test(ua)) {
    if (/Chrome/i.test(ua)) {
      return "Android Chrome";
    }
    return "Android Browser";
  }
  if (/Macintosh/i.test(ua)) {
    return "Mac Browser";
  }
  if (/Windows/i.test(ua)) {
    return "Windows Browser";
  }
  return "mobile-browser";
}

export function LoginPanel({ onLoggedIn }: LoginPanelProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [deviceName, setDeviceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null);
  const [pendingRequestToken, setPendingRequestToken] = useState<string | null>(null);
  const [pendingExpiresAt, setPendingExpiresAt] = useState<string | null>(null);
  const [pollIntervalSeconds, setPollIntervalSeconds] = useState(2);
  const [cancelPending, setCancelPending] = useState(false);
  const [compactViewport, setCompactViewport] = useState(false);
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
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia("(max-width: 719px)");
    const sync = () => setCompactViewport(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const desktopApprovePath = useMemo(() => {
    if (typeof window === "undefined") {
      return "http://localhost:3000";
    }
    return `${window.location.origin}/`;
  }, []);

  const mapAuthError = useCallback((raw: unknown): string => {
    const message = raw instanceof Error ? raw.message : "";
    if (message.includes("Request validation failed") || message.includes("Invalid request token")) {
      return bi(
        "授权请求已失效，请重新发起手机授权。",
        "Approval request is no longer valid. Please request mobile approval again."
      );
    }
    if (message.includes("Invalid credentials")) {
      return bi("账号或密码错误，请重试。", "Invalid username or password. Please try again.");
    }
    if (message.includes("Request timed out")) {
      return bi(
        "请求超时，请确认网络与服务状态后重试。",
        "Request timed out. Verify network/backend status and retry."
      );
    }
    if (message.includes("Internal Server Error") || message.includes("HTTP 500")) {
      return bi(
        "登录服务暂时不可用，请稍后重试；若持续失败请先在电脑端检查服务状态。",
        "Login service is temporarily unavailable. Retry shortly, or check backend status on desktop."
      );
    }
    return message || bi("登录失败。", "Sign in failed.");
  }, []);

  const pollPendingRequest = useCallback(
    async (requestId: string, requestToken: string): Promise<boolean> => {
      const status = await getMobileLoginStatus(requestId, requestToken);
      if (status.status === "COMPLETED" && status.access_token && status.refresh_token) {
        setNote(null);
        setError(null);
        setPendingRequestId(null);
        setPendingRequestToken(null);
        onLoggedIn();
        return true;
      }
      if (status.status === "REJECTED" || status.status === "CANCELED") {
        setPendingRequestId(null);
        setPendingRequestToken(null);
        setError(
          bi(
            "该手机登录请求已被拒绝或取消，请重新发起。",
            "The mobile sign-in request was rejected or canceled. Please start again."
          )
        );
        setNote(null);
        return true;
      }
      if (status.status === "EXPIRED") {
        setPendingRequestId(null);
        setPendingRequestToken(null);
        setError(bi("授权请求已过期，请重新发起。", "Approval request expired. Please start again."));
        setNote(null);
        return true;
      }
      setNote(
        bi(
          "步骤 2/3：请在电脑端“手机登录授权”中点击允许；允许后可点“立即检查”。",
          "Step 2/3: Approve in desktop Mobile Login Approvals; then tap Check now."
        )
      );
      return false;
    },
    [onLoggedIn]
  );

  useEffect(() => {
    if (!pendingRequestId || !pendingRequestToken) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      void (async () => {
        if (cancelled) {
          return;
        }
        try {
          await pollPendingRequest(pendingRequestId, pendingRequestToken);
        } catch (pollError) {
          if (cancelled) {
            return;
          }
          setPendingRequestId(null);
          setPendingRequestToken(null);
          setError(mapAuthError(pollError));
        }
      })();
    }, Math.max(1, pollIntervalSeconds) * 1000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [mapAuthError, pendingRequestId, pendingRequestToken, pollIntervalSeconds, pollPendingRequest]);

  async function handleDesktopLogin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (submitting || formInvalid) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setNote(null);
    try {
      await login(username.trim(), password);
      onLoggedIn();
    } catch (submitError) {
      setError(mapAuthError(submitError));
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
      setPendingRequestToken(requestResult.request_token);
      setPendingExpiresAt(requestResult.expires_at);
      setPollIntervalSeconds(requestResult.poll_interval_seconds || 2);
      setNote(
        bi(
          "步骤 1/3 已完成：请求已发送。请到电脑端批准后返回此处自动登录。",
          "Step 1/3 done: request sent. Approve on desktop, then return to auto sign in."
        )
      );
    } catch (requestError) {
      setError(mapAuthError(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancelWaiting(): Promise<void> {
    if (!pendingRequestId || !pendingRequestToken || cancelPending) {
      return;
    }
    setCancelPending(true);
    setError(null);
    try {
      await cancelMobileLoginRequest(pendingRequestId, pendingRequestToken);
      setPendingRequestId(null);
      setPendingRequestToken(null);
      setPendingExpiresAt(null);
      setNote(bi("已取消等待授权。", "Canceled waiting for approval."));
    } catch (cancelError) {
      setError(mapAuthError(cancelError));
    } finally {
      setCancelPending(false);
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
          "手机端推荐流程：发起授权请求 -> 电脑端批准 -> 手机自动登录。",
          "Recommended mobile flow: request approval -> approve on desktop -> mobile auto sign-in."
        )}
      </p>
      <ol className="muted login-steps">
        <li>{bi("1) 输入账号密码，点击“发起手机授权”。", "1) Enter credentials and tap Request mobile approval.")}</li>
        <li>{bi("2) 在电脑端“手机登录授权”里点击允许。", "2) Approve in desktop Mobile Login Approvals.")}</li>
        <li>{bi("3) 回到手机端自动完成登录。", "3) Return to mobile and sign in automatically.")}</li>
      </ol>
      <p className="muted login-inline-tip">
        {bi(
          "提示：先填写用户名和密码，按钮才可点击。",
          "Tip: Username and password are required before actions are enabled."
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
            <p className="muted">
              {bi("请在电脑端打开并审批：", "Open on desktop and approve:")}{" "}
              <code>{desktopApprovePath}</code>
            </p>
            <div className="pagination-actions" style={{ marginTop: "8px" }}>
              <button
                className="button button-secondary"
                type="button"
                disabled={submitting}
                onClick={() => {
                  if (!pendingRequestToken) {
                    return;
                  }
                  void pollPendingRequest(pendingRequestId, pendingRequestToken);
                }}
              >
                {bi("我已批准，立即检查", "I approved, check now")}
              </button>
            </div>
          </div>
        ) : null}

        {error ? <p className="error">{error}</p> : null}
        {note ? <p className="note">{note}</p> : null}

        <div className="pagination-actions mobile-sticky-actions">
          <button
            className="button"
            type="button"
            disabled={submitting || formInvalid || Boolean(pendingRequestId)}
            onClick={() => {
              void handleMobileLoginRequest();
            }}
          >
            {submitting ? bi("提交中...", "Submitting...") : bi("发起手机授权", "Request mobile approval")}
          </button>
          {compactViewport ? (
            <details className="login-desktop-entry">
              <summary>{bi("电脑端入口", "Desktop entry")}</summary>
              <button className="button button-secondary" type="submit" disabled={submitting || formInvalid}>
                {submitting
                  ? bi("登录中...", "Signing in...")
                  : bi("我是电脑端，直接登录", "I'm on desktop, direct sign-in")}
              </button>
            </details>
          ) : (
            <button className="button button-secondary" type="submit" disabled={submitting || formInvalid}>
              {submitting
                ? bi("登录中...", "Signing in...")
                : bi("我是电脑端，直接登录", "I'm on desktop, direct sign-in")}
            </button>
          )}
          {pendingRequestId ? (
            <button
              className="button button-secondary"
              type="button"
              disabled={cancelPending}
              onClick={() => {
                void handleCancelWaiting();
              }}
            >
              {cancelPending ? bi("取消中...", "Canceling...") : bi("取消等待", "Cancel waiting")}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}
