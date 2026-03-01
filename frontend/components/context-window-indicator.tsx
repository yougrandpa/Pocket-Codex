"use client";

import { useMemo, useState } from "react";
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
  const [open, setOpen] = useState(false);
  const context = useMemo(() => formatContextUsage(usedTokens, totalTokens), [usedTokens, totalTokens]);

  return (
    <div className="context-window-indicator">
      <button
        className="context-window-toggle"
        type="button"
        aria-label={bi("查看背景信息窗口使用率", "View context window usage")}
        onClick={() => setOpen((value) => !value)}
      >
        i
      </button>
      {open ? (
        <div className="context-window-popover" role="dialog" aria-label={bi("背景信息窗口", "Context Window")}> 
          <p className="context-window-title">{bi("背景信息窗口", "Context Window")}</p>
          <p className="context-window-percent">
            {context.percent !== null ? `${context.percent}% ${bi("已用", "used")}` : bi("未上报", "not reported")}
          </p>
          <p className="context-window-detail">
            {bi("已用", "Used")} {context.usedText} {bi("标记", "tokens")}，{bi("共", "of")} {context.totalText}
          </p>
        </div>
      ) : null}
    </div>
  );
}
