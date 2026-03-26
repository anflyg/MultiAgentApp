#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

API_PID_FILE="$ROOT_DIR/.run/memory_api.pid"
NGROK_PID_FILE="$ROOT_DIR/.run/ngrok.pid"

if [ -f "$API_PID_FILE" ]; then
  PID="$(cat "$API_PID_FILE" || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" >/dev/null 2>&1; then
    echo "Stoppar API ($PID)..."
    kill "$PID" || true
  fi
  rm -f "$API_PID_FILE"
fi

if [ -f "$NGROK_PID_FILE" ]; then
  PID="$(cat "$NGROK_PID_FILE" || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" >/dev/null 2>&1; then
    echo "Stoppar ngrok ($PID)..."
    kill "$PID" || true
  fi
  rm -f "$NGROK_PID_FILE"
fi

echo "Klart."