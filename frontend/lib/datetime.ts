import { getLanguage } from "@/lib/i18n";

const DATE_TIME_FORMATTER_CACHE = new Map<string, Intl.DateTimeFormat>();
const TIME_FORMATTER_CACHE = new Map<string, Intl.DateTimeFormat>();

function localeForCurrentLanguage(): string {
  return getLanguage() === "en" ? "en-US" : "zh-CN";
}

function getDateTimeFormatter(): Intl.DateTimeFormat {
  const locale = localeForCurrentLanguage();
  const key = `datetime:${locale}`;
  let formatter = DATE_TIME_FORMATTER_CACHE.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    DATE_TIME_FORMATTER_CACHE.set(key, formatter);
  }
  return formatter;
}

function getTimeFormatter(): Intl.DateTimeFormat {
  const locale = localeForCurrentLanguage();
  const key = `time:${locale}`;
  let formatter = TIME_FORMATTER_CACHE.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    TIME_FORMATTER_CACHE.set(key, formatter);
  }
  return formatter;
}

function parseDate(value?: string | null): Date | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return null;
  }
  return parsed;
}

export function formatDateTime(value?: string | null, fallback = "-"): string {
  if (!value) {
    return fallback;
  }
  const parsed = parseDate(value);
  if (!parsed) {
    return value;
  }
  return getDateTimeFormatter().format(parsed);
}

export function formatTime(value?: string | null, fallback = "-"): string {
  if (!value) {
    return fallback;
  }
  const parsed = parseDate(value);
  if (!parsed) {
    return value;
  }
  return getTimeFormatter().format(parsed);
}
