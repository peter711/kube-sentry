# Stage 2 — function calling + Pod logs

This version changes the agent from a "full cluster snapshot in every prompt" design
to a real tool-calling loop.

## What the model can call

- `get_pods`
- `get_deployments`
- `get_services`
- `get_events`
- `get_pod_logs`

All Kubernetes access is restricted to namespace `ai-lab`.

The agent has read-only RBAC. `pods/log` is readable, but no create/update/delete
permissions are granted.

## Upgrade an already running Stage 1 cluster

From the project directory:

```bash
export OPENAI_API_KEY='YOUR_KEY_HERE'

kubectl apply -f k8s/10-rbac.yaml
./scripts/rebuild.sh
```

Confirm log permission:

```bash
kubectl -n ai-lab auth can-i get pods/log \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
yes
```

And confirm that write access is still blocked:

```bash
kubectl -n ai-lab auth can-i delete pods \
  --as=system:serviceaccount:ai-lab:ai-agent
```

Expected:

```text
no
```

## Inspect available agent tools

```bash
curl -s http://localhost:8080/tools
```

## Test 1 — image pull problem

```bash
kubectl apply -f demo/broken-nginx.yaml
```

Ask:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Dlaczego broken-nginx nie działa? Zdiagnozuj na podstawie klastra."}'
```

Expected behavior:

1. model calls `get_pods`
2. model calls `get_events`
3. it diagnoses `ErrImagePull` / `ImagePullBackOff`
4. it does not need application logs because the container never starts

## Test 2 — CrashLoopBackOff that requires logs

```bash
kubectl apply -f demo/crashy-app.yaml
```

Wait a little and inspect:

```bash
kubectl -n ai-lab get pods
```

Ask:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Dlaczego crashy-app się restartuje? Znajdź konkretną przyczynę."}'
```

Expected behavior:

1. `get_pods`
2. optionally `get_events`
3. `get_pod_logs` for the exact Pod
4. often `get_pod_logs(previous=true)` for the previous crashed container
5. diagnosis based on the `DATABASE_HOST=db.invalid` log line

The `/ask` response contains a `tool_calls` field, so you can see which tools the
model actually chose.

## Fix crashy-app

```bash
kubectl apply -f demo/fixed-crashy-app.yaml
kubectl -n ai-lab rollout status deploy/crashy-app
```

Then ask again:

```bash
curl -s \
  -X POST http://localhost:8080/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Czy crashy-app jest już zdrowy? Sprawdź to."}'
```

## Security notes

- The namespace is fixed server-side; the model cannot request another namespace.
- The agent cannot write to Kubernetes.
- Logs are truncated before they are sent to the model.
- A basic redactor removes common `password=`, `token=`, `api_key=` and Bearer-token patterns.
- Log content is explicitly treated as untrusted data to reduce prompt-injection risk.

For a production version, use a proper secret/log redaction layer rather than the
simple regex-based demonstration included here.
