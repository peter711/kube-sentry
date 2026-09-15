"""Scripted fake of the OpenAI Responses API for the offline eval layer.

The offline layer drives the *real* agent loop (agent/app.py::run_agent) with a
deterministic, pre-recorded sequence of model turns. This validates the agent's
plumbing, tool dispatch, proposal creation and safety invariants without a
network call or an API key. It does not measure real model quality - that is the
job of the live eval layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptedCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScriptedStep:
    """One model turn: either a set of tool calls or a final text answer."""

    calls: list[ScriptedCall] = field(default_factory=list)
    text: str = ""


class _FunctionCall:
    type = "function_call"

    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class _Response:
    def __init__(self, response_id: str, items: list[Any], text: str) -> None:
        self.id = response_id
        self.output = items
        self.output_text = text
        self.usage = None


class _Responses:
    def __init__(self, steps: list[ScriptedStep]) -> None:
        self._steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Response:
        self.requests.append(kwargs)
        if not self._steps:
            raise AssertionError("FakeOpenAI ran out of scripted steps")
        step = self._steps.pop(0)
        items = [
            _FunctionCall(call_id=f"call_{index}", name=call.name, arguments=json.dumps(call.arguments))
            for index, call in enumerate(step.calls)
        ]
        return _Response(f"resp_{len(self.requests)}", items, step.text)


class FakeOpenAI:
    def __init__(self, steps: list[ScriptedStep]) -> None:
        self.responses = _Responses(steps)


def text_step(text: str) -> ScriptedStep:
    return ScriptedStep(text=text)


def calls_step(*calls: ScriptedCall) -> ScriptedStep:
    return ScriptedStep(calls=list(calls))


def call(name: str, **arguments: Any) -> ScriptedCall:
    return ScriptedCall(name=name, arguments=arguments)
