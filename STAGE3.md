# Stage 3 — memory + detailed inspection + human-approved repairs

Stage 3 adds three major capabilities:

1. Persistent local conversation memory in SQLite on a Kubernetes PVC.
2. More detailed inspection tools for Pods and Deployments.
3. Constrained repair proposals that require explicit human approval before Kubernetes is patched.

## Security model

The model still has no direct "apply", shell, kubectl, exec, or arbitrary patch tool.

The model can only create a pending proposal for:

- changing one Deployment container image;
- scaling one Deployment between 0 and 10 replicas.

The actual Kubernetes patch happens only when a human calls the approval endpoint
with the exact confirmation string `APPLY`.

Every proposal stores the Deployment `resourceVersion` observed at proposal time.
If the Deployment changes before approval, the proposal becomes stale and is not applied.

## Upgrade from Stage 2

From the Stage 3 project directory, use the full deploy script. It rebuilds the
image and applies the new RBAC, PVC, Deployment mount, Service, and Ingress in
the correct order:

```bash
export OPENAI_API_KEY='YOUR_KEY_HERE'
./scripts/deploy.sh
```

Check the new permissions:

```bash
kubectl -n ai-lab auth can-i patch deployments \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
yes
```

But dangerous operations are still blocked:

```bash
kubectl -n ai-lab auth can-i delete deployments \
  --as=system:serviceaccount:ai-lab:ai-agent

kubectl -n ai-lab auth can-i create pods \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
no
no
```

## 1. Test persistent conversation memory

Ask a first question:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Zdiagnozuj broken-nginx i zapamiętaj, że będziemy pracować nad tym deploymentem."}'
```

Copy the returned `conversation_id`, for example:

```text
conv_a1b2c3d4e5f6
```

Continue the same conversation:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id":"conv_a1b2c3d4e5f6",
    "question":"Jaki problem znaleźliśmy poprzednio?"
  }'
```

Inspect stored turns:

```bash
curl -s http://localhost:8080/conversations/conv_a1b2c3d4e5f6
```

Restart the Pod:

```bash
kubectl -n ai-lab rollout restart deploy/ai-agent
kubectl -n ai-lab rollout status deploy/ai-agent
```

Ask again using the same conversation ID. The history should still be available because
SQLite is stored on `ai-agent-data` PVC.

## 2. Create a repair proposal

Make sure the deliberately broken Deployment exists:

```bash
kubectl apply -f demo/broken-nginx.yaml
```

Ask the agent to prepare a repair, not apply it:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question":"Zdiagnozuj broken-nginx i przygotuj bezpieczną propozycję naprawy obrazu kontenera. Niczego jeszcze nie zmieniaj."
  }'
```

The response should include something like:

```json
{
  "proposal_ids": ["rp_123456789abc"]
}
```

Inspect it:

```bash
curl -s http://localhost:8080/repair/proposals/rp_123456789abc
```

At this point Kubernetes has NOT been modified.

Verify:

```bash
kubectl -n ai-lab get deploy broken-nginx \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

It should still show:

```text
nginx:this-tag-does-not-exist
```

## 3. Explicitly approve

Apply only after human review:

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/rp_123456789abc/approve \
  -H 'Content-Type: application/json' \
  -d '{"confirmation":"APPLY"}'
```

Watch the rollout:

```bash
kubectl -n ai-lab rollout status deploy/broken-nginx
kubectl -n ai-lab get pods
```

Inspect the resulting image:

```bash
kubectl -n ai-lab get deploy broken-nginx \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

## 4. Reject instead of approve

```bash
curl -s \
  -X POST http://localhost:8080/repair/proposals/PROPOSAL_ID/reject \
  -H 'Content-Type: application/json' \
  -d '{"reason":"Chcę najpierw sprawdzić inną wersję obrazu."}'
```

## 5. Test stale-proposal protection

Create a proposal, but before approving it manually change the Deployment:

```bash
kubectl -n ai-lab scale deploy/broken-nginx --replicas=2
```

Now try to approve the old proposal.

The API should return HTTP 409 and mark it `stale` because the Deployment
`resourceVersion` changed after the proposal was created.

## 6. List proposals

All:

```bash
curl -s http://localhost:8080/repair/proposals
```

Only pending:

```bash
curl -s 'http://localhost:8080/repair/proposals?status=pending'
```

## Important local-only note

The Stage 3 cluster creation script binds the ingress port to `127.0.0.1:8080`
so the approval API is not intentionally exposed to your LAN.

If your cluster was created with an older Stage 1/2 script, this port mapping does
not change automatically. Recreate the local cluster with the Stage 3 script if
you want the localhost-only binding.

For a production implementation, add real authentication/authorization around
the approval endpoint and use a dedicated repair controller or separate identity
for mutation permissions.
