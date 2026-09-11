#!/usr/bin/env sh
set -eu

k3d cluster create ai-lab \
  --servers 1 \
  --agents 1 \
  -p "127.0.0.1:8080:80@loadbalancer"

kubectl wait --for=condition=Ready nodes --all --timeout=120s
kubectl get nodes -o wide
