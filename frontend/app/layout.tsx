import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { bi } from "@/lib/i18n";

export const metadata: Metadata = {
  title: bi("Pocket Codex 中文优先控制台", "Pocket Codex Mobile Dashboard"),
  description: bi(
    "移动端优先的 Codex 远程任务控制台",
    "Mobile-first remote dashboard for Codex tasks"
  )
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN">
      <body>
        <main className="app-shell">
          <header className="app-header">
            <p className="eyebrow">Pocket Codex</p>
            <h1>{bi("远程任务控制", "Remote Task Control")}</h1>
            <p className="muted">
              {bi("用手机监控并操作 Codex 任务。", "Monitor and operate Codex jobs from your phone.")}
            </p>
          </header>
          {children}
        </main>
      </body>
    </html>
  );
}
