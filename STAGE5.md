# Stage 5 — asynchronous Job-based repair execution

Stage 5 removes repair execution from the HTTP request path.

## Architecture

```text
user
  |
  v
FastAPI /approve
  |
  | creates Job
  v
Kubernetes Job
  |
  v
worker.py
  |
  +--> stale check
  +--> constrained Deployment patch
  +--> rollout verification
  +--> audit
  +--> rollback proposal on failure
```

The approval API returns immediately:

```json
{
  "status": "queued",
  "job_name": "repair-rp-..."
}
```

You then poll:

```bash
curl -s http://localhost:8080/operations/PROPOSAL_ID | jq
```

## Important RBAC change

The API ServiceAccount can no longer patch Deployments:

```bash
kubectl -n ai-lab auth can-i patch deployments \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
no
```

The worker identity can:

```bash
kubectl -n ai-lab auth can-i patch deployments \
  --as=system:serviceaccount:ai-lab:ai-agent-worker
```

Expected:

```text
yes
```

The API can create Jobs:

```bash
kubectl -n ai-lab auth can-i create jobs.batch \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
yes
```

## Upgrade

```bash
export OPENAI_API_KEY='YOUR_KEY_HERE'
./scripts/deploy.sh
```

Check:

```bash
curl -s http://localhost:8080/health | jq
```

Expected version:

```text
0.5.0
```

## Happy-path test

Create broken nginx:

```bash
kubectl apply -f demo/broken-nginx.yaml
```

Ask for a repair proposal:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"Zdiagnozuj broken-nginx i przygotuj propozycję naprawy obrazu. Niczego jeszcze nie zmieniaj."
  }' | jq
```

Approve:

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{
    "confirmation":"APPLY",
    "approved_by":"Piotr"
  }' | jq
```

You should get `queued` immediately.

Inspect the Job:

```bash
kubectl -n ai-lab get jobs
kubectl -n ai-lab get pods -l app=ai-agent-worker
```

Poll operation state:

```bash
watch -n 1 \
  'curl -s http://localhost:8080/operations/PROPOSAL_ID | jq'
```

Expected transitions:

```text
queued
running
verified
```

## Failure and rollback test

Start from healthy nginx:

```bash
kubectl apply -f demo/fixed-nginx.yaml
kubectl -n ai-lab rollout status deploy/broken-nginx
```

Ask for a bad image proposal and approve it.

Expected proposal transitions:

```text
queued
running
failed
```

The **proposal** is failed because rollout verification failed. The Kubernetes
worker Job itself should normally show `Succeeded`, because the worker handled
the failure correctly and created a rollback proposal. A Job in `Failed` state
means the worker process/infrastructure itself failed.

The failed proposal should create a new pending rollback proposal.

Find it:

```bash
curl -s http://localhost:8080/repair/proposals | jq
```

Approve the rollback proposal exactly the same way.

The rollback itself is another Kubernetes Job and should transition:

```text
queued
running
verified
```

## Worker logs

List worker Pods:

```bash
kubectl -n ai-lab get pods -l app=ai-agent-worker
```

Read one:

```bash
kubectl -n ai-lab logs POD_NAME
```

## Audit trail

```bash
curl -s http://localhost:8080/audit | jq
```

New Stage 5 events include:

```text
proposal_queued
execution_started
proposal_applied
verification_completed
rollback_proposal_generated
worker_failed
job_creation_failed
```

## Why this is better

The HTTP request no longer waits for a rollout.

The API identity cannot patch Deployments.

The worker is disposable and managed by Kubernetes.

Kubernetes provides retry/backoff and status for execution Jobs.

## Lab limitation: SQLite + RWO PVC

Both the API and worker Jobs share the same SQLite database on the same PVC.

This is acceptable for this local k3d lab because the PVC is `ReadWriteOnce` and
the local-path volume keeps consumers on the volume's node. SQLite WAL and busy
timeouts reduce lock contention.

For a real multi-node production system, replace SQLite with PostgreSQL and use a
proper work queue or controller reconciliation loop. Do not use shared SQLite as
a production distributed queue.


## Upgrade check: make sure old Stage 4 RBAC is gone

Stage 4 used a Role and RoleBinding named `ai-agent`. `kubectl apply` does not
delete renamed Kubernetes objects, so the Stage 5 deploy script explicitly
removes those old RBAC resources.

After upgrade, verify:

```bash
kubectl -n ai-lab auth can-i patch deployments \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
no
```

If this says `yes`, inspect bindings before continuing:

```bash
kubectl -n ai-lab get role,rolebinding
```
