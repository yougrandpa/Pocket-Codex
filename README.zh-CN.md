# Pocket Codex（中文版）

Pocket Codex 是一个移动端优先的 Codex 远程控制台，用于在手机上监控和操作任务执行过程。

## 项目愿景

- 实时查看 Codex 当前在做什么
- 判断任务状态（排队、运行、成功、失败、超时、取消）
- 从手机端新建任务、追加指令、执行控制动作
- 在任务结束后查看摘要与审计记录

## 当前能力（MVP）

- 前端：Next.js 移动优先控制台
- 后端：FastAPI + JWT 鉴权（支持手机登录电脑端授权）
- 实时：SSE 状态/日志增量推送
- 存储：SQLite（默认）或 PostgreSQL（可切换）
- 队列：可插拔执行后端（`local` / `redis`）
- 控制动作：`pause` / `resume` / `cancel` / `retry`

## 快速开始

### 1) 一键初始化本地环境

```bash
./scripts/setup_local_env.sh
```

### 2) 启动后端

```bash
cd backend
source .venv/bin/activate
set -a && source .env && set +a
uvicorn app.main:app --reload --port 8000
```

### 3) 启动前端

```bash
cd frontend
npm run dev
```

打开 `http://localhost:3000`，使用 `backend/.env` 中配置的账号登录：

- 用户名：`APP_USERNAME`
- 密码：`APP_PASSWORD`

建议：

- 先在 `backend/.env` 中设置强口令（`APP_USERNAME` / `APP_PASSWORD`）
- 手机端优先使用“手机登录（需电脑授权）”流程
- 手机登录详细步骤见：`docs/USAGE.zh-CN.md` 的“2. 登录（重点：手机端需要电脑授权）”

## 提交前子代理审查命令

命令：

```bash
./scripts/commit_with_subagent_review.sh "<commit message>"
```

行为：

- 自动执行“review 子代理 -> 修复子代理 -> 再 review 子代理”递归流程
- 直到 review 输出 `STATUS:PASS` 才继续
- 默认执行 `./scripts/verify_local_env.sh`
- 最后自动 `git add -A` + `git commit`

可选环境变量：

- `CODEX_REVIEW_CLI_PATH`：codex 可执行路径（默认 `codex`）
- `MAX_REVIEW_ROUNDS`：最大递归轮次（默认 `5`）
- `RUN_VERIFY_BEFORE_COMMIT`：是否执行本地验收（`1/0`，默认 `1`）

## 文档索引

- 项目计划：`docs/PROJECT_PLAN.md`
- 实现方案：`docs/IMPLEMENTATION_PLAN.md`
- API 合同：`docs/API_CONTRACT.md`
- 本地联调：`docs/LOCAL_RUN.md`
- 使用说明（中文）：`docs/USAGE.zh-CN.md`

## 远端与分支

- GitHub：`https://github.com/yougrandpa/Pocket-Codex`
- 默认分支：`main`
