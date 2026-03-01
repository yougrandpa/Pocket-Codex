# Pocket Codex

Pocket Codex is a mobile-first control panel for monitoring and operating Codex tasks remotely.

## Vision

Use your phone to:

- See what Codex is currently doing in real time.
- Check whether a task is queued, running, completed, or failed.
- Send new commands and control existing tasks (pause, resume, cancel, retry).
- Receive completion and failure notifications.

## MVP Scope

- Task list and task detail views.
- Realtime status and log streaming.
- Command submission from mobile web.
- Task control actions.
- Basic auth for single-user operation.

## Suggested Stack

- Frontend: Next.js (responsive web for iOS Safari first).
- Backend: FastAPI or NestJS.
- Queue: Redis + Celery/BullMQ.
- Realtime: WebSocket/SSE.
- Database: PostgreSQL.

## Quick Start

0. One-command local setup: `./scripts/setup_local_env.sh`
1. Read implementation details: `docs/IMPLEMENTATION_PLAN.md`
2. Read API contract: `docs/API_CONTRACT.md`
3. Follow local setup and integration steps: `docs/LOCAL_RUN.md`
4. Optional infra bootstrap: `docker compose up -d postgres redis`

Recommended startup order:

1. Start backend (`backend/`, FastAPI on `:8000`)
2. Start frontend (`frontend/`, Next.js on `:3000`)
3. Sign in with credentials configured in `backend/.env` (`APP_USERNAME` / `APP_PASSWORD`)
4. Create a task and verify realtime events with `/api/v1/stream`

## Pre-commit Sub-agent Review Command

Command: `./scripts/commit_with_subagent_review.sh "<commit message>"`

- Runs recursive `review sub-agent -> fix sub-agent -> review sub-agent`
- Continues until reviewer returns `STATUS:PASS`
- Runs `./scripts/verify_local_env.sh` by default
- Then executes `git add -A` and `git commit`

Optional environment variables:

- `CODEX_REVIEW_CLI_PATH`: codex executable path (default: `codex`)
- `MAX_REVIEW_ROUNDS`: max recursive rounds (default: `5`)
- `RUN_VERIFY_BEFORE_COMMIT`: run local verification (`1/0`, default: `1`)

## Documentation Index

- Project plan: `docs/PROJECT_PLAN.md`
- Implementation plan: `docs/IMPLEMENTATION_PLAN.md`
- API contract: `docs/API_CONTRACT.md`
- Local runbook: `docs/LOCAL_RUN.md`
- Usage guide (Chinese): `docs/USAGE.zh-CN.md`
