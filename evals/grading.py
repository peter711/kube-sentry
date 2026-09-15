"""Shared grading helpers for offline and live eval results.

Both the offline harness ``RunResult`` and the live ``LiveRunResult`` expose
``question``, ``answer`` and ``tool_calls`` (entries with ``tool`` and
``arguments`` keys), so a single adapter feeds DeepEval's ``LLMTestCase``.
"""

from __future__ import annotations

from typing import Any, Protocol

from deepeval.test_case import LLMTestCase, ToolCall


class RunResultLike(Protocol):
    question: str
    answer: str
    tool_calls: list[dict[str, Any]]


def to_test_case(result: RunResultLike) -> LLMTestCase:
    return LLMTestCase(
        input=result.question,
        actual_output=result.answer,
        tools_called=[
            ToolCall(name=entry["tool"], input_parameters=entry.get("arguments") or {})
            for entry in result.tool_calls
        ],
    )
