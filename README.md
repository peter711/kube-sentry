# Kube Sentry

A local k3d/K3s lab for building a **constrained AI agent** that diagnoses and
repairs workloads in a Kubernetes namespace. The project is built in
incremental stages, from a simple read-only chat-with-your-cluster agent to a
fully observable, asynchronous, human-in-the-loop repair pipeline with a
React operator console.

Current version: **0.6.0** (backend), UI `0.7.0.2`.

## Table of contents

- [Why this project exists](#why-this-project-exists)
- [Safety model](#safety-model)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Repair lifecycle](#repair-lifecycle)
- [API reference](#api-reference)
- [Demo scenarios](#demo-scenarios)
- [RBAC verification](#rbac-verification)
- [Observability](#observability)
- [Operator UI](#operator-ui)
- [Local UI development](#local-ui-development)
- [Development history (stages)](#development-history-stages)
- [Production notes / known lab limitations](#production-notes--known-lab-limitations)
- [Troubleshooting](#troubleshooting)

## Why this project exists

This is a learning/reference project for wiring an LLM tool-calling agent to
a real Kubernetes cluster **without** giving the model shell access or direct
write permissions. Every capability the model has is a narrow, purpose-built
tool. Every mutation goes through a proposal, human approval, and automated
rollout verification, with a rollback path if verification fails.

## Safety model

- fixed namespace `ai-lab` — the model cannot target any other namespace,
- no arbitrary shell, `exec`, or generic `kubectl` tool exposed to the model,
- Kubernetes logs and events are treated as **untrusted data** (prompt-injection surface),
- basic secret redaction is applied to log content before it reaches the model,
- the LLM cannot directly mutate Kubernetes — it can only create a **pending proposal**,
- every mutation requires an explicit human `APPLY` confirmation,
- the API ServiceAccount **cannot** patch Deployments,
- a separate, least-privilege **worker** ServiceAccount performs the actual constrained patch,
- stale proposals (Deployment changed since the proposal was created) are rejected instead of applied,
- a failed rollout only ever creates a **rollback proposal** — rollback is never auto-applied.

## Architecture

```text
Browser
  |
  | http://localhost:8080
  v
Traefik (k3d loadbalancer, bound to 127.0.0.1:8080)
  |---- /ui/*       --> ai-agent-ui       (nginx + React static build)
  |---- /grafana/*  --> Grafana
  `---- /*          --> ai-agent          (FastAPI)

ai-agent (FastAPI, ServiceAccount: ai-agent)
  |
  |-- read-only Kubernetes tools (pods, deployments, services, events, logs)
  |-- SQLite conversation memory + repair proposals (PVC-backed)
  |-- OpenTelemetry traces/metrics (OTLP gRPC) ---------------------> otel-collector
  |
  `-- POST /repair/proposals/{id}/approve
        creates a Kubernetes Job (traceparent injected)
              |
              v
      repair worker (ServiceAccount: ai-agent-worker)
        |-- stale check (Deployment generation)
        |-- constrained Deployment patch (image or replica count)
        |-- rollout verification (bounded poll window)
        |-- audit event + rollback proposal on failure
        `-- flushes telemetry before exit
                                                          otel-collector --> Tempo (traces)
                                                                        --> Prometheus (metrics)
                                                                              --> Grafana (dashboards)
```

Two Kubernetes identities matter:

| ServiceAccount     | Can patch Deployments | Can create Jobs | Purpose                       |
|---------------------|:---------------------:|:---------------:|--------------------------------|
| `ai-agent`           | no                     | yes              | API: read cluster state, queue repairs |
| `ai-agent-worker`     | yes (constrained)      | n/a              | Executes exactly one approved repair Job |

## Repository layout

```text
agent/            FastAPI agent (app.py), agent tools (tools.py), async repair worker (worker.py), OTel setup
ui/               React 19 + TypeScript + Vite operator console
k8s/              Namespace, RBAC, PVC, Deployment/Service/Ingress manifests
observability/    OpenTelemetry Collector, Tempo, Prometheus, Grafana manifests
scripts/          create-cluster.sh, deploy.sh, deploy-ui.sh, rebuild.sh, test-observability.sh
demo/             Sample broken/fixed Deployments used to exercise the agent
```

## Prerequisites

- Docker
- [k3d](https://k3d.io/)
- `kubectl`
- `jq` (used in examples below)
- An OpenAI API key
- Node.js 20+ (only needed for local UI development, see below)

## Quick start

```bash
./scripts/create-cluster.sh
export OPENAI_API_KEY='sk-...'
./scripts/deploy.sh
./scripts/deploy-ui.sh   # optional: React operator console

curl -s http://localhost:8080/health | jq
```

Expected:

```json
{"status": "ok", "version": "0.6.0"}
```

Open in a browser:

```text
http://localhost:8080/ui/         # operator console
http://localhost:8080/grafana/    # traces, metrics, dashboards (anonymous admin, local lab only)
```

To rebuild only the agent image after a code change:

```bash
./scripts/rebuild.sh
```

To rebuild only the UI after a code change:

```bash
./scripts/deploy-ui.sh
```

## Repair lifecycle

```text
diagnose
  -> propose                (model calls a propose_* tool; nothing changes yet)
  -> human approve           (POST .../approve with confirmation: "APPLY")
  -> Kubernetes Job queued   (API returns immediately, does not block on the rollout)
  -> worker applies patch
  -> worker verifies rollout
      -> healthy => verified
      -> failed  => rollback proposal created
                      -> human approve
                      -> apply rollback (another Job)
                      -> verify rollback
```

A proposal can only change **one** of:

- a Deployment's container image, or
- a Deployment's replica count (0-10).

A proposal is rejected outright if it is a no-op (requested state == current
state). A rollback proposal is only created if the pre-change state actually
differs from the failed target state.

A rollout is considered healthy only when **all** of the following hold for
the Deployment:

```text
observed_generation >= generation
current_replicas     == desired
updated_replicas     == desired
ready_replicas       == desired
available_replicas   == desired
unavailable_replicas == 0
```

Checking all six counters (not just ready/available) avoids a false-positive
during a `RollingUpdate`, where an old healthy replica can keep the aggregate
counters looking fine while the new, broken replica is still starting.

Default verification timeout is 90 seconds, overridable via the `ai-agent`
Deployment env var `VERIFY_TIMEOUT_SECONDS` (20-30s is convenient for local
testing).

Staleness is decided by comparing the Deployment's `metadata.generation`
captured at proposal time, not `resourceVersion` (which also changes on
status-only updates and would cause spurious staleness).

## API reference

All endpoints are served by the `ai-agent` FastAPI app, same-origin behind
Traefik at `http://localhost:8080`.

| Method | Path                                       | Purpose |
|--------|---------------------------------------------|---------|
| GET    | `/health`                                    | Liveness + version |
| POST   | `/ask`                                        | Ask the agent a question; runs the tool-calling loop |
| GET    | `/conversations/{conversation_id}`            | Fetch stored conversation turns |
| GET    | `/repair/proposals`                           | List repair proposals (optional `?status=pending`) |
| GET    | `/repair/proposals/{proposal_id}`              | Fetch one proposal |
| POST   | `/repair/proposals/{proposal_id}/approve`      | Approve; body: `{"confirmation":"APPLY","approved_by":"<name>"}` |
| POST   | `/repair/proposals/{proposal_id}/reject`       | Reject; body: `{"reason":"<why>"}` |
| GET    | `/operations/{proposal_id}`                    | Poll worker Job / rollout status for an approved proposal |
| GET    | `/audit`                                       | Audit event timeline |

`POST /ask` accepts an optional `conversation_id` to continue an existing
conversation; the response includes `tool_calls` (which tools the model
actually invoked) and `trace_id` (for looking the run up in Tempo/Grafana).

Tools available to the model (all scoped to namespace `ai-lab`, read-only
unless explicitly a `propose_*` tool): `get_pods`, `get_deployments`,
`get_services`, `get_events`, `get_pod_logs` (supports `previous=true`),
plus the constrained `propose_image_change` / `propose_replica_change`
proposal tools.

### Example: ask a question

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Why is broken-nginx not working? Diagnose from the cluster."}' | jq
```

### Example: create and approve a repair

```bash
curl -s -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Diagnose broken-nginx and prepare a safe image-fix proposal. Do not change anything yet."}' | jq

curl -s -X POST http://localhost:8080/repair/proposals/PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{"confirmation":"APPLY","approved_by":"your-name"}' | jq

curl -s http://localhost:8080/operations/PROPOSAL_ID | jq
```

Expected operation transitions: `queued -> running -> verified` (or `failed`,
which produces a new pending rollback proposal).

## Demo scenarios

Sample manifests live in `demo/`.

**Image pull failure (no logs needed):**

```bash
kubectl apply -f demo/broken-nginx.yaml
```

The model should call `get_pods` and `get_events`, diagnose
`ErrImagePull`/`ImagePullBackOff`, and not need `get_pod_logs` since the
container never starts.

**CrashLoopBackOff (needs logs):**

```bash
kubectl apply -f demo/crashy-app.yaml
```

The model should call `get_pods`, optionally `get_events`, then
`get_pod_logs` (often with `previous=true` for the crashed container), and
diagnose the root cause from a `DATABASE_HOST=db.invalid` log line.

Fix it:

```bash
kubectl apply -f demo/fixed-crashy-app.yaml
kubectl -n ai-lab rollout status deploy/crashy-app
```

**Reset to a known-good baseline before testing a bad rollout:**

```bash
kubectl apply -f demo/fixed-nginx.yaml
kubectl -n ai-lab rollout status deploy/broken-nginx
```

## RBAC verification

Read access (API identity):

```bash
kubectl -n ai-lab auth can-i get pods/log \
  --as=system:serviceaccount:ai-lab:ai-agent
# yes
```

Write access is blocked on the API identity:

```bash
kubectl -n ai-lab auth can-i patch deployments \
  --as=system:serviceaccount:ai-lab:ai-agent
# no

kubectl -n ai-lab auth can-i delete deployments \
  --as=system:serviceaccount:ai-lab:ai-agent
# no
```

The API identity can only queue work:

```bash
kubectl -n ai-lab auth can-i create jobs.batch \
  --as=system:serviceaccount:ai-lab:ai-agent
# yes
```

Only the worker identity can patch:

```bash
kubectl -n ai-lab auth can-i patch deployments \
  --as=system:serviceaccount:ai-lab:ai-agent-worker
# yes
```

If any of these come back wrong after an upgrade, inspect leftover RBAC
objects (renamed Roles/RoleBindings are not deleted by `kubectl apply`):

```bash
kubectl -n ai-lab get role,rolebinding
```

## Observability

Stage 6 adds OpenTelemetry traces and metrics across the API and the async
repair worker, using a shared trace context (the approval step injects a W3C
`traceparent` into the worker Job's environment).

Pipeline: `ai-agent` / `ai-agent-worker` → OTLP gRPC → OpenTelemetry Collector
→ Tempo (traces) + Prometheus (metrics) → Grafana (dashboards).

**Privacy rule** — telemetry never records: the user's full prompt, model
output text, Pod log contents, Kubernetes Event message bodies, or secret
values. Spans only carry operational metadata (tool name, Deployment name,
proposal ID, timings, status, replica counters).

Generate a sample trace:

```bash
kubectl apply -f demo/broken-nginx.yaml
./scripts/test-observability.sh
```

The `/ask` response includes a `trace_id`. In Grafana:

```text
Dashboards -> AI Kubernetes Agent -> AI Kubernetes Agent Observability
Explore -> Tempo  (search by trace ID or TraceQL)
```

Useful TraceQL:

```text
{ resource.service.name = "ai-agent-api" }
{ resource.service.name = "ai-agent-worker" }
{ name =~ "tool\..*" }
```

Example metrics available in Prometheus/Grafana:

```text
ai_agent_requests_total
ai_agent_tool_calls_total
ai_agent_tool_duration_seconds_bucket
ai_agent_llm_requests_total
ai_agent_llm_duration_seconds_bucket
ai_agent_llm_tokens_total
ai_agent_proposals_total
ai_agent_repair_operations_total
ai_agent_rollout_duration_seconds_bucket
ai_agent_rollbacks_total
```

Query Prometheus directly:

```bash
kubectl -n ai-lab port-forward svc/prometheus 9090:9090
curl -s 'http://localhost:9090/api/v1/query?query=ai_agent_tool_calls_total' | jq
```

Pinned component versions: OpenTelemetry Python SDK/OTLP exporter `1.44.0`,
FastAPI instrumentation `0.65b0`, OpenTelemetry Collector Contrib `0.160.0`,
Tempo `3.0.2` (monolithic mode, local ephemeral storage — no Kafka needed),
Prometheus `3.14.0`, Grafana `13.2.1`.

## Operator UI

Stage 7 adds a same-origin React console on top of the FastAPI API. It
complements Grafana/Tempo rather than replacing them.

- **Agent** — ask questions, browse conversation history, see grouped tool
  calls per round, link out to the Grafana trace for a run.
- **Proposals** — list, before/after diff preview, explicit two-step
  `APPLY` confirmation, approve/reject.
- **Operations** — derived from approved proposals; polls
  `/operations/{proposal_id}` every second while `queued`/`running`, stops
  on terminal status; shows Job name, workflow steps, replica counters.
- **Audit** — expandable audit timeline from `/audit`.

Stack: React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Router/Query/Table,
Lucide React, Sonner. UI primitives are kept small and local rather than
pulling in a full admin template.

The UI is served at `http://localhost:8080/ui/` via nginx, running as a
non-root container (UID/GID `101`, read-only root filesystem, all Linux
capabilities dropped, temp paths under an `emptyDir` `/tmp`, no Kubernetes
API token mounted).

## Local UI development

Keep the backend running (`./scripts/deploy.sh` against the cluster), then:

```bash
cd ui
npm install
npm run dev
```

Open `http://localhost:5173/ui/`. Vite proxies API calls to
`http://localhost:8080`.

## Development history (stages)

The project was built incrementally; each stage is summarized below.

| Stage | Focus |
|-------|-------|
| 1     | Baseline agent: full cluster snapshot sent to the model each turn |
| 2     | Real tool-calling loop; read-only Kubernetes tools scoped to `ai-lab`; log-based diagnosis |
| 3     | Persistent SQLite conversation memory (PVC-backed); constrained repair proposals; explicit human `APPLY` approval; stale-proposal protection via `resourceVersion` |
| 4     | Full lifecycle: propose → approve → apply → verify → rollback-on-failure; audit trail |
| 4.1   | Fixed a false-positive verification during `RollingUpdate` (added `current_replicas`/`unavailable_replicas` checks); switched staleness check from `resourceVersion` to `metadata.generation` |
| 5     | Moved repair execution out of the request path into an async Kubernetes Job run by a separate, least-privilege worker ServiceAccount; API loses `patch deployments` |
| 5.1   | Rejected no-op proposals; rollback only created when pre-change state actually differs; verification no longer trusts an inherited `ProgressDeadlineExceeded`; `/operations` endpoint hardened against client errors |
| 6     | OpenTelemetry traces/metrics across API and worker with shared trace context; OTel Collector, Tempo, Prometheus, Grafana added; strict privacy rule on span content |
| 7     | React operator console (Agent, Proposals, Operations, Audit screens) served same-origin behind Traefik; non-root/read-only nginx runtime fix (7.0.2) |

## Production notes / known lab limitations

- **Synchronous verification pre-Stage-5**: early stages verified rollouts
  inside the HTTP request. Stage 5+ fixes this with a Job-based worker; a
  real system would still want a durable queue/controller rather than a
  single Job per proposal.
- **Shared SQLite on an RWO PVC**: acceptable for this single-node local lab
  (local-path volumes keep consumers on the same node; SQLite WAL + busy
  timeouts reduce lock contention) but not appropriate for a multi-node
  production deployment. Use PostgreSQL and a real work queue or
  controller reconciliation loop instead.
- **No auth on the approval endpoint**: `approved_by` is a free-text field,
  not an authenticated identity. Add real authentication/authorization
  before exposing this beyond a local lab.
- **Anonymous Grafana admin** is enabled — intentional for this local lab
  only, never do this on a shared or internet-reachable instance.
- **Log/secret redaction** is a simple regex-based demonstration
  (`password=`, `token=`, `api_key=`, Bearer tokens). Use a proper
  secret-scanning/redaction layer in production.
- The k3d cluster binds the ingress to `127.0.0.1:8080` (not `0.0.0.0`) so
  the approval API is not exposed to your LAN by default.

## Troubleshooting

**`OPENAI_API_KEY is not set and Secret/openai-api does not exist`** — export
`OPENAI_API_KEY` before running `./scripts/deploy.sh`, or ensure the Secret
already exists in the `ai-lab` namespace.

**RBAC check unexpectedly returns `yes` after an upgrade** — a Role/RoleBinding
was likely renamed between stages; `kubectl apply` doesn't delete objects
that no longer exist in the new manifests. Run
`kubectl -n ai-lab get role,rolebinding` and remove stale ones.

**`/operations/{id}` errors** — check the worker Job and Pod directly:

```bash
kubectl -n ai-lab get jobs
kubectl -n ai-lab get pods -l app=ai-agent-worker
kubectl -n ai-lab logs POD_NAME
```

**Collector / Tempo / Prometheus not receiving data**:

```bash
kubectl -n ai-lab logs deploy/otel-collector --tail=100
kubectl -n ai-lab get pods
```
