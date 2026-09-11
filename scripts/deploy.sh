#!/usr/bin/env sh
set -eu

: "${OPENAI_API_KEY:?Set OPENAI_API_KEY before running this script}"

docker build -t ai-agent:dev ./agent
k3d image import ai-agent:dev -c ai-lab

kubectl apply -f k8s/00-namespace.yaml

# Stage 4 used Role/RoleBinding named "ai-agent" and granted patch on Deployments
# to the API ServiceAccount. Stage 5 splits API and worker identities, so remove
# those legacy RBAC objects before applying the new policy.
kubectl -n ai-lab delete rolebinding ai-agent --ignore-not-found
kubectl -n ai-lab delete role ai-agent --ignore-not-found

kubectl -n ai-lab create secret generic openai-api \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f k8s/10-rbac.yaml
kubectl apply -f k8s/15-pvc.yaml
kubectl apply -f k8s/20-deployment.yaml
kubectl apply -f k8s/30-service.yaml
kubectl apply -f k8s/40-ingress.yaml

# The development image keeps the same tag, so force Pods to pick up
# the newly imported image even when the Deployment spec did not change.
kubectl -n ai-lab rollout restart deployment/ai-agent
kubectl -n ai-lab rollout status deployment/ai-agent --timeout=180s
kubectl -n ai-lab get pods,svc,ingress,pvc
