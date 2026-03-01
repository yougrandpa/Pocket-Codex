# Pocket Codex 本地启动与联调（MVP）

本文档用于在本地同时启动 backend/frontend，并完成一轮基础联调。

建议先执行一键初始化：

```bash
./scripts/setup_local_env.sh
```

## 1. 目录约定

- 后端目录：`backend/`
- 前端目录：`frontend/`
- API 前缀：`/api/v1`
- 默认后端地址：`http://localhost:8000`
- 默认前端地址：`http://localhost:3000`

## 2. 启动后端（FastAPI）

可选：先启动依赖（PostgreSQL + Redis）：

```bash
docker compose up -d postgres redis
```

在仓库根目录执行：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 可选：默认 sqlite 持久化，也可指定 PostgreSQL
# export DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/pocket_codex
# 可选：调节超时自动重试次数与退避
# export APP_MAX_AUTO_RETRIES=2
# export APP_RETRY_BACKOFF_BASE_SECONDS=1
# 可选：本地 worker 并发（建议 2~4）
# export APP_WORKER_CONCURRENCY=2
# 可选：启用 Redis 队列执行模式（多实例共享队列）
# export APP_EXECUTION_BACKEND=redis
# export REDIS_URL=redis://localhost:6379/0
# export REDIS_QUEUE_PREFIX=pocket_codex:tasks
# 可选：限制允许执行的工作目录（逗号分隔，推荐仅仓库根目录）
# export APP_WORKDIR_WHITELIST=/Users/slg/workspace/Pocket-Codex
# 可选：允许私网来源跨域（手机热点/局域网访问时建议开启，默认已开启）
# export APP_CORS_ALLOW_PRIVATE_NETWORK=true
# 可选：SSE 断线重放上限
# export APP_SSE_REPLAY_LIMIT=500
# 可选：启用本地 Codex 执行器（真正调用 CLI，而非模拟器）
# export APP_TASK_EXECUTOR=codex
# export APP_TASK_EXECUTOR=codex-cli
# export APP_CODEX_MIN_TIMEOUT_SECONDS=180
# export APP_CODEX_HARD_TIMEOUT_SECONDS=1800
# export CODEX_CLI_PATH=codex
# export CODEX_CLI_PATH=codex-cli
# export CODEX_FULL_AUTO=true
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动成功后可访问：

- 健康检查：`http://localhost:8000/healthz`
- OpenAPI：`http://localhost:8000/docs`

说明：`/healthz` 现在会返回 `task_executor` 和 `execution_backend`，便于确认后端实际运行模式。

## 3. 启动前端（Next.js）

新开一个终端，在仓库根目录执行：

```bash
cd frontend
npm install
npm run dev:lan
```

打开 `http://localhost:3000`，应能看到任务列表与创建任务入口。

说明：

- 前端默认会通过 Next.js rewrite 把 `/api/*` 和 `/healthz` 代理到 `http://127.0.0.1:8000`。
- 这样手机访问前端时，不需要浏览器直接访问 `localhost:8000`，可避免移动端登录 `load failed`。
- 如果你需要代理到其他后端地址，再设置（注意是 `BACKEND_BASE_URL`，不是 `NEXT_PUBLIC_API_BASE_URL`）：

```bash
BACKEND_BASE_URL=http://<backend-host>:8000 npm run dev:lan
```

## 4. 手工联调步骤

## 4.1 登录并获取 Token

```bash
source backend/.env
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$APP_USERNAME\",\"password\":\"$APP_PASSWORD\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

## 4.2 创建任务

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "读取 docs 并生成实现清单",
    "priority": 5,
    "workdir": "/workspace/Pocket-Codex"
  }'
```

预期：返回 `201`，状态为 `QUEUED`，随后由 worker 队列异步推进到 `RUNNING` / `SUCCEEDED`。如果运行超时，会进入 `TIMEOUT` 并按配置自动重试。

## 4.3 查看任务列表

```bash
curl "http://localhost:8000/api/v1/tasks?limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

## 4.4 查看任务详情

```bash
curl http://localhost:8000/api/v1/tasks/<TASK_ID> \
  -H "Authorization: Bearer $TOKEN"
```

## 4.5 订阅 SSE 事件

```bash
curl -N "http://localhost:8000/api/v1/stream?task_id=<TASK_ID>" \
  -H "Authorization: Bearer $TOKEN"
```

预期：可持续收到 `task.status.changed`、`task.log.appended` 等事件。

## 4.6 发送控制动作

取消任务：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"cancel"}'
```

重试任务：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"retry"}'
```

暂停任务：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"pause"}'
```

继续任务：

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/control \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"resume"}'
```

## 4.7 追加消息

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/message \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"补充：先输出风险项"}'
```

## 4.8 查看审计日志

```bash
curl "http://localhost:8000/api/v1/tasks/audit/logs?limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

## 4.9 手机登录授权流（API 手工联调）

说明：默认开启 `APP_REQUIRE_LOOPBACK_DIRECT_LOGIN=true`，非 localhost 直接登录会返回 `403`。

### 4.9.1 手机端发起登录请求（模拟）

```bash
REQ=$(curl -s -X POST http://localhost:8000/api/v1/auth/mobile/request \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$APP_USERNAME\",\"password\":\"$APP_PASSWORD\",\"device_name\":\"iphone-15-pro\"}")
echo "$REQ"
REQ_ID=$(echo "$REQ" | python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])')
REQ_TOKEN=$(echo "$REQ" | python3 -c 'import json,sys; print(json.load(sys.stdin)["request_token"])')
```

### 4.9.2 电脑端查看待审批请求（需要已登录 token）

```bash
curl "http://localhost:8000/api/v1/auth/mobile/pending" \
  -H "Authorization: Bearer $TOKEN"
