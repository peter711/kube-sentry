import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException


NAMESPACE = os.getenv("TARGET_NAMESPACE", "ai-lab")
DB_PATH = os.getenv("AGENT_DB_PATH", "/data/agent.db")
APPROVED_BY = os.getenv("APPROVED_BY", "local-user")
VERIFY_TIMEOUT_SECONDS = int(os.getenv("VERIFY_TIMEOUT_SECONDS", "30"))
VERIFY_POLL_SECONDS = float(os.getenv("VERIFY_POLL_SECONDS", "2"))


def db_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def audit(
    event_type: str,
    proposal_id: str,
    actor: str,
    details: dict[str, Any],
) -> None:
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_events(
                proposal_id, event_type, actor, details_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                proposal_id,
                event_type,
                actor,
                json.dumps(details, ensure_ascii=False),
            ),
        )


def load_kubernetes_config() -> None:
    config.load_incluster_config()


def api_clients() -> tuple[client.CoreV1Api, client.AppsV1Api]:
    load_kubernetes_config()
    return client.CoreV1Api(), client.AppsV1Api()


def deployment_snapshot(dep: Any) -> dict[str, Any]:
    return {
        "name": dep.metadata.name,
        "resource_version": dep.metadata.resource_version,
        "generation": dep.metadata.generation,
        "replicas": dep.spec.replicas,
        "images": {
            c.name: c.image
            for c in dep.spec.template.spec.containers
        },
        "current_replicas": dep.status.replicas or 0,
        "ready_replicas": dep.status.ready_replicas or 0,
        "available_replicas": dep.status.available_replicas or 0,
        "updated_replicas": dep.status.updated_replicas or 0,
        "unavailable_replicas": dep.status.unavailable_replicas or 0,
        "observed_generation": dep.status.observed_generation or 0,
        "conditions": [
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message,
            }
            for c in (dep.status.conditions or [])
        ],
    }


def row_to_proposal(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "deployment_name": row["deployment_name"],
        "action": row["action"],
        "payload": json.loads(row["payload_json"]),
        "before": (
            json.loads(row["before_snapshot_json"])
            if row["before_snapshot_json"]
            else None
        ),
        "status": row["status"],
        "rollback_of": row["rollback_of"],
    }


def proposal_changes_state(proposal: dict[str, Any]) -> bool:
    before = proposal.get("before") or {}
    payload = proposal["payload"]

    if proposal["action"] == "set_image":
        old_image = (before.get("images") or {}).get(
            payload["container_name"]
        )
        return old_image != payload["image"]

    if proposal["action"] == "scale":
        return before.get("replicas") != payload["replicas"]

    return True


def get_proposal(proposal_id: str) -> dict[str, Any]:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM repair_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError(f"proposal {proposal_id} not found")

    return row_to_proposal(row)


def deployment_related_pods(
    deployment_name: str,
) -> list[dict[str, Any]]:
    core, apps = api_clients()
    dep = apps.read_namespaced_deployment(
        deployment_name,
        NAMESPACE,
    )
    dep_uid = dep.metadata.uid

    replica_sets = apps.list_namespaced_replica_set(
        namespace=NAMESPACE
    ).items

    owned_rs_uids = set()

    for rs in replica_sets:
        owners = rs.metadata.owner_references or []
        if any(
            owner.kind == "Deployment"
            and owner.uid == dep_uid
            for owner in owners
        ):
            owned_rs_uids.add(rs.metadata.uid)

    related = []

    for pod in core.list_namespaced_pod(
        namespace=NAMESPACE
    ).items:
        owners = pod.metadata.owner_references or []

        if not any(
            owner.kind == "ReplicaSet"
            and owner.uid in owned_rs_uids
            for owner in owners
        ):
            continue

        related.append(
            {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "containers": [
                    {
                        "name": st.name,
                        "ready": st.ready,
                        "restarts": st.restart_count,
                        "waiting_reason": (
                            st.state.waiting.reason
                            if st.state.waiting
                            else None
                        ),
                        "terminated_reason": (
                            st.state.terminated.reason
                            if st.state.terminated
                            else None
                        ),
                    }
                    for st in (
                        pod.status.container_statuses or []
                    )
                ],
            }
        )

    return related


