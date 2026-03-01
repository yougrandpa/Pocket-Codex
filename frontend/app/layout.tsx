import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { AppHeaderShell } from "@/components/app-header-shell";

export const metadata: Metadata = {
  title: "Pocket Codex Dashboard",
  description: "Mobile-first remote dashboard for Codex tasks"
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <main className="app-shell">
          <AppHeaderShell />
          {children}
        </main>
      </body>
    </html>
  );
}
