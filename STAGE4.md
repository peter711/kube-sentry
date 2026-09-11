# Stage 4 — verification, rollback proposal, and audit trail

Stage 4 extends the repair lifecycle:

```text
diagnose
  -> propose
  -> human approve
  -> apply
  -> verify rollout
      -> healthy => verified
      -> failed  => rollback proposal
                     -> human approve
                     -> apply rollback
                     -> verify rollback
```

## Upgrade

From the Stage 4 project directory:

```bash
export OPENAI_API_KEY='YOUR_KEY_HERE'
./scripts/deploy.sh
```

Check:

```bash
curl -s http://localhost:8080/health | jq
```

Expected:

```json
{
  "status": "ok",
  "version": "0.4.0"
}
```

## Happy-path verification

Create the broken deployment again:

```bash
kubectl apply -f demo/broken-nginx.yaml
```

Ask the agent for a repair proposal:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"Zdiagnozuj broken-nginx i przygotuj propozycję naprawy obrazu. Niczego jeszcze nie zmieniaj."
  }' | jq
```

Approve with an explicit actor:

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{
    "confirmation":"APPLY",
    "approved_by":"marcin"
  }' | jq
```

The endpoint now waits for rollout verification and returns either:

```json
{
  "status": "verified",
  "verification": {
    "status": "healthy"
  }
}
```

or:

```json
{
  "status": "failed",
  "verification": {
    "status": "failed"
  },
  "rollback_proposal": {
    "proposal_id": "rp_..."
  }
}
```

## Deliberately test rollback flow

Create a normal healthy nginx first:

```bash
kubectl apply -f demo/fixed-nginx.yaml
kubectl -n ai-lab rollout status deploy/broken-nginx
```

Ask for a deliberately bad proposal:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"Przygotuj propozycję zmiany obrazu deploymentu broken-nginx na nginx:this-tag-does-not-exist, ale niczego jeszcze nie zmieniaj."
  }' | jq
```

Approve it:

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{
    "confirmation":"APPLY",
    "approved_by":"marcin"
  }' | jq
```

The verification should fail after the configured timeout.

The response should include a new rollback proposal that restores the previous image.

Inspect it:

```bash
curl -s \
  http://localhost:8080/repair/proposals/ROLLBACK_PROPOSAL_ID \
  | jq
```

Then approve the rollback:

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/ROLLBACK_PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{
    "confirmation":"APPLY",
    "approved_by":"marcin"
  }' | jq
```

That rollback is itself verified.

## Audit trail

Show recent audit events:

```bash
curl -s http://localhost:8080/audit | jq
```

You will see events such as:

```text
proposal_created
proposal_applied
verification_completed
proposal_rejected
proposal_stale
```

Each audit event includes:

- proposal ID
- actor
- before/after data where relevant
- action and payload
- verification result
- timestamp

## Verification behavior

The lab considers a Deployment healthy when:

- observed generation reached current generation
- updated replicas == desired replicas
- ready replicas == desired replicas
- available replicas == desired replicas

Default verification timeout:

```text
90 seconds
```

You can override it in the Deployment environment:

```yaml
- name: VERIFY_TIMEOUT_SECONDS
  value: "30"
```

For local testing, 20-30 seconds is often more convenient.

## Important production note

This lab performs verification synchronously inside the approval HTTP request.

That is fine for a local educational project, but in a production system you would
usually move the workflow to a durable job/controller/queue:

```text
approval API
  -> enqueue repair
  -> worker/controller applies
  -> worker watches rollout
  -> audit store updated
  -> UI polls or receives event
```

This avoids holding a request open during long rollouts and makes retries/recovery easier.
