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

## 2. 登录（重点：手机端需要电脑授权）

当前默认安全策略是：

- **电脑本机（localhost）**可以直接登录。
- **手机端**不能直接拿账号密码进系统，必须走“请求 -> 电脑批准 -> 手机登录成功”流程。

请先在 `backend/.env` 中设置账号：

- `APP_USERNAME`
- `APP_PASSWORD`
- `APP_JWT_SECRET`（至少 32 字符）

关键安全配置（`backend/.env`）：

- `APP_REQUIRE_LOOPBACK_DIRECT_LOGIN=true`（默认开启，禁止非 localhost 直接登录）
- `APP_MOBILE_LOGIN_REQUEST_TTL_SECONDS=180`（手机授权请求有效期，单位秒）

### 2.1 手机端登录步骤（你需要按这个顺序操作）

1. **先在电脑端打开控制台并登录**
   - 地址：`http://localhost:3000`
   - 使用账号密码点击“电脑端直接登录”
2. **保持电脑端页面不关闭**
   - 左侧会看到“手机登录授权 / Mobile Login Approvals”面板
3. **手机访问前端地址**
   - 不能用 `localhost`，要用你电脑局域网 IP，例如：`http://192.168.1.10:3000`
4. **手机端输入同一套账号密码**
   - 点击“手机登录（需电脑授权）”
5. **回到电脑端批准请求**
   - 在“手机登录授权”里找到对应设备名/IP，点击“允许登录”
6. **手机端自动完成登录**
   - 手机会轮询授权状态，批准后会自动进入控制台

### 2.2 手机访问地址怎么配

如果手机打不开前端，优先检查：

- 前端是否以可被局域网访问的方式启动（通常默认可用）
- 手机和电脑是否在同一 Wi-Fi
- `NEXT_PUBLIC_API_BASE_URL` 是否指向手机可访问的后端地址（不是 `localhost`）

推荐启动方式示例：

```bash
# 终端 1：后端（监听所有网卡）
cd backend
source .venv/bin/activate
set -a && source .env && set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# 终端 2：前端（把 API 指向电脑局域网 IP）
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://192.168.1.10:8000 npm run dev:lan
```

然后手机打开：`http://192.168.1.10:3000`

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

### Q1-1: 手机端点“电脑端直接登录”报 403

这是预期行为。默认开启了 `APP_REQUIRE_LOOPBACK_DIRECT_LOGIN=true`，手机不允许直接登录。
请使用“手机登录（需电脑授权）”按钮，并在电脑端批准。

### Q1-2: 手机端显示“等待电脑端授权”但一直不成功

排查顺序：

1. 电脑端是否已经登录同一服务。
2. 电脑端“手机登录授权”面板是否出现该请求（设备名/IP）。
3. 请求是否超时（默认 180 秒）。
4. 手机和电脑是否在同一网络，前端/API 地址是否用电脑局域网 IP。
5. 若有反向代理，确认没有屏蔽轮询接口：
   - `GET /api/v1/auth/mobile/requests/{request_id}`
6. 如果出现 `Cannot find module './403.js'` 或类似 `.next/server` chunk 丢失错误：
   - 执行 `cd frontend && NEXT_PUBLIC_API_BASE_URL=http://你的电脑IP:8000 npm run dev:lan`
   - 该命令会先清理 `.next` 再启动，通常可直接恢复。

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

## 10. 指标脚本（验证优化效果）

已内置指标脚本：

`scripts/report_funnel_metrics.py`

运行示例（默认读取 `backend/pocket_codex.db`）：

```bash
cd /Users/slg/workspace/Pocket-Codex
python3 scripts/report_funnel_metrics.py
```

只看最近 7 天：

```bash
python3 scripts/report_funnel_metrics.py --since-days 7
```

当前脚本输出：

- 指标 2：创建任务到进入详情页中位时长（秒）
- 指标 3：用户找到目标任务的平均点击次数
