#!/usr/bin/env bash
# Contract: ./run.sh <SIM_URL> starts the controller and runs until the scenario finishes.
# No Docker needed: Python 3.11+ with `pip install -r requirements.txt` (adds orjson only).
# State (SQLite + snapshot) lives in $CTL_STATE_DIR (default ./state). Re-running the same command
# after a crash resumes; a new simulator world is detected and the old state is archived.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m controller run --url "$SIM_URL" --state-dir "${CTL_STATE_DIR:-state}" \
  ${CTL_API_PORT:+--api-port "$CTL_API_PORT"} ${CTL_NO_CALL_LOG:+--no-call-log}
