#!/usr/bin/env sh
set -eu

docker build -t ai-agent:dev ./agent
k3d image import ai-agent:dev -c ai-lab
kubectl -n ai-lab rollout restart deployment/ai-agent
kubectl -n ai-lab rollout status deployment/ai-agent --timeout=120s
