"use client";

import { FormEvent, useMemo, useState } from "react";
import { login } from "@/lib/api";
import { bi } from "@/lib/i18n";

interface LoginPanelProps {
  onLoggedIn: () => void;
}

export function LoginPanel({ onLoggedIn }: LoginPanelProps) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const disabled = useMemo(
    () => submitting || username.trim().length === 0 || password.trim().length === 0,
    [password, submitting, username]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (disabled) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
      onLoggedIn();
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : bi("登录失败。", "Sign in failed.")
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel animate-rise">
      <div className="panel-title-row">
        <h2 className="panel-title">{bi("登录", "Sign In")}</h2>
        <span className="chip">{bi("单用户", "Single User")}</span>
      </div>
      <form className="stack" onSubmit={handleSubmit}>
        <label className="field">
          <span>{bi("用户名", "Username")}</span>
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>{bi("密码", "Password")}</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error ? <p className="error">{error}</p> : null}
        <button className="button" type="submit" disabled={disabled}>
          {submitting ? bi("登录中...", "Signing in...") : bi("登录", "Sign In")}
        </button>
      </form>
    </section>
  );
}