def wait_for_rollout(
    deployment_name: str,
) -> dict[str, Any]:
    _, apps = api_clients()
    deadline = time.time() + VERIFY_TIMEOUT_SECONDS
    last_snapshot = None

    while time.time() < deadline:
        dep = apps.read_namespaced_deployment(
            deployment_name,
            NAMESPACE,
        )
        snap = deployment_snapshot(dep)
        last_snapshot = snap

        desired = snap["replicas"] or 0

        healthy = (
            snap["observed_generation"] >= snap["generation"]
            and snap["current_replicas"] == desired
            and snap["updated_replicas"] == desired
            and snap["ready_replicas"] == desired
            and snap["available_replicas"] == desired
            and snap["unavailable_replicas"] == 0
        )

        if healthy:
            return {
                "status": "healthy",
                "reason": "Deployment rollout completed.",
                "snapshot": snap,
                "pods_observed": deployment_related_pods(
                    deployment_name
                ),
            }

        # Do not fail immediately on ProgressDeadlineExceeded.
        # A Deployment can carry a condition from an earlier failed rollout.
        # For this local lab we prefer the bounded verification timeout below,
        # which observes the rollout created by this worker execution.
        time.sleep(VERIFY_POLL_SECONDS)

    return {
        "status": "failed",
        "reason": (
            "Deployment did not complete its rollout within "
            f"{VERIFY_TIMEOUT_SECONDS}s."
        ),
        "snapshot": last_snapshot,
        "pods_observed": deployment_related_pods(
            deployment_name
        ),
    }


def create_rollback_proposal(
    failed: dict[str, Any],
) -> dict[str, Any] | None:
    before = failed.get("before") or {}

    if not proposal_changes_state(failed):
        audit(
            "rollback_skipped_no_state_change",
            failed["id"],
            "worker",
            {
                "action": failed["action"],
                "payload": failed["payload"],
                "before": before,
            },
        )
        return None

    if failed["action"] == "set_image":
        container_name = failed["payload"]["container_name"]
        old_image = (before.get("images") or {}).get(
            container_name
        )
        if not old_image:
            return None

        action = "set_image"
        payload = {
            "container_name": container_name,
            "image": old_image,
        }
        rationale = (
            f"Verification failed after {failed['id']}; "
            f"restore image {container_name}={old_image}."
        )

    elif failed["action"] == "scale":
        old_replicas = before.get("replicas")
        if old_replicas is None:
            return None

        action = "scale"
        payload = {"replicas": old_replicas}
        rationale = (
            f"Verification failed after {failed['id']}; "
            f"restore replicas={old_replicas}."
        )
    else:
        return None

    _, apps = api_clients()
    dep = apps.read_namespaced_deployment(
        failed["deployment_name"],
        NAMESPACE,
    )

    proposal_id = "rp_" + uuid.uuid4().hex[:12]
    before_now = deployment_snapshot(dep)

    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO repair_proposals(
                id, conversation_id, deployment_name,
                action, payload_json, rationale,
                source_resource_version, before_snapshot_json,
                status, rollback_of
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                proposal_id,
                failed["conversation_id"],
                failed["deployment_name"],
                action,
                json.dumps(payload, ensure_ascii=False),
                rationale,
                dep.metadata.resource_version,
                json.dumps(before_now, ensure_ascii=False),
                failed["id"],
            ),
        )

    audit(
        "proposal_created",
        proposal_id,
        "worker",
        {
            "rollback_of": failed["id"],
            "deployment": failed["deployment_name"],
            "action": action,
            "payload": payload,
            "before": before_now,
        },
    )

    return {
        "proposal_id": proposal_id,
        "status": "pending",
        "rollback_of": failed["id"],
        "action": action,
        "payload": payload,
    }


def mark_stale(
    proposal_id: str,
    expected_generation: int,
    actual_generation: int,
) -> None:
    with db_connection() as conn:
        conn.execute(
            """
            UPDATE repair_proposals
            SET status='stale',
                result_json=?
            WHERE id=?
            """,
            (
                json.dumps(
                    {
                        "expected_generation": expected_generation,
                        "actual_generation": actual_generation,
                    },
                    ensure_ascii=False,
                ),
                proposal_id,
            ),
        )

    audit(
        "proposal_stale",
        proposal_id,
        "worker",
        {
            "expected_generation": expected_generation,
            "actual_generation": actual_generation,
        },
    )


