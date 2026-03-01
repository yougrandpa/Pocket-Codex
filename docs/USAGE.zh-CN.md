# Pocket Codex 使用说明（中文）

本说明面向日常使用者，覆盖登录、创建任务、实时查看、控制任务和排查问题。

## 1. 使用前准备

建议先运行：

```bash
./scripts/setup_local_env.sh
./scripts/verify_local_env.sh
```

然后分别启动后端与前端：

```bash
# 终端 1
cd backend
source .venv/bin/activate
set -a && source .env && set +a
uvicorn app.main:app --reload --port 8000
```

```bash
# 终端 2
cd frontend
npm run dev
```

访问：`http://localhost:3000`

## 2. 登录

首页会先显示登录卡片，输入账号后进入控制台。

- 默认账号：`admin`
- 默认密码：`admin123`

建议在 `backend/.env` 中修改：

- `APP_USERNAME`
- `APP_PASSWORD`
- `APP_JWT_SECRET`（至少 32 字符）

## 3. 创建任务

在 Dashboard 的 `Create Task` 区域填写：

- `Prompt`：任务描述
- `Priority`：优先级（数值越大越优先，仅用于展示和策略扩展）
- `Timeout (sec)`：任务超时阈值
- `Workdir`：可选工作目录

提交后任务会进入：

`QUEUED -> RUNNING -> SUCCEEDED`

如果超时可能进入：

`TIMEOUT -> RETRYING -> QUEUED`

## 4. 查看任务与实时事件

### 4.1 任务列表

任务列表会显示状态标签、最后更新时间和详情入口。

### 4.2 任务详情

详情页包含：

- 任务元信息（状态、超时、时间戳、工作目录）
- 控制动作按钮
- 追加消息输入框
- 最近事件流（状态变化、日志、摘要更新）

### 4.3 站内通知

首页 `Notifications` 区域会实时显示来自 SSE 的最新事件。

## 5. 控制动作

可用动作受当前状态限制：

- `RUNNING`：可 `pause` / `cancel`
- `WAITING_INPUT`：可 `resume` / `cancel`
- `FAILED` / `CANCELED` / `TIMEOUT`：可 `retry`

常见返回语义：

- `accepted: true`：动作被接受
- `accepted: false`：状态不匹配（例如非运行态执行 `pause`）

## 6. 追加消息

在详情页 `Append instruction` 输入框提交补充指令后：

- 后端记录 `task.message.appended` 事件
- 审计日志记录 `task.message.append`

## 7. 审计日志

首页 `Audit Logs` 会显示最近关键操作，包括：

- 登录成功/失败
- 任务创建
- 控制动作
- 追加消息

也可以通过 API 查询：

`GET /api/v1/tasks/audit/logs?limit=20&offset=0`

## 8. 可选运行模式

### 8.1 本地队列（默认）

`APP_EXECUTION_BACKEND=local`

- 无外部依赖
- 适合单实例开发调试

### 8.2 Redis 队列

`APP_EXECUTION_BACKEND=redis`

并配置：

- `REDIS_URL`
- `REDIS_QUEUE_PREFIX`

适合多实例共享执行队列。

## 9. 常见问题

### Q1: 登录报 401

检查 `backend/.env` 的 `APP_USERNAME/APP_PASSWORD` 是否与前端输入一致。

### Q2: 任务长期停在 `QUEUED`

检查后端日志是否有 worker 报错；确认执行后端配置（`local/redis`）和依赖服务状态。

### Q3: 实时不更新

确认后端可访问 `/api/v1/stream`，并检查浏览器控制台是否有 SSE 断连错误。

### Q4: 构建失败

执行：

```bash
./scripts/verify_local_env.sh
```

根据输出定位后端依赖或前端构建问题。
