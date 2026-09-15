"""Offline agent-loop evals, graded deterministically with DeepEval metrics."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, ToolCall

from fakes.fake_openai import call, calls_step
from fakes.scenarios import Scenario, build
from metrics.deterministic import (
    answer_non_empty_metric,
    evidence_metric,
    no_mutation_metric,
    proposal_state_metric,
    tool_args_metric,
    tool_set_metric,
)

DATASET = yaml.safe_load((Path(__file__).parent / "datasets" / "offline_agent.yaml").read_text())


def _test_case(result) -> LLMTestCase:
    return LLMTestCase(
        input=result.question,
        actual_output=result.answer,
        tools_called=[
            ToolCall(name=entry["tool"], input_parameters=entry["arguments"])
            for entry in result.tool_calls
        ],
    )


@pytest.mark.parametrize("case", DATASET, ids=[case["name"] for case in DATASET])
def test_offline_agent_case(offline, case):
    scenario = build(case["scenario"])
    result = offline.run(scenario)
    test_case = _test_case(result)

    metrics = [
        answer_non_empty_metric(),
        tool_set_metric(case.get("required_tools", []), case.get("forbidden_tools", [])),
        proposal_state_metric(
            result.proposals,
            expected_count=case.get("proposal_count"),
            actions=case.get("actions"),
            statuses=case.get("statuses"),
            payloads=case.get("payloads"),
        ),
    ]
    if case.get("required_patterns"):
        metrics.append(evidence_metric(case["required_patterns"], case.get("forbidden_patterns", [])))
    if case.get("expect_no_mutation", True):
        metrics.append(no_mutation_metric(offline.writes))

    assert_test(test_case, metrics)


def test_agent_passes_tools_and_replays_tool_outputs(offline):
    scenario = build("image_fix_proposal")
    result = offline.run(scenario)

    assert len(result.llm_requests) == len(scenario.steps)
    assert all("tools" in request for request in result.llm_requests)
    follow_up = result.llm_requests[1]
    assert follow_up.get("previous_response_id") == "resp_1"
    assert isinstance(follow_up["input"], list)
    assert follow_up["input"][0]["type"] == "function_call_output"


def test_tool_args_metric_detects_proposal_target(offline):
    scenario = build("image_fix_proposal")
    result = offline.run(scenario)
    metric = tool_args_metric({"propose_set_image": {"container_name": "nginx", "image": "nginx:1.25"}})
    metric.measure(_test_case(result))
    assert metric.is_successful(), metric.reason


def test_agent_enforces_max_tool_rounds(offline, monkeypatch):
    import app

    monkeypatch.setattr(app, "MAX_TOOL_ROUNDS", 2)
    scenario = Scenario(
        name="endless_tools",
        question="Loop forever",
        cluster=build("healthy_no_action").cluster,
        steps=[calls_step(call("get_pods")) for _ in range(3)],
    )
    with pytest.raises(RuntimeError, match="maximum tool-call rounds"):
        offline.run(scenario)


def test_proposal_ids_are_returned(offline):
    scenario = build("scale_proposal")
    result = offline.run(scenario)
    assert len(result.proposal_ids) == 1
    assert result.proposal_ids[0] == result.proposals[0]["id"]
