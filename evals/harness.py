"""Offline eval harness: drive the real agent loop with a scripted model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import app
from db import db_connection, row_to_proposal
from fakes.fake_k8s import FakeCluster
from fakes.fake_openai import FakeOpenAI
from fakes.scenarios import Scenario


@dataclass
class RunResult:
    question: str
    answer: str
    conversation_id: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    llm_requests: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [entry["tool"] for entry in self.tool_calls]


def fetch_proposals(conversation_id: str | None = None) -> list[dict[str, Any]]:
    with db_connection() as conn:
        if conversation_id is not None:
            rows = conn.execute(
                "SELECT * FROM repair_proposals WHERE conversation_id=? ORDER BY created_at, id",
                (conversation_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM repair_proposals ORDER BY created_at, id").fetchall()
    return [row_to_proposal(row) for row in rows]


def run_offline(scenario: Scenario, conversation_id: str = "conv_offline") -> RunResult:
    fake = FakeOpenAI(scenario.steps)
    answer, tool_calls, proposal_ids = app.run_agent(
        scenario.question,
        conversation_id,
        openai_client=fake,
    )
    return RunResult(
        question=scenario.question,
        answer=answer,
        conversation_id=conversation_id,
        tool_calls=tool_calls,
        proposal_ids=proposal_ids,
        proposals=fetch_proposals(conversation_id),
        llm_requests=fake.responses.requests,
    )


class OfflineSession:
    """Handle for the active offline cluster.

    The ``offline`` fixture points the patched Kubernetes clients at
    ``session.cluster``; tests select which scenario/cluster is live via
    :meth:`run` or :meth:`use`.
    """

    def __init__(self) -> None:
        self.cluster: FakeCluster | None = None

    def use(self, cluster: FakeCluster) -> FakeCluster:
        self.cluster = cluster
        return cluster

    def run(self, scenario: Scenario, conversation_id: str = "conv_offline") -> RunResult:
        self.cluster = scenario.cluster
        return run_offline(scenario, conversation_id)

    @property
    def writes(self) -> list[str]:
        return self.cluster.writes if self.cluster is not None else []
