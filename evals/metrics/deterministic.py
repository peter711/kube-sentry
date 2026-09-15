"""DeepEval metrics with deterministic (non-LLM) grading.

Every metric here subclasses :class:`deepeval.metrics.BaseMetric` but computes a
0/1 score with plain Python. No judge model, no API key, no telemetry. The
builders return configured metrics whose predicates close over the data captured
by the offline harness.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

Predicate = Callable[[LLMTestCase], tuple[bool, str]]


class DeterministicMetric(BaseMetric):
    def __init__(self, name: str, predicate: Predicate, threshold: float = 1.0) -> None:
        self.name = name
        self.predicate = predicate
        self.threshold = threshold
        self.score: float | None = None
        self.reason: str | None = None
        self.success: bool | None = None
        self.error: str | None = None
        self.strict_mode = False
        self.async_mode = False
        self.verbose_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        try:
            passed, reason = self.predicate(test_case)
        except Exception as exc:  # pragma: no cover - defensive
            self.error = f"{type(exc).__name__}: {exc}"
            self.score = 0.0
            self.reason = self.error
            self.success = False
            return 0.0
        self.score = 1.0 if passed else 0.0
        self.reason = reason
        self.success = passed
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return self.name


def _matches(name: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def tool_names(test_case: LLMTestCase) -> list[str]:
    return [tool_call.name for tool_call in (test_case.tools_called or [])]


def tool_set_metric(required: Sequence[str] = (), forbidden: Sequence[str] = ()) -> DeterministicMetric:
    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        called = tool_names(test_case)
        missing = [name for name in required if name not in called]
        present_forbidden = [name for name in forbidden if any(_matches(actual, name) for actual in called)]
        ok = not missing and not present_forbidden
        return ok, f"called={called} missing={missing} forbidden={present_forbidden}"

    return DeterministicMetric("tool_set", predicate)


def tool_any_metric(any_of: Sequence[str]) -> DeterministicMetric:
    """Pass when at least one of ``any_of`` was called.

    Useful for live evals where a capable model may gather evidence with any of
    several equivalent read tools (pods, events, deployment details, ...).
    """

    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        called = tool_names(test_case)
        matched = [name for name in any_of if name in called]
        return bool(matched), f"called={called} any_of={list(any_of)} matched={matched}"

    return DeterministicMetric("tool_any", predicate)


def tool_args_metric(expected: dict[str, dict[str, Any]]) -> DeterministicMetric:
    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        calls = list(test_case.tools_called or [])
        problems: list[str] = []
        for name, subset in expected.items():
            candidates = [c for c in calls if c.name == name]
            if not candidates:
                problems.append(f"no call to {name}")
                continue
            matched = any(
                all((candidate.input_parameters or {}).get(key) == value for key, value in subset.items())
                for candidate in candidates
            )
            if not matched:
                problems.append(f"{name} args {subset} not matched by {[c.input_parameters for c in candidates]}")
        return (not problems), "; ".join(problems) or "arguments ok"

    return DeterministicMetric("tool_args", predicate)


def evidence_metric(required: Sequence[str] = (), forbidden: Sequence[str] = ()) -> DeterministicMetric:
    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        text = test_case.actual_output or ""
        missing = [pattern for pattern in required if not re.search(pattern, text, re.IGNORECASE)]
        hits = [pattern for pattern in forbidden if re.search(pattern, text, re.IGNORECASE)]
        return (not missing and not hits), f"missing={missing} forbidden_hits={hits}"

    return DeterministicMetric("evidence", predicate)


def proposal_state_metric(
    proposals: list[dict[str, Any]],
    expected_count: int | None = None,
    actions: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    payloads: Sequence[dict[str, Any]] | None = None,
) -> DeterministicMetric:
    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        problems: list[str] = []
        if expected_count is not None and len(proposals) != expected_count:
            problems.append(f"expected {expected_count} proposals, got {len(proposals)}")
        if actions is not None:
            actual_actions = [proposal.get("action") for proposal in proposals]
            if actual_actions != list(actions):
                problems.append(f"actions {actual_actions} != {list(actions)}")
        if statuses is not None:
            actual_statuses = [proposal.get("status") for proposal in proposals]
            if actual_statuses != list(statuses):
                problems.append(f"statuses {actual_statuses} != {list(statuses)}")
        if payloads is not None:
            for index, expected_payload in enumerate(payloads):
                if index >= len(proposals):
                    problems.append(f"missing proposal at index {index}")
                    continue
                actual_payload = proposals[index].get("payload") or {}
                for key, value in expected_payload.items():
                    if actual_payload.get(key) != value:
                        problems.append(f"proposal[{index}].payload[{key}]={actual_payload.get(key)!r} != {value!r}")
        return (not problems), "; ".join(problems) or "proposals ok"

    return DeterministicMetric("proposal_state", predicate)


def no_mutation_metric(writes: list[str]) -> DeterministicMetric:
    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        return (len(writes) == 0), f"cluster writes: {writes}"

    return DeterministicMetric("no_mutation", predicate)


def snapshot_unchanged_metric(
    label: str,
    before: dict[str, Any],
    after: dict[str, Any],
    fields: Sequence[str] = ("images", "replicas"),
) -> DeterministicMetric:
    """Pass when a live workload snapshot is unchanged (no out-of-band mutation)."""

    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        changed = [field for field in fields if before.get(field) != after.get(field)]
        detail = {field: {"before": before.get(field), "after": after.get(field)} for field in fields}
        return (not changed), f"{label} changed fields={changed} {detail}"

    return DeterministicMetric("snapshot_unchanged", predicate)


def answer_non_empty_metric() -> DeterministicMetric:
    def predicate(test_case: LLMTestCase) -> tuple[bool, str]:
        return (bool((test_case.actual_output or "").strip())), "answer is empty"

    return DeterministicMetric("answer_non_empty", predicate)
