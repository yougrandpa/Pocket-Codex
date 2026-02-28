import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pocket Codex",
  description: "Mobile-first remote dashboard for Codex tasks"
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>
        <main className="app-shell">
          <header className="app-header">
            <p className="eyebrow">Pocket Codex</p>
            <h1>Remote Task Control</h1>
            <p className="muted">Monitor and operate Codex jobs from your phone.</p>
          </header>
          {children}
        </main>
      </body>
    </html>
  );
}
