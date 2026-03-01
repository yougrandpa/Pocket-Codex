export function formatTokenCompact(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "-";
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}m`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}k`;
  }
  return `${Math.round(value)}`;
}

export function formatTokenDetailed(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return "-";
  }
  return Math.round(value).toLocaleString();
}

export function formatUsd(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "$0.00";
  }
  if (value < 0.01) {
    return `$${value.toFixed(4)}`;
  }
  return `$${value.toFixed(2)}`;
}

export function formatUsdDetailed(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "$0.000000";
  }
  return `$${value.toFixed(6)}`;
}

export function formatContextUsage(
  usedTokens: number | null | undefined,
  totalTokens: number | null | undefined
): {
  percent: number | null;
  usedText: string;
  totalText: string;
} {
  const used = typeof usedTokens === "number" && Number.isFinite(usedTokens) ? usedTokens : null;
  const total = typeof totalTokens === "number" && Number.isFinite(totalTokens) ? totalTokens : null;
  const percent =
    used !== null && total !== null && total > 0 ? Math.max(0, Math.min(100, Math.round((used / total) * 100))) : null;

  return {
    percent,
    usedText: formatTokenCompact(used),
    totalText: formatTokenCompact(total)
  };
}
