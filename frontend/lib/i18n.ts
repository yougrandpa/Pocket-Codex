export type TaskStatusLabel =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_INPUT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "TIMEOUT"
  | "RETRYING";

export function bi(zh: string, en: string): string {
  return `${zh} / ${en}`;
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
