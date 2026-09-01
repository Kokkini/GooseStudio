#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is required but was not found on PATH." >&2
  exit 1
fi

if [[ $(id -u) -eq 0 ]]; then
  export ELECTRON_DISABLE_SANDBOX=1
fi

exec pnpm --dir "$ROOT/web" dev
