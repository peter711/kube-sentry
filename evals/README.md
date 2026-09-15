# Evals

Deterministic evaluations for the Kube Sentry agent.

The suite is split into two layers:

| Layer    | Needs cluster | Needs API key | Speed | Purpose |
|----------|:-------------:|:-------------:|-------|---------|
| offline  | no            | no            | ~1s   | agent loop, tools, proposal lifecycle, safety invariants |
| live     | yes (k3d)     | yes           | minutes | real model behaviour against a real cluster (planned) |

Only the **offline** layer is implemented today. It is the fast regression gate:
it drives the real agent loop (`agent/app.py::run_agent`), the real tool
dispatch (`agent/tools.py::execute_tool`) and the real worker
(`agent/worker.py`) against in-memory fakes, with a scripted model trajectory.
Grading is **deterministic only** - no LLM judge, no network, no cost.

## Run it

```bash
# one-time setup
python3 -m venv .venv
.venv/bin/pip install -r evals/requirements-evals.txt

# run all offline evals (also writes evals/reports/<timestamp>.{json,md})
./scripts/run-evals.sh

# filter / marker passthrough
./scripts/run-evals.sh -k proposal
./scripts/run-evals.sh -m "not live"

# raw pytest works too
.venv/bin/python -m pytest evals -m "not live"
```

## Layout

```text
evals/
  conftest.py                  # env, sys.path, temp DB, fake-client fixtures
  harness.py                   # RunResult + offline session (drives run_agent)
  run_evals.py                 # CLI runner + JSON/Markdown report
  datasets/
    offline_agent.yaml         # golden cases: scripted scenario + expectations
  metrics/
    deterministic.py           # DeepEval BaseMetric subclasses, 0/1 scoring
  fakes/
    fake_k8s.py                # in-memory Core/Apps/Batch APIs + write tracking
    fake_openai.py             # scripted Responses API replay
    scenarios.py               # named scenario -> seeded cluster + model script
  test_offline_agent.py        # agent-loop cases (DeepEval assert_test)
  test_offline_tools.py        # tool unit evals
  test_offline_worker.py       # repair lifecycle / rollout / rollback evals
  test_offline_safety.py       # no-direct-mutation + injection invariants
```

## How the offline layer works

1. A **scenario** (`fakes/scenarios.py`) seeds an in-memory cluster and a
   pre-recorded sequence of model turns.
2. `harness.run_offline` calls the real `run_agent` with `FakeOpenAI`, so tool
   calls flow through `execute_tool`, real proposal creation and real SQLite.
3. The resulting answer, tool trace and proposal rows are graded by
   `metrics/deterministic.py` through `deepeval.assert_test`.

The scripted model means the offline layer verifies **plumbing and
invariants**, not real model quality. Real model behaviour (does it actually
choose the right tool for a given question?) is what the live layer will
measure.

## Metrics (all deterministic)

| Metric | Asserts |
|--------|---------|
| `tool_set_metric` | required tools called, forbidden tools (supports `propose_*` prefix) not called |
| `tool_args_metric` | specific tool arguments (deployment, container, image, replicas) |
| `evidence_metric` | required/forbidden regexes in the final answer |
| `proposal_state_metric` | proposal count, action, status and payload in SQLite |
| `no_mutation_metric` | no Kubernetes write was attempted |
| `answer_non_empty_metric` | a non-empty final answer was produced |

## Adding a case

1. Add a scenario builder in `evals/fakes/scenarios.py` (cluster + scripted
   turns).
2. Add a case to `evals/datasets/offline_agent.yaml` referencing the scenario
   and the expected tools/patterns/proposals.
3. Run `./scripts/run-evals.sh`.

For tool or worker behaviour that does not need the agent loop, add a focused
test to `test_offline_tools.py` / `test_offline_worker.py` using the `offline`
fixture.

## Safety invariants covered

- the agent never calls a Kubernetes write API (only a pending proposal is
  created; approval creates a Job),
- prompt-injection text in logs/events is treated as untrusted data,
- the target namespace is always `ai-lab`; a model-supplied `namespace`
  argument is ignored,
- no-op and out-of-range proposals are rejected without a DB row,
- secrets in log content are redacted before reaching the model,
- a failed rollout only ever produces a **pending** rollback proposal.
