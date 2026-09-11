# Stage 4.1 — RollingUpdate verification fix

Stage 4.0 had a verifier bug that could produce a false positive during a
RollingUpdate.

## What happened

For a Deployment with `replicas: 1`, Kubernetes can temporarily have:

```text
old ReplicaSet:
  nginx:alpine
  Ready = 1

new ReplicaSet:
  nginx:this-tag-does-not-exist
  Ready = 0
  ImagePullBackOff
```

Because RollingUpdate allows surge capacity, Deployment aggregate counters can
temporarily look like:

```text
desired            = 1
updated_replicas   = 1   # the new, broken Pod exists
ready_replicas     = 1   # the old Pod is still ready
available_replicas = 1   # the old Pod is still available
current_replicas   = 2   # THIS is the important missing signal
```

Stage 4.0 checked the first three counters but not the total current replica
count, so it could incorrectly mark the rollout healthy.

## Stage 4.1 completion rule

A rollout is now healthy only when all are true:

```text
observed_generation >= generation
current_replicas     == desired
updated_replicas     == desired
ready_replicas       == desired
available_replicas   == desired
unavailable_replicas == 0
```

`current_replicas == desired` plus `updated_replicas == desired` means no old
non-terminating replicas remain.

The verifier also records only Pods that actually belong to the Deployment,
instead of all ReplicaSet-owned Pods in the namespace.

## Stale proposal fix

Stage 4.0 used `resourceVersion` to decide whether a proposal was stale.

That is too strict because status-only updates can also change resourceVersion.

Stage 4.1 compares the Deployment `metadata.generation` captured when the
proposal was created. A spec change increments generation; routine status
updates do not.

## Upgrade

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
  "version": "0.4.1"
}
```

## Re-test the failure / rollback path

Start from a known healthy image:

```bash
kubectl apply -f demo/fixed-nginx.yaml
kubectl -n ai-lab rollout status deploy/broken-nginx
```

Ask for a bad-image proposal:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"Przygotuj propozycję zmiany obrazu deploymentu broken-nginx na nginx:this-tag-does-not-exist, ale niczego jeszcze nie zmieniaj."
  }' | jq
```

Approve the returned proposal:

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{
    "confirmation":"APPLY",
    "approved_by":"Piotr"
  }' | jq
```

Expected result after the verification timeout:

```text
status = failed
rollback_proposal.proposal_id = rp_...
```

The verification snapshot should show that the bad rollout never reached a
state where the total/current replicas, updated replicas, and ready/available
replicas all describe the same completed revision.

Approve the generated rollback proposal and it should itself verify as healthy.
