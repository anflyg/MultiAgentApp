#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

RUN_DIR="$ROOT_DIR/.run"
API_PID_FILE="$RUN_DIR/memory_api.pid"
NGROK_PID_FILE="$RUN_DIR/ngrok.pid"
NGROK_URL_FILE="$RUN_DIR/ngrok_public_url.txt"

stop_process_from_pid_file() {
  local name="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    echo "$name: ingen PID-fil ($pid_file)."
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -z "$pid" ]; then
    echo "$name: tom PID-fil, tar bort den."
    rm -f "$pid_file"
    return 0
  fi

  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "Stoppar $name ($pid)..."
    kill "$pid" >/dev/null 2>&1 || true
    for _ in $(seq 1 10); do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
      fi
      sleep 0.2
    done
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "$name ($pid) svarar inte på SIGTERM, skickar SIGKILL."
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  else
    echo "$name: process $pid körs inte."
  fi

  rm -f "$pid_file"
}

echo "== Stoppar Socrates lokalt =="
stop_process_from_pid_file "ngrok" "$NGROK_PID_FILE"
stop_process_from_pid_file "memory-api" "$API_PID_FILE"

if [ -f "$NGROK_URL_FILE" ]; then
  rm -f "$NGROK_URL_FILE"
  echo "Tog bort sparad ngrok-URL: $NGROK_URL_FILE"
fi

echo "Klart."
