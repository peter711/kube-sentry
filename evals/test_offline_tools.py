"""Deterministic unit evals for the agent's Kubernetes tools (no LLM involved)."""

from __future__ import annotations

import config
import tools
from fakes.fake_k8s import FakeCluster, make_deployment, make_event, make_pod, make_service
from harness import fetch_proposals


def _multi_container_pod():
    return make_pod(
        "multi-0",
        containers=[
            {"name": "app", "state": "running", "ready": True},
            {"name": "sidecar", "state": "running", "ready": True},
        ],
    )


def test_get_pods_reports_container_health(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_pod(make_pod("web-0", containers=[{"name": "app", "state": "waiting", "reason": "ImagePullBackOff", "ready": False}]))

    result = tools.get_pods()

    assert result["namespace"] == config.NAMESPACE
    assert result["pods"][0]["containers"][0]["reason"] == "ImagePullBackOff"
    assert result["pods"][0]["containers"][0]["ready"] is False


def test_get_events_filters_and_sorts(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_event(make_event("Older", "old", object_name="web-0", last_timestamp="2024-01-01T00:00:00Z"))
    cluster.add_event(make_event("Newer", "new", object_name="web-0", last_timestamp="2024-01-02T00:00:00Z"))
    cluster.add_event(make_event("Other", "other", object_name="db-0", last_timestamp="2024-01-03T00:00:00Z"))

    result = tools.get_events("web-0", 10)

    assert [event["reason"] for event in result["events"]] == ["Newer", "Older"]


def test_get_pod_logs_redacts_secrets(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_pod(make_pod("web-0", containers=[{"name": "app", "state": "running"}]))
    cluster.add_logs("web-0", "app", "startup\npassword=super-secret\ntoken=abc.def.ghi\nBearer xyz.123\n")

    result = tools.get_pod_logs("web-0", "app", 100, False)

    assert "super-secret" not in result["logs"]
    assert "abc.def.ghi" not in result["logs"]
    assert "xyz.123" not in result["logs"]
    assert "[REDACTED]" in result["logs"]


def test_sanitize_log_text_truncates(offline):
    long_text = "x" * (config.MAX_LOG_CHARS + 500)
    redacted = tools.sanitize_log_text(long_text)
    assert redacted.startswith("[...log truncated...]")


def test_get_pod_logs_requires_container_for_multi_container_pod(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_pod(_multi_container_pod())

    result = tools.get_pod_logs("multi-0", None, 100, False)

    assert result["error"] == "container_name required"
    assert set(result["containers"]) == {"app", "sidecar"}


def test_propose_set_image_creates_pending_proposal(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", images={"app": "nginx:1.24"}))

    result = tools.propose_set_image("conv_tools", "web", "app", "nginx:1.25", "upgrade")

    assert result["status"] == "pending"
    proposals = fetch_proposals("conv_tools")
    assert len(proposals) == 1
    assert proposals[0]["action"] == "set_image"
    assert proposals[0]["payload"] == {"container_name": "app", "image": "nginx:1.25"}
    assert cluster.writes == []


def test_propose_set_image_rejects_noop(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", images={"app": "nginx:1.25"}))

    result = tools.propose_set_image("conv_noop", "web", "app", "nginx:1.25", "no change")

    assert "no-op" in result["error"]
    assert fetch_proposals("conv_noop") == []
    assert cluster.writes == []


def test_propose_set_image_rejects_unknown_container(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", images={"app": "nginx:1.25"}))

    result = tools.propose_set_image("conv_unknown", "web", "missing", "nginx:1.25", "typo")

    assert result["error"] == "container not found"
    assert fetch_proposals("conv_unknown") == []


def test_propose_set_image_rejects_invalid_reference(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", images={"app": "nginx:1.25"}))

    result = tools.propose_set_image("conv_invalid", "web", "app", "bad image ref", "typo")

    assert result["error"] == "invalid image reference"


def test_propose_scale_rejects_out_of_range(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", replicas=1))

    result = tools.propose_scale_deployment("conv_scale", "web", 42, "too many")

    assert result["error"] == "replicas must be between 0 and 10"
    assert fetch_proposals("conv_scale") == []


def test_propose_scale_rejects_noop(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web", replicas=3))

    result = tools.propose_scale_deployment("conv_scale_noop", "web", 3, "same")

    assert "no-op" in result["error"]
    assert fetch_proposals("conv_scale_noop") == []


def test_tools_are_scoped_to_target_namespace(offline):
    cluster = offline.use(FakeCluster())
    cluster.add_deployment(make_deployment("web"))
    cluster.add_pod(make_pod("web-0", containers=[{"name": "app", "state": "running"}]))
    cluster.add_service(make_service("web"))

    tools.get_pods()
    tools.get_deployments()
    tools.get_services()
    tools.get_events(None, 10)
    tools.propose_scale_deployment("conv_ns", "web", 2, "scale")

    assert cluster.namespace_calls
    assert set(cluster.namespace_calls) == {config.NAMESPACE}
