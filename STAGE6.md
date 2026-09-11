# Stage 6 — Agent Observability

Stage 6 adds OpenTelemetry traces and metrics to both the FastAPI agent and the asynchronous repair worker.

## Architecture

```text
AI Agent API ---------------------+
  HTTP /ask                       |
  OpenAI Responses spans          | OTLP gRPC
  tool.* spans                    v
                           OpenTelemetry Collector ----> Tempo
Repair worker Job -----------+            |
  repair.worker              |            +-----------> Prometheus
  stale_check                |                            |
  deployment.patch ----------+                            v
  rollout.verify                                          Grafana
```

The API and worker use the same trace context. Short-lived worker Jobs explicitly flush telemetry before exit so their last spans/metrics are not lost. Approval injects W3C `traceparent` into the Kubernetes Job environment, so the worker trace is connected to the approval trace.

## What is traced

For `/ask` you should see spans similar to:

```text
POST /ask
  llm.openai.responses
  tool.get_deployment_details
  llm.openai.responses
  tool.get_events
  tool.get_pod_logs
  llm.openai.responses
```

For an approved repair:

```text
POST /repair/proposals/{id}/approve
  repair.approve
    kubernetes.job.create
      repair.worker
        repair.stale_check
        kubernetes.deployment.patch
        rollout.verify
          rollout.poll
          rollout.poll
          ...
```

## Privacy rule

Telemetry intentionally does **not** record:

- the user's full prompt,
- model output text,
- Pod log contents,
- Kubernetes Event message bodies,
- OpenAI API keys or Secret values.

Spans contain operational metadata such as tool name, Deployment name, proposal ID, timings, status and replica counters.

## Components and pinned versions

- OpenTelemetry Python SDK / OTLP exporter: `1.44.0`
- OpenTelemetry FastAPI instrumentation: `0.65b0`
- OpenTelemetry Collector Contrib: `0.160.0` (current release line used by this lab)
- Tempo: `3.0.2`
- Prometheus: `3.14.0`
- Grafana: `13.2.1`

Tempo runs in monolithic mode with local ephemeral trace storage. In Tempo 3, this mode does not require Kafka; Kafka is required for the microservices deployment mode.

## Deploy

```bash
export OPENAI_API_KEY='sk-...'
./scripts/deploy.sh
```

Check:

```bash
curl -s http://localhost:8080/health | jq
```

Expected:

```json
{"status":"ok","version":"0.6.0"}
```

Open Grafana:

```text
http://localhost:8080/grafana/
```

Anonymous Admin is enabled **only for this local lab**.

## Generate a diagnostic trace

Create or reset the demo:

```bash
kubectl apply -f demo/broken-nginx.yaml
```

Then:

```bash
./scripts/test-observability.sh
```

The `/ask` response now includes:

```json
"trace_id": "0123456789abcdef..."
```

In Grafana open:

```text
Dashboards -> AI Kubernetes Agent -> AI Kubernetes Agent Observability
```

For detailed spans:

```text
Explore -> Tempo
```

Search by trace ID or use TraceQL:

```text
{ resource.service.name = "ai-agent-api" }
```

Worker traces:

```text
{ resource.service.name = "ai-agent-worker" }
```

Tool calls only:

```text
{ name =~ "tool\..*" }
```

## Metrics

Prometheus receives metrics from the OTel Collector. Examples:

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

## Verify the collector

```bash
kubectl -n ai-lab logs deploy/otel-collector --tail=100
```

Check workloads:

```bash
kubectl -n ai-lab get pods
```

## Query Prometheus directly

In one terminal:

```bash
kubectl -n ai-lab port-forward svc/prometheus 9090:9090
```

Then:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=ai_agent_tool_calls_total' | jq
```

## RBAC correction carried into Stage 6

`/operations/{proposal_id}` now reads the normal `batch/jobs` resource with `read_namespaced_job()`. Kubernetes returns Job status in that object, so the API does not need `get jobs/status`.

Expected:

```bash
kubectl -n ai-lab auth can-i get jobs   --as=system:serviceaccount:ai-lab:ai-agent
# yes

kubectl -n ai-lab auth can-i get jobs   --subresource=status   --as=system:serviceaccount:ai-lab:ai-agent
# no
```

The `/operations` endpoint should still show `active`, `succeeded`, `failed` and Job conditions.

## Next stage

Stage 7 can build the operator UI on top of the already-observable APIs:

- conversations,
- trace links,
- pending proposals,
- approve/reject,
- operation state,
- audit timeline.
