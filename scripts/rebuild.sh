#!/usr/bin/env bash
set -euo pipefail
docker build -t ai-agent:dev ./agent
k3d image import -c ai-lab ai-agent:dev
kubectl -n ai-lab rollout restart deployment/ai-agent
kubectl -n ai-lab rollout status deployment/ai-agent --timeout=120s
