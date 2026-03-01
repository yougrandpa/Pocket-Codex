"use client";

import { useMemo } from "react";
import { bi } from "@/lib/i18n";
import { formatContextUsage } from "@/lib/usage";

interface ContextWindowIndicatorProps {
  usedTokens?: number | null;
  totalTokens?: number | null;
}

export function ContextWindowIndicator({
  usedTokens = null,
  totalTokens = null
}: ContextWindowIndicatorProps) {
  const context = useMemo(() => formatContextUsage(usedTokens, totalTokens), [usedTokens, totalTokens]);

  return (
    <div className="context-window-indicator">
      <span
        className="context-window-toggle"
        tabIndex={0}
        role="img"
        aria-label={bi("背景信息窗口提示", "Context window hint")}
      >
        i
      </span>
      <div className="context-window-popover" role="dialog" aria-label={bi("背景信息窗口", "Context Window")}>
        <p className="context-window-title">{bi("背景信息窗口", "Context Window")}</p>
        <p className="context-window-percent">
          {context.percent !== null ? `${context.percent}% ${bi("已用", "used")}` : bi("未上报", "not reported")}
        </p>
        <p className="context-window-detail">
          {bi("已用", "Used")} {context.usedText} {bi("标记", "tokens")}，{bi("共", "of")} {context.totalText}
        </p>
      </div>
    </div>
  );
}
