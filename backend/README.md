# Pocket Codex Backend (MVP)

FastAPI backend skeleton for Pocket Codex mobile control panel.

## Features in this MVP scaffold

- `POST /api/v1/tasks` creates a task (`QUEUED`) and starts a simulated lifecycle.
- Simulated lifecycle automatically transitions `QUEUED -> RUNNING -> SUCCEEDED`.
- `GET /api/v1/tasks` and `GET /api/v1/tasks/{id}` read task data from in-memory storage.
- `POST /api/v1/tasks/{id}/control` supports `cancel` and `retry`.
- `POST /api/v1/tasks/{id}/message` appends user messages to a task.
- `GET /api/v1/stream` exposes SSE events (optional `task_id` filter).

## Local run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Quick smoke test

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"run test command","priority":1}'
```

Then check:

- `GET http://127.0.0.1:8000/api/v1/tasks`
- `GET http://127.0.0.1:8000/api/v1/stream`

## Notes

- Storage is in-memory only; data resets on process restart.
- `pause` and `resume` intentionally return `501 Not Implemented` in this MVP.
