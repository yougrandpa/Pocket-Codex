#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo "[setup] project root: $ROOT_DIR"

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  python3 - <<PY
from pathlib import Path
path = Path("$BACKEND_DIR/.env")
text = path.read_text()
text = text.replace("APP_JWT_SECRET=replace-with-a-random-32-plus-char-secret", f"APP_JWT_SECRET=$SECRET")
path.write_text(text)
PY
  echo "[setup] created backend/.env"
else
  echo "[setup] backend/.env already exists, skip"
fi

if [[ ! -f "$FRONTEND_DIR/.env.local" ]]; then
  cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env.local"
  echo "[setup] created frontend/.env.local"
else
  echo "[setup] frontend/.env.local already exists, skip"
fi

if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
fi

source "$BACKEND_DIR/.venv/bin/activate"
python3 -m pip install -r "$BACKEND_DIR/requirements.txt"

cd "$FRONTEND_DIR"
npm install

echo
echo "[setup] done"
echo "backend run: cd backend && source .venv/bin/activate && set -a && source .env && set +a && uvicorn app.main:app --reload --port 8000"
echo "frontend run: cd frontend && npm run dev"
