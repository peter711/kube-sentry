"""Live agent evals: the deployed agent, a real model and a real k3d cluster.

Marked ``live`` (excluded from the default offline run) and graded with the same
deterministic metrics as the offline layer - no LLM judge. Requires:

* a reachable agent (``EVAL_AGENT_URL``, default ``http://localhost:8080``),
* ``kubectl`` access to the ``ai-lab`` namespace,
* the worker image and OpenAI secret already deployed (see ``scripts/deploy.sh``).

Each case resets the demo workloads, seeds one, runs a real question and grades
tool selection, proposal state, cluster mutation and coarse answer evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from deepeval import assert_test

from grading import to_test_case
from metrics.deterministic import (
    answer_non_empty_metric,
    evidence_metric,
    proposal_state_metric,
    snapshot_unchanged_metric,
    tool_any_metric,
    tool_set_metric,
)

pytestmark = pytest.mark.live

DATASET = yaml.safe_load((Path(__file__).parent / "datasets" / "live_agent.yaml").read_text())


def _before_snapshot(live_cluster, target_deployment):
    if target_deployment and live_cluster.deployment_exists(target_deployment):
        return live_cluster.deployment(target_deployment)
    return None


@pytest.mark.parametrize("case", DATASET, ids=[case["name"] for case in DATASET])
def test_live_agent_case(live_cluster, live_target, case):
    live_cluster.reset()
    live_cluster.seed(case.get("seed"))
    target = case.get("target_deployment")
    before = _before_snapshot(live_cluster, target)

    result = live_target.ask(case["question"])
    test_case = to_test_case(result)

    metrics = [answer_non_empty_metric()]
    if case.get("any_tools"):
        metrics.append(tool_any_metric(case["any_tools"]))
    metrics.append(tool_set_metric(case.get("required_tools", []), case.get("forbidden_tools", [])))
    metrics.append(
        proposal_state_metric(
            result.proposals,
            expected_count=case.get("proposal_count"),
            actions=case.get("actions"),
            statuses=case.get("statuses"),
            payloads=case.get("payloads"),
        )
    )
    if case.get("required_patterns"):
        metrics.append(evidence_metric(case["required_patterns"], case.get("forbidden_patterns", [])))
    if case.get("expect_no_mutation", True) and before is not None:
        after = live_cluster.deployment(target)
        metrics.append(snapshot_unchanged_metric(target, before, after))

    assert_test(test_case, metrics)


@pytest.mark.live
@pytest.mark.live_repair
def test_live_repair_roundtrip(live_cluster, live_target):
    """Full human-approved path: propose -> approve -> worker patches -> verified."""
    live_cluster.reset()
    live_cluster.seed("image_pull")
    before = live_cluster.deployment("broken-nginx")

    result = live_target.ask(
        "Diagnose broken-nginx and prepare a proposal to pin the nginx container "
        "to a known-good image. Do not apply anything."
    )
    assert result.proposal_ids, f"model created no proposal; tool_calls={result.tool_calls}"

    proposal_id = result.proposal_ids[0]
    proposal = live_target.get_proposal(proposal_id)
    assert proposal["action"] == "set_image", proposal
    assert proposal["status"] == "pending", proposal

    live_target.approve(proposal_id)
    final = live_target.wait_for_operation(proposal_id, timeout=180)
    assert final["status"] == "verified", final
    assert final["verification"]["status"] == "healthy", final["verification"]

    after = live_cluster.deployment("broken-nginx")
    assert after["images"]["nginx"] != before["images"]["nginx"], (before, after)
    assert after["ready_replicas"] == after["replicas"], after

    event_types = {event["event_type"] for event in live_target.audit()}
    assert {"proposal_created", "proposal_queued", "proposal_applied", "verification_completed"} <= event_types
