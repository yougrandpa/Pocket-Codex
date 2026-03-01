import { useEffect, useState } from "react";

export type TaskStatusLabel =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_INPUT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "TIMEOUT"
  | "RETRYING";

export type Language = "zh" | "en";

const LANGUAGE_STORAGE_KEY = "pocket_codex_language";
let currentLanguage: Language = "zh";
let languageLoaded = false;
const listeners = new Set<(language: Language) => void>();

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function notifyLanguageChange(): void {
  for (const listener of listeners) {
    listener(currentLanguage);
  }
}

function applyLanguage(language: Language): void {
  currentLanguage = language;
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
}

function loadLanguageFromStorage(): void {
  if (!isBrowser() || languageLoaded) {
    return;
  }
  languageLoaded = true;
  const saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (saved === "en" || saved === "zh") {
    currentLanguage = saved;
  }
  document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : "en";
}

export function getLanguage(): Language {
  loadLanguageFromStorage();
  return currentLanguage;
}

export function setLanguage(language: Language): void {
  loadLanguageFromStorage();
  if (language === currentLanguage) {
    return;
  }
  applyLanguage(language);
  notifyLanguageChange();
}

export function useLanguage(): [Language, (language: Language) => void] {
  const [language, setLanguageState] = useState<Language>(getLanguage());

  useEffect(() => {
    loadLanguageFromStorage();
    setLanguageState(currentLanguage);
    const handler = (nextLanguage: Language) => {
      setLanguageState(nextLanguage);
    };
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, []);

  return [language, setLanguage];
}

export function bi(zh: string, en: string): string {
  return getLanguage() === "en" ? en : zh;
}

export function statusText(status: TaskStatusLabel): string {
  const map: Record<TaskStatusLabel, string> = {
    QUEUED: bi("排队中", "Queued"),
    RUNNING: bi("执行中", "Running"),
    WAITING_INPUT: bi("等待输入", "Waiting Input"),
    SUCCEEDED: bi("成功", "Succeeded"),
    FAILED: bi("失败", "Failed"),
    CANCELED: bi("已取消", "Canceled"),
    TIMEOUT: bi("超时", "Timeout"),
    RETRYING: bi("重试中", "Retrying")
  };
  return map[status];
}
