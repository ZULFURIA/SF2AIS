#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker info >/dev/null
docker build --pull -t sf2ais-workbench:latest -f "$ROOT/sandbox/Dockerfile" "$ROOT"
echo "Sf2AiS sandbox image is ready: sf2ais-workbench:latest"
