#!/usr/bin/env bash
set -euo pipefail

RESPONSE=$(curl -s -X POST http://localhost:8080/ask   -H 'Content-Type: application/json'   -d '{"question":"Zdiagnozuj stan deploymentu broken-nginx. Nie proponuj zmian."}')

echo "$RESPONSE" | jq
TRACE_ID=$(echo "$RESPONSE" | jq -r '.trace_id // empty')

echo
if [[ -n "$TRACE_ID" ]]; then
  echo "Trace ID: $TRACE_ID"
  echo "Open Grafana: http://localhost:8080/grafana/"
  echo "Explore -> Tempo -> search this Trace ID, or open dashboard AI Kubernetes Agent Observability."
else
  echo "No trace_id returned. Check ai-agent and otel-collector logs."
fi
