#!/usr/bin/env bash
set -euo pipefail

if k3d cluster list 2>/dev/null | grep -q '^ai-lab '; then
  echo "Cluster ai-lab already exists."
  exit 0
fi

k3d cluster create ai-lab   --servers 1   --agents 1   -p '127.0.0.1:8080:80@loadbalancer'   --wait

kubectl cluster-info
