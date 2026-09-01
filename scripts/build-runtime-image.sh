#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${1:-ghcr.io/kokkini/goose-studio-runtime:v1.2.0}
PYTHON=${PYTHON:-python3}
OUTPUT=${2:---load}

if [[ "$OUTPUT" != "--load" && "$OUTPUT" != "--push" ]]; then
  echo "Usage: $0 [image] [--load|--push]" >&2
  exit 2
fi

"$PYTHON" "$ROOT/scripts/prepare-custom-nodes.py"
docker buildx build "$OUTPUT" -f "$ROOT/Dockerfile" -t "$IMAGE" "$ROOT"
echo "Built $IMAGE"
