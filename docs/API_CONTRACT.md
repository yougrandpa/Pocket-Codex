# Pocket Codex API Contract（MVP v1）

本文档用于前后端联调，约定统一前缀为 `/api/v1`，时间字段统一使用 ISO 8601 UTC（示例：`2026-02-28T15:04:05Z`）。

## 1. 状态与枚举

### 1.1 任务状态 `TaskStatus`

- `QUEUED`：已入队，等待执行。
- `RUNNING`：执行中。
- `WAITING_INPUT`：等待用户追加输入。
- `RETRYING`：系统重试中。
- `SUCCEEDED`：成功完成。
- `FAILED`：执行失败。
- `CANCELED`：已取消。
- `TIMEOUT`：执行超时。

### 1.2 控制动作 `TaskControlAction`

- `pause`（MVP 占位，允许返回 `501`）
- `resume`（MVP 占位，允许返回 `501`）
- `cancel`
- `retry`

### 1.3 事件类型 `TaskEventType`

- `task.status.changed`
- `task.log.appended`
- `task.message.appended`
- `task.summary.updated`

## 2. 核心对象

### 2.1 Task

```json
{
  "id": "task_01JYQCT77QEFG80A2W87GQ6B7K",
  "prompt": "扫描 backend 目录并给出错误摘要",
  "status": "RUNNING",
  "priority": 5,
  "workdir": "/workspace/Pocket-Codex",
  "summary": "正在扫描 Python 文件",
  "created_at": "2026-02-28T14:00:00Z",
  "updated_at": "2026-02-28T14:00:03Z",
  "started_at": "2026-02-28T14:00:02Z",
  "finished_at": null,
  "last_heartbeat_at": "2026-02-28T14:00:03Z"
}
```

### 2.2 TaskEvent

```json
{
  "id": "evt_01JYQCV5HP8S2D2QH5KM1MT8X2",
  "task_id": "task_01JYQCT77QEFG80A2W87GQ6B7K",
  "seq": 12,
  "event_type": "task.log.appended",
  "timestamp": "2026-02-28T14:00:03Z",
  "payload": {
    "level": "info",
    "message": "scan started"
  }
}
```

## 3. REST 端点

## 3.1 创建任务

`POST /api/v1/tasks`

请求：

```json
{
  "prompt": "读取 docs 并生成实现清单",
  "priority": 5,
  "workdir": "/workspace/Pocket-Codex"
}
```

响应（`201`）：

```json
{
  "id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "prompt": "读取 docs 并生成实现清单",
  "status": "QUEUED",
  "priority": 5,
  "workdir": "/workspace/Pocket-Codex",
  "summary": null,
  "created_at": "2026-02-28T14:10:00Z",
  "updated_at": "2026-02-28T14:10:00Z",
  "started_at": null,
  "finished_at": null,
  "last_heartbeat_at": null
}
```

说明：MVP 模拟执行器会异步推进 `QUEUED -> RUNNING -> SUCCEEDED`，用于前端联调。

## 3.2 任务列表

`GET /api/v1/tasks?status=RUNNING&limit=20&offset=0`

响应（`200`）：

```json
{
  "items": [
    {
      "id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
      "prompt": "读取 docs 并生成实现清单",
      "status": "RUNNING",
      "priority": 5,
      "workdir": "/workspace/Pocket-Codex",
      "summary": "正在执行",
      "created_at": "2026-02-28T14:10:00Z",
      "updated_at": "2026-02-28T14:10:02Z",
      "started_at": "2026-02-28T14:10:01Z",
      "finished_at": null,
      "last_heartbeat_at": "2026-02-28T14:10:02Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

## 3.3 任务详情

`GET /api/v1/tasks/{id}`

响应（`200`）：

```json
{
  "task": {
    "id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
    "prompt": "读取 docs 并生成实现清单",
    "status": "SUCCEEDED",
    "priority": 5,
    "workdir": "/workspace/Pocket-Codex",
    "summary": "任务完成，共处理 3 个文档",
    "created_at": "2026-02-28T14:10:00Z",
    "updated_at": "2026-02-28T14:10:08Z",
    "started_at": "2026-02-28T14:10:01Z",
    "finished_at": "2026-02-28T14:10:08Z",
    "last_heartbeat_at": "2026-02-28T14:10:08Z"
  },
  "events": [
    {
      "id": "evt_01",
      "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
      "seq": 1,
      "event_type": "task.status.changed",
      "timestamp": "2026-02-28T14:10:01Z",
      "payload": {
        "from": "QUEUED",
        "to": "RUNNING"
      }
    }
  ]
}
```

## 3.4 任务控制

`POST /api/v1/tasks/{id}/control`

请求：

```json
{
  "action": "cancel"
}
```

成功响应（`200`）：

```json
{
  "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "action": "cancel",
  "accepted": true,
  "status": "CANCELED",
  "message": "task canceled"
}
```

重试请求：

```json
{
  "action": "retry"
}
```

重试响应（`200`）：

```json
{
  "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "action": "retry",
  "accepted": true,
  "status": "RETRYING",
  "message": "task scheduled for retry"
}
```

占位动作响应（`501`）：

```json
{
  "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "action": "pause",
  "accepted": false,
  "status": "RUNNING",
  "message": "pause is not implemented in MVP"
}
```

## 3.5 追加消息

`POST /api/v1/tasks/{id}/message`

请求：

```json
{
  "message": "补充：优先输出风险项"
}
```

响应（`200`）：

```json
{
  "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "message_id": "msg_01JYQD5J0T2J9YF2W25D72QN2A",
  "accepted": true,
  "created_at": "2026-02-28T14:11:00Z"
}
```

## 4. SSE 事件流

`GET /api/v1/stream?task_id={id}`（`task_id` 可选，不传时返回全量任务事件）

响应头建议：

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`

事件格式：

```text
id: 101
event: task.status.changed
data: {"task_id":"task_01JYQD0H3YQ4FQ3EVNVB83BP5A","seq":101,"timestamp":"2026-02-28T14:10:01Z","payload":{"from":"QUEUED","to":"RUNNING"}}

id: 102
event: task.log.appended
data: {"task_id":"task_01JYQD0H3YQ4FQ3EVNVB83BP5A","seq":102,"timestamp":"2026-02-28T14:10:03Z","payload":{"level":"info","message":"scan started"}}
```

保活包（建议每 15-30 秒）：

```text
: ping
```

## 5. 错误结构

统一错误响应（建议）：

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "task does not exist",
    "details": null
  }
}
```

常见错误码：

- `400 BAD_REQUEST`：参数不合法。
- `404 TASK_NOT_FOUND`：任务不存在。
- `409 INVALID_STATE_TRANSITION`：非法状态流转。
- `501 NOT_IMPLEMENTED`：MVP 占位能力未实现（例如 pause/resume）。
