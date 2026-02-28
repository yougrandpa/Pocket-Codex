# Pocket Codex API Contract（MVP v1）

本文档用于前后端联调，约定统一前缀为 `/api/v1`，时间字段统一使用 ISO 8601 UTC（示例：`2026-02-28T15:04:05Z`）。

## 1. 状态与枚举

## 0. 鉴权

- 除 `POST /api/v1/auth/login` 与 `POST /api/v1/auth/refresh` 外，其余接口均需鉴权。
- Header 方式：`Authorization: Bearer <access_token>`
- SSE（浏览器 `EventSource`）可使用查询参数：`/api/v1/stream?access_token=<access_token>`

### 0.1 登录

`POST /api/v1/auth/login`

```json
{
  "username": "admin",
  "password": "admin123"
}
```

响应（`200`）：

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "expires_in_seconds": 1800
}
```

### 0.2 刷新令牌

`POST /api/v1/auth/refresh`

```json
{
  "refresh_token": "<jwt>"
}
```

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

- `pause`
- `resume`
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
  "timeout_seconds": 20,
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
  "last_heartbeat_at": null,
  "paused_at": null,
  "retry_count": 0,
  "timeout_seconds": 20
}
```

说明：当前实现使用队列 worker，异步推进任务。若运行时间超过 `timeout_seconds`，会进入 `TIMEOUT`，并按配置触发自动重试。

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
      "last_heartbeat_at": "2026-02-28T14:10:02Z",
      "paused_at": null,
      "retry_count": 0,
      "timeout_seconds": 20
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
    "last_heartbeat_at": "2026-02-28T14:10:08Z",
    "paused_at": null,
    "retry_count": 0,
    "timeout_seconds": 20
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

暂停动作响应（`200`）：

```json
{
  "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "action": "pause",
  "accepted": true,
  "status": "WAITING_INPUT",
  "message": "task paused"
}
```

继续动作响应（`200`）：

```json
{
  "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
  "action": "resume",
  "accepted": true,
  "status": "RUNNING",
  "message": "task resumed"
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

## 3.6 审计日志

`GET /api/v1/tasks/audit/logs?limit=20&offset=0`

响应（`200`）：

```json
{
  "total": 3,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": 3,
      "timestamp": "2026-02-28T14:11:12Z",
      "actor": "admin",
      "action": "task.control.pause",
      "task_id": "task_01JYQD0H3YQ4FQ3EVNVB83BP5A",
      "detail": {
        "accepted": true,
        "message": "task paused"
      }
    }
  ]
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

`GET /api/v1/stream?task_id={id}&access_token={token}`（`task_id` 可选，不传时返回全量任务事件）

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
- `422 VALIDATION_ERROR`：请求体或参数校验失败。
