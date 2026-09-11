#!/usr/bin/env bash
set -euo pipefail

CLUSTER=ai-lab
NAMESPACE=ai-lab

echo "[1/4] Building React UI"
docker build -t ai-agent-ui:dev ./ui

echo "[2/4] Importing image into k3d"
k3d image import -c "$CLUSTER" ai-agent-ui:dev

echo "[3/4] Applying Kubernetes UI manifests"
kubectl apply -f k8s/50-ui.yaml
kubectl -n "$NAMESPACE" rollout restart deployment/ai-agent-ui
kubectl -n "$NAMESPACE" rollout status deployment/ai-agent-ui --timeout=120s

echo "[4/4] Ready"
echo "UI:      http://localhost:8080/ui/"
echo "Grafana: http://localhost:8080/grafana/"
kubectl -n "$NAMESPACE" get deploy,svc,ingress -l app=ai-agent-ui 2>/dev/null || true
