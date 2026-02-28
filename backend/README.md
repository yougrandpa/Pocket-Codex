# Pocket Codex Backend (MVP)

FastAPI backend skeleton for Pocket Codex mobile control panel.

## Features in this MVP scaffold

- `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh` for single-user JWT auth.
- `POST /api/v1/tasks` creates a task (`QUEUED`) and starts a simulated lifecycle.
- Simulated lifecycle transitions `QUEUED -> RUNNING -> SUCCEEDED`, supports pause/resume.
- `GET /api/v1/tasks` and `GET /api/v1/tasks/{id}` read task data from in-memory storage.
- `POST /api/v1/tasks/{id}/control` supports `pause`, `resume`, `cancel`, `retry`.
- `POST /api/v1/tasks/{id}/message` appends user messages to a task.
- `GET /api/v1/stream` exposes SSE events (optional `task_id` filter), auth via bearer or `access_token` query.

## Local run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Quick smoke test

Login and export access token:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"run test command","priority":1}'
```

Then check:

- `GET http://127.0.0.1:8000/api/v1/tasks` with bearer token
- `GET http://127.0.0.1:8000/api/v1/stream?access_token=$TOKEN`

## Notes

- Storage is in-memory only; data resets on process restart.
- Default credentials are `admin / admin123` and should be overridden with env vars for non-local environments.
