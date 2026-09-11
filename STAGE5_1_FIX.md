# Stage 5.1 — no-op, inherited rollout condition, and operations endpoint fixes

This patch fixes three issues exposed by the Stage 5 test.

## 1. No-op proposals are rejected

If the Deployment already uses the requested image, the agent-side proposal
function now returns an error instead of creating a proposal.

Example:

```text
current image:   nginx:this-tag-does-not-exist
requested image: nginx:this-tag-does-not-exist
```

Result:

```text
no-op proposal rejected
```

The worker also performs a defensive no-op check before mutation.

## 2. Rollback is only created when there is a different previous state

A failed image-change proposal can only roll back if the captured `before`
image differs from the attempted image.

This prevents meaningless rollback proposals such as:

```text
bad image -> bad image
rollback -> same bad image
```

## 3. Verification no longer fails immediately on an inherited
`ProgressDeadlineExceeded`

A Deployment may still carry a failed `Progressing` condition from an earlier
rollout. Stage 5 could therefore finish a new worker Job almost immediately.

Stage 5.1 always uses the bounded rollout-verification window for this lab
instead of immediately trusting a pre-existing ProgressDeadlineExceeded
condition.

## 4. `/operations/{proposal_id}` is defensive

The endpoint now catches Kubernetes client/attribute errors and returns them as
JSON in the `job` object instead of allowing FastAPI to emit a plain-text
`Internal Server Error`.

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
  "version": "0.5.1"
}
```

## Clean test sequence

Before testing a bad rollout, first force a known-good baseline:

```bash
kubectl apply -f demo/fixed-nginx.yaml
kubectl -n ai-lab rollout status deploy/broken-nginx

kubectl -n ai-lab get deploy broken-nginx \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

Expected:

```text
nginx:alpine
```

Only then ask for the bad image proposal.

After approval:

```bash
curl -s http://localhost:8080/operations/PROPOSAL_ID | jq
```

The operation should move from `queued` to `running` and eventually `failed`,
then create a rollback proposal whose payload restores `nginx:alpine`.
