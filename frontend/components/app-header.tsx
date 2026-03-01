"use client";

import { bi, useLanguage } from "@/lib/i18n";

export function AppHeader() {
  const [language, setLanguage] = useLanguage();
  const nextLanguage = language === "zh" ? "en" : "zh";

  return (
    <header className="app-header">
      <div className="app-header-top">
        <div>
          <p className="eyebrow">Pocket Codex</p>
          <h1>{bi("远程任务控制", "Remote Task Control")}</h1>
        </div>
        <button
          className="button button-secondary lang-switch-button"
          type="button"
          onClick={() => setLanguage(nextLanguage)}
        >
          {language === "zh" ? "English" : "中文"}
        </button>
      </div>
      <p className="muted">
        {bi("用手机监控并操作 Codex 任务。", "Monitor and operate Codex jobs from your phone.")}
      </p>
    </header>
  );
}