```

### 4.9.3 电脑端批准请求

```bash
curl -X POST "http://localhost:8000/api/v1/auth/mobile/requests/$REQ_ID/approve" \
  -H "Authorization: Bearer $TOKEN"
```

### 4.9.4 手机端轮询状态并获取 token

```bash
curl "http://localhost:8000/api/v1/auth/mobile/requests/$REQ_ID" \
  -H "X-Mobile-Request-Token: $REQ_TOKEN"
```

如果已批准，响应里会包含：

- `access_token`
- `refresh_token`
- `status=COMPLETED`

## 5. 前后端对齐检查单

- 状态字段是否仅使用 `TaskStatus` 枚举。
- 时间字段是否为 ISO 8601 UTC，示例：`2026-02-28T15:04:05Z`。
- 任务控制接口是否支持 `pause` / `resume` / `cancel` / `retry`。
- SSE `event` 名称与 `data.event_type` 是否一致。
- 前端 API Base URL 是否正确读取 `NEXT_PUBLIC_API_BASE_URL`。

## 6. 常见问题（FAQ）

Q1: 前端报跨域错误（CORS）怎么办？  
A1: 在后端 FastAPI 配置中开启本地来源（至少包含 `http://localhost:3000`）。

Q1-1: 手机端登录报 `403 Direct login is only allowed from localhost`？  
A1-1: 这是默认安全策略，手机端应走 `/api/v1/auth/mobile/request` + 电脑批准流程；或临时将 `APP_REQUIRE_LOOPBACK_DIRECT_LOGIN=false`（不推荐）。

Q2: `curl -N` 看不到 SSE 输出？  
A2: 确认后端返回 `text/event-stream`，并且创建任务后确实产生了事件；必要时先不加 `task_id` 订阅全量流。

Q3: 任务一直停在 `QUEUED`？  
A3: 检查模拟执行器异步任务是否启动；确认应用启动日志里无异常。

Q4: `pause` / `resume` 调用失败？  
A4: 先确认任务当前状态（`RUNNING` 才能 `pause`，`WAITING_INPUT` 才能 `resume`）；状态不匹配会返回业务错误。

Q5: 前端创建成功但列表不刷新？  
A5: 优先检查轮询或刷新逻辑，其次检查 SSE 订阅是否连接成功。

Q6: 如何快速确认本地环境是否已就绪？  
A6: 运行 `./scripts/verify_local_env.sh`，会执行后端编译+API 烟测以及前端构建。

Q7: 启动前端时报 `Cannot find module './xxx.js'`（来自 `.next/server/webpack-runtime.js`）怎么办？  
A7: 这是 Next.js 本地缓存损坏或增量构建残留导致。执行 `cd frontend && npm run dev:lan`（会先清理 `.next` 再启动），或 `npm run dev:reset` 即可。

Q8: 我发送了追加消息，但任务没有执行新命令？  
A8: 如果后端是 `APP_TASK_EXECUTOR=simulator`，任务只是模拟执行，不会真正调用 CLI。请切换为 `APP_TASK_EXECUTOR=codex` 或 `APP_TASK_EXECUTOR=codex-cli` 并重启后端。可先请求 `GET /healthz`，确认返回 `task_executor=codex` 或 `task_executor=codex-cli`。当前版本在任务已结束后追加消息时，会自动触发一次重跑（`RETRYING -> QUEUED`）。

Q9: 日志提示 `codex cli not found at 'codex'` 怎么办？  
A9: 先查看 `GET /healthz` 返回的 `codex_cli_path` 和 `codex_cli_exists`。如果 `codex_cli_exists=false`，请在 `backend/.env` 里设置绝对路径，例如 `CODEX_CLI_PATH=/Applications/Codex.app/Contents/Resources/codex`，然后重启后端。

Q10: 为什么总是 `codex execution timeout`？  
A10: 默认 `20s` 对真实 Codex 往往太短。当前版本使用双超时机制：空闲超时（`APP_CODEX_MIN_TIMEOUT_SECONDS`，默认 `180s`，任务有持续输出就不会触发）+ 硬超时（`APP_CODEX_HARD_TIMEOUT_SECONDS`，默认 `1800s`）。可在 `GET /healthz` 查看这两个值，必要时上调后重启后端。

Q11: follow-up 消息会覆盖原始 prompt 吗？  
A11: 不会。当前版本会保留原始 `prompt`，并在执行时把最近 follow-up 消息追加到上下文，同时每次重跑会生成新的 `run_id`，便于前端追踪历史。

Q12: SSE 断线后能补发遗漏事件吗？  
A12: 支持。服务端支持 `last_event_id` / `Last-Event-ID` 断点续传，客户端会自动携带并请求重放最近事件（受 `APP_SSE_REPLAY_LIMIT` 限制）。

## 7. 指标报表脚本

用于验证前端转化优化（已覆盖指标 2 和指标 3）：

```bash
cd /Users/slg/workspace/Pocket-Codex
python3 scripts/report_funnel_metrics.py
```

可选参数：

- `--db /path/to/pocket_codex.db`
- `--since-days 7`
