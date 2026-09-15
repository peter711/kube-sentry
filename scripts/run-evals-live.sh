#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

AGENT_URL="${EVAL_AGENT_URL:-${AGENT_URL:-http://localhost:8080}}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is not installed." >&2
  exit 1
fi

if ! kubectl get namespace ai-lab >/dev/null 2>&1; then
  echo "Namespace ai-lab is not reachable. Run ./scripts/create-cluster.sh && ./scripts/deploy.sh first." >&2
  exit 1
fi

if ! curl -sf "$AGENT_URL/health" >/dev/null 2>&1; then
  echo "Agent is not reachable at $AGENT_URL/health. Deploy it with ./scripts/deploy.sh." >&2
  exit 1
fi

if [[ -x .venv/bin/python ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

echo "Running live evals against $AGENT_URL (namespace ai-lab)"
exec "$PYTHON" evals/run_evals.py -m live --report-dir evals/reports/live "$@"
