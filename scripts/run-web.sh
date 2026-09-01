#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is required but was not found on PATH." >&2
  exit 1
fi

cleanup() {
  trap - EXIT INT TERM
  kill "${BRIDGE_PID:-}" "${VITE_PID:-}" 2>/dev/null || true
  wait "${BRIDGE_PID:-}" "${VITE_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python "$ROOT/scripts/serve-web.py" &
BRIDGE_PID=$!
pnpm --dir "$ROOT/web" dev:web &
VITE_PID=$!

echo "Goose Studio is starting at http://localhost:4173"
wait -n "$BRIDGE_PID" "$VITE_PID"
