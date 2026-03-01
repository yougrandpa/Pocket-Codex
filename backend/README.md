# Pocket Codex Backend (MVP)

FastAPI backend skeleton for Pocket Codex mobile control panel.

## Features in this MVP scaffold

- `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh` for single-user JWT auth.
- Mobile approval auth flow:
  - `POST /api/v1/auth/mobile/request` creates pending mobile login request.
    - Returns `request_id` and `request_token` (keep both on device).
  - `GET /api/v1/auth/mobile/pending` lists pending requests (desktop session required).
  - `POST /api/v1/auth/mobile/requests/{id}/approve|reject|cancel` approves/rejects/cancels request.
  - `GET /api/v1/auth/mobile/requests/{id}` polls status (must send `X-Mobile-Request-Token` header) and returns tokens on approval.
- `POST /api/v1/tasks` creates a task (`QUEUED`) and starts a simulated lifecycle.
- Worker lifecycle transitions `QUEUED -> RUNNING -> SUCCEEDED`, supports pause/resume/timeout.
- `GET /api/v1/tasks` and `GET /api/v1/tasks/{id}` read persisted task snapshots.
- `POST /api/v1/tasks/{id}/control` supports `pause`, `resume`, `cancel`, `retry`.
- `POST /api/v1/tasks/{id}/message` appends user messages to a task.
- `GET /api/v1/tasks/audit/logs` returns audit logs (auth + control + message actions).
- `GET /api/v1/stream` exposes SSE events (optional `task_id` filter), auth via bearer header only.

## Local run

Run commands from repository root (`Pocket-Codex/`) unless noted.

```bash
./scripts/setup_local_env.sh
cd backend
source .venv/bin/activate
set -a && source .env && set +a
# Optional: switch to PostgreSQL for persistence
# export DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/pocket_codex
# Optional: retry policy
# export APP_MAX_AUTO_RETRIES=2
# export APP_RETRY_BACKOFF_BASE_SECONDS=1
# Optional: local worker concurrency (2~4 recommended)
# export APP_WORKER_CONCURRENCY=2
# Optional: allowed workdir roots (comma-separated)
# export APP_WORKDIR_WHITELIST=/Users/slg/workspace/Pocket-Codex
# Optional: security policy for mobile login approval flow
# export APP_REQUIRE_LOOPBACK_DIRECT_LOGIN=true
# export APP_MOBILE_LOGIN_REQUEST_TTL_SECONDS=180
# Optional: allow private-network origins (172/192.168/10.x and *.local) for phone access
# export APP_CORS_ALLOW_PRIVATE_NETWORK=true
# Optional: SSE replay limit on reconnect
# export APP_SSE_REPLAY_LIMIT=500
# Optional: switch executor queue backend to Redis
# export APP_EXECUTION_BACKEND=redis
# export REDIS_URL=redis://localhost:6379/0
# export REDIS_QUEUE_PREFIX=pocket_codex:tasks
# Optional: switch task executor from simulator to local codex CLI
# export APP_TASK_EXECUTOR=codex
# export APP_TASK_EXECUTOR=codex-cli
# export CODEX_CLI_PATH=codex
# export CODEX_CLI_PATH=codex-cli
# export CODEX_FULL_AUTO=true
uvicorn app.main:app --reload --port 8000
# If file watching is restricted, run without reload:
# uvicorn app.main:app --port 8000
```

## Quick smoke test

Login and export access token (`backend/` terminal):

```bash
source .env
LOGIN_JSON=$(curl --fail-with-body -sS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$APP_USERNAME\",\"password\":\"$APP_PASSWORD\"}") || {
  echo "[smoke] login request failed. Is backend running on 127.0.0.1:8000?"
  exit 1
}
TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<< "$LOGIN_JSON")

curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"run test command","priority":1}'
```

Then check:

- `GET http://127.0.0.1:8000/api/v1/tasks` with bearer token
- `GET http://127.0.0.1:8000/api/v1/stream` with `Authorization: Bearer $TOKEN`

### Mobile approval example

```bash
source .env
REQ_JSON=$(curl --fail-with-body -sS -X POST http://127.0.0.1:8000/api/v1/auth/mobile/request \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$APP_USERNAME\",\"password\":\"$APP_PASSWORD\",\"device_name\":\"phone\"}")
REQUEST_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])' <<< "$REQ_JSON")
REQUEST_TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["request_token"])' <<< "$REQ_JSON")

# desktop side approves (use a desktop bearer token):
curl -X POST "http://127.0.0.1:8000/api/v1/auth/mobile/requests/$REQUEST_ID/approve" \
  -H "Authorization: Bearer $TOKEN"

# phone side polls by request_id + request_token header:
curl "http://127.0.0.1:8000/api/v1/auth/mobile/requests/$REQUEST_ID" \
  -H "X-Mobile-Request-Token: $REQUEST_TOKEN"
```

## Notes

- Default persistence uses SQLite at `backend/pocket_codex.db` and survives process restarts.
- Default queue backend is in-process (`APP_EXECUTION_BACKEND=local`); set it to `redis` for shared queue consumption.
- Queue execution uses priority scheduling and supports multi-worker concurrency via `APP_WORKER_CONCURRENCY`.
- Workdir validation is enforced by `APP_WORKDIR_WHITELIST` for safer local execution boundaries.
- SSE supports reconnect replay via `Last-Event-ID` / `last_event_id`.
- By default, direct login (`/auth/login`) is localhost-only (`APP_REQUIRE_LOOPBACK_DIRECT_LOGIN=true`).
- If `/auth/login` returns `403` from non-localhost traffic, use the mobile approval flow (`/auth/mobile/*`).
- Mobile login requires desktop approval via `/auth/mobile/*` endpoints.
- Private-network CORS origins are allowed by default (`APP_CORS_ALLOW_PRIVATE_NETWORK=true`) for phone hotspot/LAN usage.
- Default task executor is `simulator`; set `APP_TASK_EXECUTOR=codex` or `APP_TASK_EXECUTOR=codex-cli` to run real local CLI commands.
- `APP_USERNAME` and `APP_PASSWORD` are required and must be set before startup.
