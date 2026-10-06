#!/usr/bin/env bash
# Runs the studio API (http://127.0.0.1:8787) and the React dev server (http://localhost:5288).
# Ctrl-C stops both. Render jobs run in their own process group, so they keep going.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
uv run uvicorn storyvid.api.app:app --host 127.0.0.1 --port 8787 --reload --reload-dir storyvid &
(cd web && npm run dev) &
wait
