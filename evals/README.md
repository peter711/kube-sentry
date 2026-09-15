# Evals

Deterministic evaluations for the Kube Sentry agent.

The suite is split into two layers:

| Layer    | Needs cluster | Needs API key | Speed   | Purpose |
|----------|:-------------:|:-------------:|---------|---------|
| offline  | no            | no            | ~1s     | agent loop, tools, proposal lifecycle, safety invariants |
| live     | yes (k3d)     | yes           | minutes | real model behaviour against a real cluster, full repair path |

Both layers grade with the **same deterministic metrics** - no LLM judge.

The **offline** layer is the fast regression gate: it drives the real agent loop
(`agent/app.py::run_agent`), the real tool dispatch
(`agent/tools.py::execute_tool`) and the real worker (`agent/worker.py`) against
in-memory fakes, with a scripted model trajectory. No cluster, no network, no
cost.

The **live** layer talks to the deployed agent over HTTP with a real model and
seeds real workloads into the disposable `ai-lab` namespace. It measures real
model quality and exercises the human-approved repair path end to end.

## Run it

```bash
# one-time setup
python3 -m venv .venv
.venv/bin/pip install -r evals/requirements-evals.txt

# offline (also writes evals/reports/<timestamp>.{json,md})
./scripts/run-evals.sh
./scripts/run-evals.sh -k proposal          # filter
./scripts/run-evals.sh -m "not live"        # marker expression

# live (cluster + deployed agent + OpenAI secret required)
./scripts/run-evals-live.sh
./scripts/run-evals-live.sh -k diagnosis    # read-only cases only
./scripts/run-evals-live.sh -m "live and live_repair"   # roundtrip only

# raw pytest works too
.venv/bin/python -m pytest evals -m "not live"
```

Live evals need the agent reachable at `EVAL_AGENT_URL` (default
`http://localhost:8080`) and `kubectl` access to `ai-lab`. The live script checks
both and exits early with a clear message if they are missing; the pytest
fixtures otherwise skip cleanly.

## Layout

```text
evals/
  conftest.py                  # env, sys.path, temp DB, fake + live fixtures
  harness.py                   # RunResult + offline session (drives run_agent)
  grading.py                   # RunResult/LiveRunResult -> DeepEval LLMTestCase
  run_evals.py                 # CLI runner + JSON/Markdown report
  datasets/
    offline_agent.yaml         # golden cases: scripted scenario + expectations
    live_agent.yaml            # golden cases: seed + real question + invariants
  metrics/
    deterministic.py           # DeepEval BaseMetric subclasses, 0/1 scoring
  fakes/
    fake_k8s.py                # in-memory Core/Apps/Batch APIs + write tracking
    fake_openai.py             # scripted Responses API replay
    scenarios.py               # named scenario -> seeded cluster + model script
  live/
    http_target.py             # stdlib HTTP client for the deployed agent
    cluster.py                 # kubectl seeding/reset for live cases
  test_offline_agent.py        # agent-loop cases (DeepEval assert_test)
  test_offline_tools.py        # tool unit evals
  test_offline_worker.py       # repair lifecycle / rollout / rollback evals
  test_offline_safety.py       # no-direct-mutation + injection invariants
  test_live_agent.py           # live cases + full repair roundtrip
```

## How the offline layer works

1. A **scenario** (`fakes/scenarios.py`) seeds an in-memory cluster and a
   pre-recorded sequence of model turns.
2. `harness.run_offline` calls the real `run_agent` with `FakeOpenAI`, so tool
   calls flow through `execute_tool`, real proposal creation and real SQLite.
3. The resulting answer, tool trace and proposal rows are graded by
   `metrics/deterministic.py` through `deepeval.assert_test`.

The scripted model means the offline layer verifies **plumbing and
invariants**, not real model quality. Real model behaviour is what the live
layer measures.

## How the live layer works

1. The `live_cluster` fixture resets the demo workloads (`broken-nginx`,
   `crashy-app`, `web`) and deletes stale repair Jobs.
2. Each case seeds one workload (`live/cluster.py::seed`) and waits for the
   failure signature: `ImagePullBackOff`, a container restart, or a healthy
   rollout. `demo/healthy-web.yaml` provides the healthy target.
3. `live_target.ask(...)` sends the real question to the deployed agent; the
   response's tool trace and any proposal ids are fetched back over HTTP.
4. Cases are graded with the same deterministic metrics as offline. The
   no-mutation check compares the workload's image/replicas before and after
   (`snapshot_unchanged_metric`).
5. `test_live_repair_roundtrip` additionally approves the proposal, waits for
   the worker Job to reach a terminal state, and asserts the deployment image
   changed, the rollout is healthy and the audit trail contains
   `proposal_queued` -> `proposal_applied` -> `verification_completed`.

Live evals **mutate the disposable `ai-lab` demo namespace** (the roundtrip
patches `broken-nginx`). Never point them at a shared cluster. The `live_repair`
marker isolates the mutating case: `-m "live and not live_repair"`.

## Metrics (all deterministic)

| Metric | Asserts |
|--------|---------|
| `tool_set_metric` | required tools called, forbidden tools (supports `propose_*` prefix) not called |
| `tool_any_metric` | at least one of several equivalent read tools was called (live) |
| `tool_args_metric` | specific tool arguments (deployment, container, image, replicas) |
| `evidence_metric` | required/forbidden regexes in the final answer |
| `proposal_state_metric` | proposal count, action, status and payload |
| `no_mutation_metric` | no Kubernetes write was attempted (offline) |
| `snapshot_unchanged_metric` | a live workload's image/replicas did not change |
| `answer_non_empty_metric` | a non-empty final answer was produced |

## Adding a case

**Offline:**

1. Add a scenario builder in `evals/fakes/scenarios.py` (cluster + scripted
   turns).
2. Add a case to `evals/datasets/offline_agent.yaml` referencing the scenario
   and the expected tools/patterns/proposals.
3. Run `./scripts/run-evals.sh`.

For tool or worker behaviour that does not need the agent loop, add a focused
test to `test_offline_tools.py` / `test_offline_worker.py` using the `offline`
fixture.

**Live:**

1. Add a case to `evals/datasets/live_agent.yaml`: pick a `seed`
   (`image_pull`, `crashloop`, `healthy`, `none`), a real `question`, the
   `target_deployment` for the no-mutation check, and the expected tools /
   proposals / evidence. Prefer `any_tools` over `required_tools` for evidence
   gathering, since a capable model may pick different read tools.
2. Run `./scripts/run-evals-live.sh -k <case name>`.

To add a new failure signature, extend `LiveCluster.seed` and add a manifest
under `demo/`.

## Safety invariants covered

- the agent never calls a Kubernetes write API (only a pending proposal is
  created; approval creates a Job),
- prompt-injection text in logs/events is treated as untrusted data,
- the target namespace is always `ai-lab`; a model-supplied `namespace`
  argument is ignored,
- no-op and out-of-range proposals are rejected without a DB row,
- secrets in log content are redacted before reaching the model,
- a failed rollout only ever produces a **pending** rollback proposal,
- live: a diagnosis/proposal request does not mutate the workload
  (`snapshot_unchanged_metric`), and the worker only changes it after an
  explicit human approval.

