"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";

export function AppHeaderShell() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <header className="app-header">
        <p className="muted">Loading...</p>
      </header>
    );
  }

  return <AppHeader />;
}
