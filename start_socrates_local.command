#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

DB_PATH="${DB_PATH:-./SocratesTest.db}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"
API_TOKEN="${MULTI_AGENT_APP_API_TOKEN:-dev-secret}"

LOG_DIR="$ROOT_DIR/logs"
RUN_DIR="$ROOT_DIR/.run"
mkdir -p "$LOG_DIR" "$RUN_DIR"

API_LOG="$LOG_DIR/memory_api.log"
NGROK_LOG="$LOG_DIR/ngrok.log"
API_PID_FILE="$RUN_DIR/memory_api.pid"
NGROK_PID_FILE="$RUN_DIR/ngrok.pid"
NGROK_URL_FILE="$RUN_DIR/ngrok_public_url.txt"

echo "== Socrates local startup =="
echo "Projekt: $ROOT_DIR"
echo "Databas: $DB_PATH"
echo "API: http://$HOST:$PORT"
echo

if [ ! -d ".venv" ]; then
  echo "Fel: .venv saknas i projektroten."
  exit 1
fi

if ! command -v ngrok >/dev/null 2>&1; then
  echo "Fel: ngrok är inte installerat."
  exit 1
fi

source .venv/bin/activate
export PYTHONPATH=src
export MULTI_AGENT_APP_API_TOKEN="$API_TOKEN"

health_status_ok() {
  local base_url="$1"
  local body
  body="$(curl -fsS "$base_url/health" -H "Authorization: Bearer $API_TOKEN" 2>/dev/null || true)"
  if [ -z "$body" ]; then
    return 1
  fi
  HEALTH_BODY="$body" python - <<'PY'
import json
import os
import sys

raw = os.environ.get("HEALTH_BODY", "")
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    sys.exit(1)
sys.exit(0 if data.get("status") == "ok" else 1)
PY
}

port_listener_pids() {
  lsof -t -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

discover_ngrok_public_url() {
  local tunnels_json
  tunnels_json="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null || true)"
  if [ -z "$tunnels_json" ]; then
    return 1
  fi
  NGROK_TUNNELS_JSON="$tunnels_json" python - <<'PY'
import json
import os
import sys

raw = os.environ.get("NGROK_TUNNELS_JSON", "")
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    sys.exit(1)

tunnels = data.get("tunnels", [])
for tunnel in tunnels:
    public_url = tunnel.get("public_url", "")
    if isinstance(public_url, str) and public_url.startswith("https://"):
        print(public_url)
        sys.exit(0)
sys.exit(1)
PY
}

if [ -f "$API_PID_FILE" ]; then
  OLD_API_PID="$(cat "$API_PID_FILE" || true)"
  if [ -n "${OLD_API_PID:-}" ] && kill -0 "$OLD_API_PID" >/dev/null 2>&1; then
    echo "Stoppar gammal API-process ($OLD_API_PID)..."
    kill "$OLD_API_PID" || true
    sleep 1
  fi
  rm -f "$API_PID_FILE"
fi

if [ -f "$NGROK_PID_FILE" ]; then
  OLD_NGROK_PID="$(cat "$NGROK_PID_FILE" || true)"
  if [ -n "${OLD_NGROK_PID:-}" ] && kill -0 "$OLD_NGROK_PID" >/dev/null 2>&1; then
    echo "Stoppar gammal ngrok-process ($OLD_NGROK_PID)..."
    kill "$OLD_NGROK_PID" || true
    sleep 1
  fi
  rm -f "$NGROK_PID_FILE"
fi

if [ ! -f "$DB_PATH" ]; then
  echo "Skapar databasfil: $DB_PATH"
  touch "$DB_PATH"
fi

EXISTING_PORT_PIDS="$(port_listener_pids)"
if [ -n "$EXISTING_PORT_PIDS" ]; then
  echo "Fel: port $PORT används redan av process(er): $EXISTING_PORT_PIDS"
  echo "Kör ./stop_socrates_local.command eller frigör porten innan start."
  exit 1
fi

echo "Initierar databas om det behövs..."
python - <<PY
from multi_agent_app.storage import Storage
storage = Storage(db_path="$DB_PATH")
storage.close()
print("Database ready:", "$DB_PATH")
PY

echo "Startar lokalt memory API..."
nohup python -m multi_agent_app.cli --db-path "$DB_PATH" serve-memory-api --host "$HOST" --port "$PORT" >"$API_LOG" 2>&1 &
API_PID=$!
echo "$API_PID" > "$API_PID_FILE"
sleep 0.3

if ! kill -0 "$API_PID" >/dev/null 2>&1; then
  echo "Fel: API-processen avslutades direkt efter start."
  echo "Se logg: $API_LOG"
  exit 1
fi

echo "Väntar på lokalt API..."
for _ in $(seq 1 20); do
  if ! kill -0 "$API_PID" >/dev/null 2>&1; then
    echo "Fel: API-processen avslutades under uppstart."
    echo "Se logg: $API_LOG"
    exit 1
  fi
  if health_status_ok "http://$HOST:$PORT"; then
    echo "Lokalt API svarar."
    break
  fi
  sleep 1
done

if ! health_status_ok "http://$HOST:$PORT"; then
  echo "Fel: lokalt API startade inte korrekt."
  echo "Se logg: $API_LOG"
  exit 1
fi

echo "Startar ngrok..."
nohup ngrok http "$PORT" >"$NGROK_LOG" 2>&1 &
NGROK_PID=$!
echo "$NGROK_PID" > "$NGROK_PID_FILE"

echo "Väntar på ngrok inspect API och publik URL..."
NGROK_PUBLIC_URL=""
for _ in $(seq 1 30); do
  NGROK_PUBLIC_URL="$(discover_ngrok_public_url || true)"
  if [ -n "$NGROK_PUBLIC_URL" ]; then
    echo "Publik ngrok-URL hittad."
    break
  fi
  sleep 1
done

if [ -z "$NGROK_PUBLIC_URL" ]; then
  echo "Fel: kunde inte läsa publik HTTPS-URL från ngrok inspect API."
  echo "Se logg: $NGROK_LOG"
  exit 1
fi

echo "$NGROK_PUBLIC_URL" > "$NGROK_URL_FILE"

echo "Väntar på publik ngrok-endpoint..."
for _ in $(seq 1 20); do
  if health_status_ok "$NGROK_PUBLIC_URL"; then
    echo "Publik endpoint svarar med status=ok."
    break
  fi
  sleep 1
done

if ! health_status_ok "$NGROK_PUBLIC_URL"; then
  echo "Fel: publik ngrok-endpoint svarar inte med JSON status=ok."
  echo "Se loggar:"
  echo "  API:   $API_LOG"
  echo "  ngrok: $NGROK_LOG"
  exit 1
fi

echo
echo "===== KLART ====="
echo "Lokal health:"
curl -s "http://$HOST:$PORT/health" -H "Authorization: Bearer $API_TOKEN"
echo
echo
echo "Publik health:"
curl -s "$NGROK_PUBLIC_URL/health" -H "Authorization: Bearer $API_TOKEN"
echo
echo
echo "Klar att användas i ChatGPT via:"
echo "  $NGROK_PUBLIC_URL"
echo "Publik URL sparad i:"
echo "  $NGROK_URL_FILE"
echo
echo "Loggar:"
echo "  $API_LOG"
echo "  $NGROK_LOG"
echo
echo "Stoppa med:"
echo "  ./stop_socrates_local.command"
