#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

source "$BACKEND_DIR/.venv/bin/activate"
if [[ -f "$BACKEND_DIR/.env" ]]; then
  set -a
  source "$BACKEND_DIR/.env"
  set +a
fi

echo "[verify] backend compile"
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall "$BACKEND_DIR/app"

echo "[verify] backend api smoke"
# Force deterministic simulator mode for smoke checks. Real codex execution can
# exceed short polling windows and depends on local CLI state.
export APP_TASK_EXECUTOR=simulator
PYTHONPATH="$BACKEND_DIR" python3 - <<'PY'
import time
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"prompt": "local verify", "priority": 2, "timeout_seconds": 10},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    status = "QUEUED"
    for _ in range(20):
        detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        status = detail.json()["task"]["status"]
        if status in {"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELED"}:
            break
        time.sleep(0.4)

    audits = client.get("/api/v1/tasks/audit/logs?limit=5&offset=0", headers=headers)
    assert audits.status_code == 200, audits.text
    assert status in {"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELED"}, status
    print(f"backend smoke ok: task={task_id} status={status}")
PY

echo "[verify] frontend build"
cd "$FRONTEND_DIR"
npm run build >/tmp/pocket-codex-frontend-build.log
echo "[verify] frontend build ok (log: /tmp/pocket-codex-frontend-build.log)"

python3 - <<'PY'
import os
path = "backend/pocket_codex.db"
if os.path.exists(path):
    os.remove(path)
PY

echo "[verify] done"
