# Pocket Codex 本地启动与联调（MVP）

本文档用于在本地同时启动 backend/frontend，并完成一轮基础联调。

## 1. 目录约定

- 后端目录：`backend/`
- 前端目录：`frontend/`
- API 前缀：`/api/v1`
- 默认后端地址：`http://localhost:8000`
- 默认前端地址：`http://localhost:3000`

## 2. 启动后端（FastAPI）

在仓库根目录执行：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动成功后可访问：

- 健康检查：`http://localhost:8000/healthz`
- OpenAPI：`http://localhost:8000/docs`

## 3. 启动前端（Next.js）

新开一个终端，在仓库根目录执行：

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

打开 `http://localhost:3000`，应能看到任务列表与创建任务入口。

## 4. 手工联调步骤

## 4.1 创建任务

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "读取 docs 并生成实现清单",
    "priority": 5,
    "workdir": "/workspace/Pocket-Codex"
  }'
```

预期：返回 `201`，状态为 `QUEUED`，并在短时间后推进到 `RUNNING` / `SUCCEEDED`（模拟执行器）。

## 4.2 查看任务列表

```bash
curl "http://localhost:8000/api/v1/tasks?limit=20&offset=0"
```

## 4.3 查看任务详情

```bash
curl http://localhost:8000/api/v1/tasks/<TASK_ID>
```

## 4.4 订阅 SSE 事件

```bash
curl -N "http://localhost:8000/api/v1/stream?task_id=<TASK_ID>"
```

预期：可持续收到 `task.status.changed`、`task.log.appended` 等事件。

## 4.5 发送控制动作

取消任务：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/control \
  -H "Content-Type: application/json" \
  -d '{"action":"cancel"}'
```

重试任务：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/control \
  -H "Content-Type: application/json" \
  -d '{"action":"retry"}'
```

## 4.6 追加消息

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/message \
  -H "Content-Type: application/json" \
  -d '{"message":"补充：先输出风险项"}'
```

## 5. 前后端对齐检查单

- 状态字段是否仅使用 `TaskStatus` 枚举。
- 时间字段是否为 ISO 8601 UTC，示例：`2026-02-28T15:04:05Z`。
- 任务控制接口是否支持 `cancel` / `retry`，`pause` / `resume` 可返回 `501`。
- SSE `event` 名称与 `data.event_type` 是否一致。
- 前端 API Base URL 是否正确读取 `NEXT_PUBLIC_API_BASE_URL`。

## 6. 常见问题（FAQ）

Q1: 前端报跨域错误（CORS）怎么办？  
A1: 在后端 FastAPI 配置中开启本地来源（至少包含 `http://localhost:3000`）。

Q2: `curl -N` 看不到 SSE 输出？  
A2: 确认后端返回 `text/event-stream`，并且创建任务后确实产生了事件；必要时先不加 `task_id` 订阅全量流。

Q3: 任务一直停在 `QUEUED`？  
A3: 检查模拟执行器异步任务是否启动；确认应用启动日志里无异常。

Q4: `pause` / `resume` 调用失败？  
A4: 这是 MVP 预期行为，可返回 `501` 占位，先保证 `cancel` / `retry` 可用。

Q5: 前端创建成功但列表不刷新？  
A5: 优先检查轮询或刷新逻辑，其次检查 SSE 订阅是否连接成功。
