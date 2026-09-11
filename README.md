# AI Kubernetes Lab

Local k3d/K3s lab for building a constrained AI Kubernetes diagnostic and remediation agent.

Current version: **Stage 6 / 0.6.0**.

## Safety model

- fixed namespace `ai-lab`,
- no arbitrary shell or `kubectl exec` tool,
- logs/events treated as untrusted data,
- basic secret redaction for logs,
- LLM cannot directly mutate Kubernetes,
- every mutation starts as a pending proposal,
- explicit human `APPLY` approval,
- API ServiceAccount cannot patch Deployments,
- separate worker ServiceAccount performs constrained patching,
- failed verification only creates a rollback proposal; rollback is never auto-applied.

## Stage 6

Adds OpenTelemetry, Tempo, Prometheus and Grafana. The most useful new feature is end-to-end tracing of model calls, agent tool calls, repair approval, worker Jobs and rollout verification.

See `STAGE6.md`.

## Quick start

```bash
./scripts/create-cluster.sh
export OPENAI_API_KEY='sk-...'
./scripts/deploy.sh
curl -s http://localhost:8080/health | jq
```

Grafana:

```text
http://localhost:8080/grafana/
```
