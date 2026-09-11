# Stage 7 — React Operator Console MVP

Stage 7 adds a same-origin React UI on top of the Stage 6 FastAPI API. It intentionally does not replace Grafana/Tempo.

## MVP screens

### Agent

- conversation persisted in browser `localStorage`,
- `/ask` form,
- conversation history from `/conversations/{id}`,
- latest tool calls grouped by agent round,
- expandable tool arguments,
- trace ID and link to Grafana.

### Proposals

- proposals list from `/repair/proposals`,
- status and rollback context,
- before/after change preview,
- explicit second-step APPLY confirmation,
- approve and reject mutations.

### Operations

- uses approved proposals as the operation index,
- polls `/operations/{proposal_id}` every second only while queued/running,
- stops polling on terminal status,
- shows Job name, workflow steps and rollout replica counters.

### Audit

- compact expandable audit timeline from `/audit`.

## Architecture

```text
Browser
  |
  | http://localhost:8080/ui/
  v
Traefik
  |---- /ui/* ------> ai-agent-ui (nginx + React static files)
  |---- /grafana/* --> Grafana
  `---- /* ----------> FastAPI ai-agent
```

Because the React UI and FastAPI API use the same origin, Stage 7 does not require CORS configuration.

## Frontend stack

- React 19.3
- TypeScript 7.0
- Vite 8.2
- Tailwind CSS 4.3
- TanStack Router
- TanStack Query
- TanStack Table dependency included for the next table iteration
- Lucide React
- Sonner

The first MVP keeps UI primitives local and small instead of pulling an admin template. The component structure is compatible with moving to generated shadcn components incrementally.

## Install over Stage 6

Extract the Stage 7 overlay into the parent directory of your existing `ai-k8s-lab` repo, so these files merge into it:

```text
ai-k8s-lab/
  ui/
  k8s/50-ui.yaml
  scripts/deploy-ui.sh
  STAGE7.md
```

No Stage 6 backend files are replaced in this iteration.

## Local development

Keep Stage 6 running on port 8080, then:

```bash
cd ui
npm install
npm run dev
```

Open:

```text
http://localhost:5173/ui/
```

Vite proxies API calls to `http://localhost:8080`.

## Kubernetes deployment

From the repository root:

```bash
./scripts/deploy-ui.sh
```

Open:

```text
http://localhost:8080/ui/
```

## Useful checks

```bash
kubectl -n ai-lab get pods
kubectl -n ai-lab get ingress
curl -I http://localhost:8080/ui/
```

## Why there is no `/operations` list endpoint yet

The current backend already exposes the proposal list and each proposal includes `execution_job_name`. The MVP derives its Operations sidebar from those proposals, so Stage 7 can be deployed without a backend migration.

A later Stage 7.1 can add purpose-built endpoints:

```text
GET /conversations
GET /operations
GET /status
GET /traces/{trace_id}/summary
```

## Next UI iteration

Recommended Stage 7.1 work:

1. Generate TypeScript API types from FastAPI OpenAPI instead of maintaining `src/api/types.ts` by hand.
2. Add direct proposal routes (`/proposals/:id`) and deep-linkable operation routes.
3. Add richer Run Inspector span durations from Tempo through a backend trace-summary endpoint.
4. Add component/E2E tests with Vitest Browser Mode, MSW and Playwright.
5. Consider React Flow only after the linear tool timeline is proven useful.

## 7.0.2 — non-root nginx runtime fix

The first Stage 7 manifest combined the stock nginx image with `capabilities.drop: ["ALL"]`.
The stock nginx master process then attempted to `chown /var/cache/nginx/client_temp` and crashed.

Stage 7.0.2 keeps the hardened security posture instead of restoring `CHOWN`:

- nginx runs as UID/GID `101`,
- container entrypoint scripts are bypassed,
- nginx listens on unprivileged port `8080`,
- PID and all temp paths live under `/tmp`,
- `/tmp` is an `emptyDir`,
- root filesystem is read-only,
- all Linux capabilities remain dropped,
- the Pod does not mount a Kubernetes API token.
