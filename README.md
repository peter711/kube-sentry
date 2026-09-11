# ai-k8s-lab

Local Kubernetes playground with:

- k3d / K3s
- FastAPI
- OpenAI Responses API
- namespace-scoped, read-only Kubernetes RBAC
- Traefik Ingress
- a deliberately broken Deployment for diagnostics practice

## Prerequisites

Install:

- Docker
- kubectl
- k3d

Verify:

```bash
docker version
kubectl version --client
k3d version
```

## 1. Create the local cluster

```bash
chmod +x scripts/*.sh
./scripts/create-cluster.sh
```

The cluster has one K3s server and one K3s agent.

Check:

```bash
kubectl get nodes -o wide
kubectl cluster-info
```

## 2. Set the OpenAI API key

macOS / Linux / WSL:

```bash
export OPENAI_API_KEY='YOUR_KEY_HERE'
```

Do not commit the key to Git.

## 3. Build and deploy the agent

```bash
./scripts/deploy.sh
```

Check:

```bash
kubectl -n ai-lab get all
kubectl -n ai-lab logs -f deploy/ai-agent
```

The app should be available at:

```text
http://localhost:8080/docs
```

Health check:

```bash
curl http://localhost:8080/health
```

Cluster snapshot:

```bash
curl http://localhost:8080/cluster
```

## 4. Ask the AI agent

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Co obecnie dzieje się w tym namespace?"}'
```

## 5. Create a deliberately broken workload

```bash
kubectl apply -f demo/broken-nginx.yaml
kubectl -n ai-lab get pods
kubectl -n ai-lab get events --sort-by=.lastTimestamp
```

Then ask:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Dlaczego deployment broken-nginx nie działa?"}'
```

The expected root cause is an invalid container image tag causing an image pull failure.

Fix it:

```bash
kubectl apply -f demo/fixed-nginx.yaml
kubectl -n ai-lab rollout status deploy/broken-nginx
kubectl -n ai-lab get pods
```

Ask the agent again and compare the answer.

## 6. Rebuild after changing Python code

```bash
./scripts/rebuild.sh
```

## Useful Kubernetes commands

```bash
kubectl get nodes
kubectl -n ai-lab get pods -o wide
kubectl -n ai-lab get deploy
kubectl -n ai-lab describe pod POD_NAME
kubectl -n ai-lab get events --sort-by=.lastTimestamp
kubectl -n ai-lab logs -f deploy/ai-agent
kubectl -n ai-lab auth can-i list pods \
  --as=system:serviceaccount:ai-lab:ai-agent
kubectl -n ai-lab auth can-i delete pods \
  --as=system:serviceaccount:ai-lab:ai-agent
```

The last command should return `no`. That is intentional.

## Tear down

Delete only the demo workload:

```bash
kubectl delete -f demo/broken-nginx.yaml --ignore-not-found
```

Delete the full cluster:

```bash
k3d cluster delete ai-lab
```

## Security model

The agent uses a ServiceAccount with a Role limited to namespace `ai-lab`.
It can list/read selected Kubernetes resources, but cannot create, modify,
or delete workloads.

The OpenAI key is created as a Kubernetes Secret at deploy time and is not
stored in this repository.


## Stage 2: tool-calling agent

The project now includes a second learning stage in `STAGE2.md`.

It adds:

- OpenAI function calling
- selective Kubernetes inspection instead of sending a full snapshot
- Pod log retrieval
- `CrashLoopBackOff` diagnostics
- a visible tool-call trace in the `/ask` response
- additional prompt-injection and secret-leak defenses

Continue with:

```bash
cat STAGE2.md
```


## Stage 3: memory and approved repairs

Stage 3 adds persistent SQLite conversation memory, detailed Pod/Deployment
inspection, and constrained Deployment repair proposals with explicit human approval.

Continue with:

```bash
cat STAGE3.md
```


## Stage 4: verification and rollback

Stage 4 adds synchronous rollout verification, automatic rollback proposal creation
after failed verification, and an audit trail.

Continue with:

```bash
cat STAGE4.md
```


## Stage 5: asynchronous repair Jobs

Stage 5 moves patching and rollout verification out of the HTTP request path
into short-lived Kubernetes Jobs with a separate worker ServiceAccount.

Continue with:

```bash
cat STAGE5.md
```


## Stage 5.1 fixes

Stage 5.1 rejects no-op proposals, avoids meaningless rollbacks, removes the
inherited ProgressDeadlineExceeded fast-fail, and hardens the operations endpoint.

See:

```bash
cat STAGE5_1_FIX.md
```
