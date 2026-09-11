#!/usr/bin/env bash
set -euo pipefail

CLUSTER=ai-lab
NAMESPACE=ai-lab

if ! k3d cluster list 2>/dev/null | grep -q '^ai-lab '; then
  echo "Cluster ai-lab does not exist. Run ./scripts/create-cluster.sh first." >&2
  exit 1
fi

echo "[1/8] Building agent image"
docker build -t ai-agent:dev ./agent
k3d image import -c "$CLUSTER" ai-agent:dev

echo "[2/8] Namespace and API secret"
kubectl apply -f k8s/00-namespace.yaml
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  kubectl -n "$NAMESPACE" create secret generic openai-api     --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"     --dry-run=client -o yaml | kubectl apply -f -
elif ! kubectl -n "$NAMESPACE" get secret openai-api >/dev/null 2>&1; then
  echo "OPENAI_API_KEY is not set and Secret/openai-api does not exist." >&2
  exit 1
else
  echo "Keeping existing Secret/openai-api"
fi

echo "[3/8] RBAC and storage"
kubectl -n "$NAMESPACE" delete rolebinding ai-agent --ignore-not-found
kubectl -n "$NAMESPACE" delete role ai-agent --ignore-not-found
kubectl apply -f k8s/10-rbac.yaml
kubectl apply -f k8s/15-pvc.yaml

echo "[4/8] Observability configuration"
kubectl apply -f observability/00-otel-collector-config.yaml
kubectl apply -f observability/20-tempo-config.yaml
kubectl apply -f observability/30-prometheus-config.yaml
kubectl apply -f observability/40-grafana-provisioning.yaml
kubectl apply -f observability/41-grafana-dashboard.yaml

echo "[5/8] Observability workloads"
kubectl apply -f observability/21-tempo.yaml
kubectl apply -f observability/10-otel-collector.yaml
kubectl apply -f observability/31-prometheus.yaml
kubectl apply -f observability/42-grafana.yaml

echo "[6/8] Agent"
kubectl apply -f k8s/20-deployment.yaml
kubectl apply -f k8s/30-service.yaml
kubectl apply -f k8s/40-ingress.yaml
kubectl -n "$NAMESPACE" rollout restart deployment/ai-agent

echo "[7/8] Waiting for workloads"
kubectl -n "$NAMESPACE" rollout status deployment/tempo --timeout=120s
kubectl -n "$NAMESPACE" rollout status deployment/otel-collector --timeout=120s
kubectl -n "$NAMESPACE" rollout status deployment/prometheus --timeout=120s
kubectl -n "$NAMESPACE" rollout status deployment/grafana --timeout=120s
kubectl -n "$NAMESPACE" rollout status deployment/ai-agent --timeout=120s

echo "[8/8] Ready"
echo "Agent:   http://localhost:8080"
echo "Grafana: http://localhost:8080/grafana/"
echo
kubectl -n "$NAMESPACE" get pods,svc,ingress