def execute(proposal_id: str) -> int:
    proposal = get_proposal(proposal_id)

    if proposal["status"] not in {"queued", "running"}:
        raise RuntimeError(
            f"proposal status is {proposal['status']}, expected queued"
        )

    if not proposal_changes_state(proposal):
        with db_connection() as conn:
            conn.execute(
                """
                UPDATE repair_proposals
                SET status='rejected',
                    result_json=?
                WHERE id=?
                """,
                (
                    json.dumps(
                        {
                            "reason": "no-op proposal",
                            "message": (
                                "The requested target state already matched the "
                                "captured before state."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    proposal_id,
                ),
            )

        audit(
            "noop_proposal_rejected",
            proposal_id,
            "worker",
            {
                "action": proposal["action"],
                "payload": proposal["payload"],
                "before": proposal["before"],
            },
        )
        return 0

    with db_connection() as conn:
        conn.execute(
            """
            UPDATE repair_proposals
            SET status='running'
            WHERE id=?
            """,
            (proposal_id,),
        )

    audit(
        "execution_started",
        proposal_id,
        "worker",
        {"approved_by": APPROVED_BY},
    )

    _, apps = api_clients()
    dep = apps.read_namespaced_deployment(
        proposal["deployment_name"],
        NAMESPACE,
    )

    expected_generation = (
        proposal["before"].get("generation")
        if proposal.get("before")
        else None
    )

    if (
        expected_generation is not None
        and dep.metadata.generation != expected_generation
    ):
        mark_stale(
            proposal_id,
            expected_generation,
            dep.metadata.generation,
        )
        # Staleness was handled correctly; the worker infrastructure succeeded.
        return 0

    payload = proposal["payload"]

    if proposal["action"] == "set_image":
        patch_body = {
            "metadata": {
                "annotations": {
                    "ai-lab.openai/approved-proposal": proposal_id,
                }
            },
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": payload["container_name"],
                                "image": payload["image"],
                            }
                        ]
                    }
                }
            },
        }

    elif proposal["action"] == "scale":
        patch_body = {
            "metadata": {
                "annotations": {
                    "ai-lab.openai/approved-proposal": proposal_id,
                }
            },
            "spec": {
                "replicas": payload["replicas"],
            },
        }
    else:
        raise RuntimeError(
            f"unsupported action {proposal['action']}"
        )

    patched = apps.patch_namespaced_deployment(
        proposal["deployment_name"],
        NAMESPACE,
        patch_body,
    )

    after_apply = deployment_snapshot(patched)

    with db_connection() as conn:
        conn.execute(
            """
            UPDATE repair_proposals
            SET result_json=?
            WHERE id=?
            """,
            (
                json.dumps(
                    {"after_apply": after_apply},
                    ensure_ascii=False,
                ),
                proposal_id,
            ),
        )

    audit(
        "proposal_applied",
        proposal_id,
        APPROVED_BY,
        {
            "before": proposal["before"],
            "after_apply": after_apply,
            "action": proposal["action"],
            "payload": payload,
        },
    )

    verification = wait_for_rollout(
        proposal["deployment_name"]
    )

    final_status = (
        "verified"
        if verification["status"] == "healthy"
        else "failed"
    )

    with db_connection() as conn:
        conn.execute(
            """
            UPDATE repair_proposals
            SET status=?,
                verification_json=?
            WHERE id=?
            """,
            (
                final_status,
                json.dumps(
                    verification,
                    ensure_ascii=False,
                ),
                proposal_id,
            ),
        )

    audit(
        "verification_completed",
        proposal_id,
        "worker",
        verification,
    )

    if final_status == "failed":
        failed = get_proposal(proposal_id)
        rollback = create_rollback_proposal(failed)

        audit(
            "rollback_proposal_generated",
            proposal_id,
            "worker",
            {"rollback_proposal": rollback},
        )

        # The attempted repair failed verification, but the workflow completed
        # correctly and created a human-approved rollback proposal. The Kubernetes
        # Job should therefore be Succeeded, not retried as an infrastructure error.
        return 0

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python worker.py PROPOSAL_ID")
        raise SystemExit(64)

    proposal_id = sys.argv[1]

    try:
        code = execute(proposal_id)
    except Exception as exc:
        with db_connection() as conn:
            conn.execute(
                """
                UPDATE repair_proposals
                SET status='failed',
                    result_json=?
                WHERE id=?
                """,
                (
                    json.dumps(
                        {
                            "worker_exception": (
                                f"{type(exc).__name__}: {exc}"
                            )
                        },
                        ensure_ascii=False,
                    ),
                    proposal_id,
                ),
            )

        audit(
            "worker_failed",
            proposal_id,
            "worker",
            {
                "error": f"{type(exc).__name__}: {exc}"
            },
        )
        raise

    raise SystemExit(code)
