"""Deterministic evals for the repair worker lifecycle (no LLM involved)."""

from __future__ import annotations

import json

import tools
import worker
from db import db_connection
from fakes.fake_k8s import FakeCluster, make_deployment


def _snapshot(**overrides):
    base = {
        "replicas": 3,
        "generation": 2,
        "observed_generation": 2,
        "current_replicas": 3,
        "updated_replicas": 3,
        "ready_replicas": 3,
        "available_replicas": 3,
        "unavailable_replicas": 0,
    }
    base.update(overrides)
    return base


def _set_status(proposal_id: str, status: str) -> None:
    with db_connection() as conn:
        conn.execute("UPDATE repair_proposals SET status=? WHERE id=?", (status, proposal_id))


def _insert_proposal(proposal_id, conversation_id, deployment, action, payload, before, status="queued"):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO repair_proposals(id,conversation_id,deployment_name,action,payload_json,rationale,source_resource_version,before_snapshot_json,status) VALUES (?,?,?,?,?,?,?,?,?)",
            (proposal_id, conversation_id, deployment, action, json.dumps(payload), "test", "1", json.dumps(before), status),
        )


def test_rollout_is_healthy_requires_all_counters():
    assert worker.rollout_is_healthy(_snapshot()) is True
    assert worker.rollout_is_healthy(_snapshot(unavailable_replicas=1)) is False
    assert worker.rollout_is_healthy(_snapshot(ready_replicas=2)) is False
    assert worker.rollout_is_healthy(_snapshot(observed_generation=1)) is False
    assert worker.rollout_is_healthy(_snapshot(current_replicas=2)) is False


def test_proposal_changes_state_detects_real_changes():
    assert worker.proposal_changes_state(
        {"action": "set_image", "payload": {"container_name": "app", "image": "nginx:1.25"}, "before": {"images": {"app": "nginx:1.24"}}}
    )
    assert not worker.proposal_changes_state(
        {"action": "set_image", "payload": {"container_name": "app", "image": "nginx:1.24"}, "before": {"images": {"app": "nginx:1.24"}}}
    )
    assert worker.proposal_changes_state(
        {"action": "scale", "payload": {"replicas": 3}, "before": {"replicas": 1}}
    )
    assert not worker.proposal_changes_state(
        {"action": "scale", "payload": {"replicas": 1}, "before": {"replicas": 1}}
    )


def test_execute_marks_stale_proposal(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", replicas=1, generation=1))

    proposal = tools.propose_scale_deployment("conv_stale", "web", 3, "scale up")
    _set_status(proposal["proposal_id"], "queued")
    cluster.deployments["web"].metadata.generation = 2

    assert worker.execute(proposal["proposal_id"]) == 0
    with db_connection() as conn:
        row = conn.execute("SELECT status FROM repair_proposals WHERE id=?", (proposal["proposal_id"],)).fetchone()
    assert row["status"] == "stale"
    assert cluster.writes == []


def test_execute_rejects_noop_proposal(offline):
    cluster = offline.use(FakeCluster())
    before = {"images": {"app": "nginx:1.25"}, "replicas": 1, "generation": 1}
    cluster.add_deployment(make_deployment("web", replicas=1, images={"app": "nginx:1.25"}))
    _insert_proposal("rp_noop", "conv_noop", "web", "scale", {"replicas": 1}, before)

    assert worker.execute("rp_noop") == 0
    with db_connection() as conn:
        row = conn.execute("SELECT status FROM repair_proposals WHERE id=?", ("rp_noop",)).fetchone()
    assert row["status"] == "rejected"
    assert cluster.writes == []


def test_execute_verifies_successful_rollout(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", replicas=1, generation=1))
    proposal = tools.propose_scale_deployment("conv_ok", "web", 3, "scale up")
    _set_status(proposal["proposal_id"], "queued")

    assert worker.execute(proposal["proposal_id"]) == 0
    with db_connection() as conn:
        row = conn.execute("SELECT status FROM repair_proposals WHERE id=?", (proposal["proposal_id"],)).fetchone()
    assert row["status"] == "verified"
    assert any(write.startswith("apps.patch_namespaced_deployment") for write in cluster.writes)


def test_execute_creates_rollback_on_failed_rollout(offline):
    cluster = offline.use(FakeCluster())
    cluster.healthy_after_patch = False
    cluster.add_deployment(make_deployment("web", replicas=1, generation=1))
    proposal = tools.propose_scale_deployment("conv_fail", "web", 3, "scale up")
    _set_status(proposal["proposal_id"], "queued")

    assert worker.execute(proposal["proposal_id"]) == 0

    with db_connection() as conn:
        rows = conn.execute("SELECT * FROM repair_proposals ORDER BY created_at, id").fetchall()
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[proposal["proposal_id"]] == "failed"

    rollbacks = [row for row in rows if row["rollback_of"] == proposal["proposal_id"]]
    assert len(rollbacks) == 1
    rollback = rollbacks[0]
    assert rollback["status"] == "pending"
    assert rollback["action"] == "scale"
    assert json.loads(rollback["payload_json"]) == {"replicas": 1}
