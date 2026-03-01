# Pocket Codex（中文优先）

Pocket Codex 是一个移动端优先的 Codex 远程控制台，用于在手机上监控、控制和追踪任务执行。

English version: `README.en.md`

## 语言策略

- 主语言：中文
- 次语言：英文（文档与界面关键文案均保留英文对照）

## 项目目标

- 实时查看 Codex 当前执行状态
- 判断任务是否成功/失败/超时/等待输入
- 从手机端下达任务与控制动作（暂停、继续、取消、重试）
- 查看事件流、日志增量与审计记录

## 当前 MVP 能力

- 前端：Next.js 移动优先控制台
- 后端：FastAPI + JWT 鉴权（支持“手机登录需电脑批准”）
- 实时：SSE 推送状态与日志
- 存储：SQLite（默认）/ PostgreSQL（可选）
- 队列：`local` / `redis` 可插拔执行后端
- 执行器：`simulator`（默认）/ `codex`（可切换到本地 Codex CLI）

## 快速开始

1. 一键初始化：`./scripts/setup_local_env.sh`
2. 环境验收：`./scripts/verify_local_env.sh`
3. 阅读本地联调文档：`docs/LOCAL_RUN.md`

推荐启动顺序：

1. 启动后端（`backend/`，端口 `8000`）
2. 启动前端（`frontend/`，端口 `3000`）
3. 使用默认账号登录（`admin` / `admin123`，建议立刻改为自定义强口令）
4. 手机端登录建议走“手机登录（需电脑授权）”流程
5. 手机登录详细步骤见：`docs/USAGE.zh-CN.md` 的“2. 登录（重点：手机端需要电脑授权）”

## 文档索引

- 项目计划：`docs/PROJECT_PLAN.md`
- 实现方案：`docs/IMPLEMENTATION_PLAN.md`
- API 契约：`docs/API_CONTRACT.md`
- 本地联调：`docs/LOCAL_RUN.md`
- 使用说明（中文）：`docs/USAGE.zh-CN.md`
- 英文总览：`README.en.md`
