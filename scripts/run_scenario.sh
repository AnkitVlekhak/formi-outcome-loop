#!/usr/bin/env bash
# Serve a scenario, run the controller against it, grade vs baseline.
#   scripts/run_scenario.sh scenarios/public_01_dev.yaml [port]
set -euo pipefail
cd "$(dirname "$0")/.."
SC="$1"; PORT="${2:-8700}"; NAME="$(basename "$SC" .yaml)"
PY=.venv/bin/python
mkdir -p runs reports logs
[ -d "runs/base_$NAME" ] || $PY -m sim baseline --scenario "$SC" --run-dir "runs/base_$NAME"
$PY -m sim serve --scenario "$SC" --run-dir "runs/mine_$NAME" --port "$PORT" --force > "logs/sim_$NAME.log" 2>&1 &
SIM=$!; trap 'kill $SIM 2>/dev/null || true' EXIT
until curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; do sleep 0.5; done
rm -rf "state/$NAME"
/usr/bin/time -l env CTL_STATE_DIR="state/$NAME" ./run.sh "http://127.0.0.1:$PORT" > "logs/ctl_$NAME.log" 2> "logs/ctl_${NAME}.time"
$PY -m sim grade --run "runs/mine_$NAME" --baseline "runs/base_$NAME" --out "reports/$NAME.md" > /dev/null
echo "graded -> reports/$NAME.md"
