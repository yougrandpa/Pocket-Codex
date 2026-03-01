import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { AppHeader } from "@/components/app-header";

export const metadata: Metadata = {
  title: "Pocket Codex Dashboard",
  description: "Mobile-first remote dashboard for Codex tasks"
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN">
      <body>
        <main className="app-shell">
          <AppHeader />
          {children}
        </main>
      </body>
    </html>
  );
}
