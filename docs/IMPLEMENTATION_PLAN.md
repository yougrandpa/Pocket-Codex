# Pocket Codex 实现方案（MVP 执行版）

## 1. 实现目标

基于 `docs/PROJECT_PLAN.md` 的 8 周路线，先完成一个可上线灰度的 MVP：

1. 手机端可查看任务列表、任务详情、实时日志。
2. 手机端可创建任务、追加指令、执行控制动作（暂停/继续/取消/重试）。
3. 服务端具备可审计的状态机、实时事件流、基础鉴权与重试能力。
4. 达到首批验收指标：2 秒内状态同步、失败可追溯、支持基础并发。

## 2. 技术选型落地

为降低首版复杂度并提升交付速度，采用如下确定方案：

- 前端：Next.js 15 + TypeScript + App Router（移动端优先）。
- 后端：FastAPI + SQLAlchemy + Pydantic。
- 实时：SSE（MVP 首选，后续按需升级 WebSocket）。
- 队列：先实现应用内异步执行器与重试框架；二期替换为 Redis + Celery。
- 数据库：PostgreSQL（开发阶段支持 SQLite 本地快速启动）。
- 鉴权：JWT Access + Refresh（先单用户模型）。

## 3. 系统架构（MVP）

```text
Mobile Web (Next.js)
   ├─ Task List / Task Detail / Composer
   ├─ SSE Client (status + logs)
   └─ Auth Session (JWT)

API Layer (FastAPI)
   ├─ /tasks CRUD + control + message
   ├─ /stream SSE event fan-out
   ├─ Auth middleware (JWT)
   └─ Audit logging

Task Runtime
   ├─ Task state machine
   ├─ Codex executor adapter
   ├─ Heartbeat + timeout monitor
   └─ Retry orchestrator

Storage
   ├─ PostgreSQL: tasks / events / audits
   └─ (Phase 2) Redis: queue + pubsub + retry backoff
```

## 4. 数据与状态模型

### 4.1 状态机

`QUEUED -> RUNNING -> WAITING_INPUT -> SUCCEEDED | FAILED | CANCELED`

补充：`TIMEOUT`、`RETRYING`

### 4.2 关键实体

- `tasks`：任务主表（prompt、status、priority、workdir、timestamps、summary）。
- `task_events`：状态流转与日志事件（event_seq、event_type、payload）。
- `task_messages`：用户追加指令。
- `task_controls`：控制动作与操作结果。
- `audit_logs`：鉴权与关键动作审计。

## 5. API 契约（MVP v1）

- `POST /api/v1/tasks`：创建任务。
- `GET /api/v1/tasks`：分页列表（按状态筛选）。
- `GET /api/v1/tasks/{id}`：详情。
- `POST /api/v1/tasks/{id}/control`：`pause|resume|cancel|retry`。
- `POST /api/v1/tasks/{id}/message`：追加用户消息。
- `GET /api/v1/stream?task_id=`：SSE 事件流。
- `POST /api/v1/auth/login` / `POST /api/v1/auth/refresh`：鉴权（单用户）。

## 6. 执行计划（按周）

### 第 1 周（当前启动）

- 产出实现方案与 API 契约。
- 初始化仓库结构（frontend/backend/shared docs）。
- 完成状态机定义与后端基础模型。

### 第 2-3 周

- 实现任务执行器抽象（可替换 Codex 适配器）。
- 打通任务创建、执行、控制、日志落库。
- 接入基础鉴权与审计。

### 第 4 周

- SSE 实时推送（状态 + 增量日志 + 断线重连游标）。
- 前端实时订阅与任务详情联动。

### 第 5 周

- 完成移动端任务列表、详情、创建与控制闭环。
- 完成首轮可用性修正（iOS Safari）。

### 第 6-8 周

- 通知能力、稳定性、压测与发布准备。
- 二期规划：Redis/Celery、WKWebView 壳、推送增强。

## 7. 当前执行拆分（并行）

并行工作流：

1. 后端代理：FastAPI 工程骨架、状态机、任务 API 与 SSE 基础实现。
2. 前端代理：Next.js 移动端骨架、任务列表/详情/创建页面。
3. 文档代理：补齐 API 文档与本地启动联调说明。

集成策略：

- 统一使用 `/api/v1` 前缀。
- 统一状态枚举、字段命名与时间格式（ISO 8601 UTC）。
- 前后端通过 `openapi.json` 和示例 payload 对齐。

## 8. Definition of Done（本轮）

本轮完成判定：

- 仓库具备可运行的前后端基础工程。
- 后端能创建任务、状态流转、输出 SSE 事件。
- 前端可查看任务列表、详情并触发创建任务。
- 文档包含启动步骤与下一轮待办。
