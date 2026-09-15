"""Deterministic offline scenarios: fake cluster state + scripted model turns.

A scenario is the offline analogue of a live eval case: a seeded cluster plus a
pre-recorded "ideal" model trajectory. Each call to :func:`build` returns a
fresh cluster so cases never share state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fakes.fake_k8s import (
    FakeCluster,
    make_deployment,
    make_event,
    make_pod,
    make_service,
)
from fakes.fake_openai import ScriptedStep, call, calls_step, text_step


@dataclass
class Scenario:
    name: str
    question: str
    cluster: FakeCluster
    steps: list[ScriptedStep] = field(default_factory=list)


def _image_pull_cluster() -> FakeCluster:
    cluster = FakeCluster()
    cluster.add_deployment(
        make_deployment(
            "broken-nginx",
            images={"nginx": "nginx:does-not-exist"},
            status={"ready_replicas": 0, "available_replicas": 0, "updated_replicas": 0, "unavailable_replicas": 1},
        )
    )
    cluster.add_pod(
        make_pod(
            "broken-nginx-6d9f7c8b5d-abcde",
            phase="Pending",
            containers=[{"name": "nginx", "state": "waiting", "reason": "ImagePullBackOff", "ready": False}],
        )
    )
    cluster.add_event(
        make_event(
            "Failed",
            "Failed to pull image \"nginx:does-not-exist\": ErrImagePull: manifest unknown",
            object_name="broken-nginx-6d9f7c8b5d-abcde",
        )
    )
    cluster.add_service(make_service("broken-nginx"))
    return cluster


def _crashloop_cluster() -> FakeCluster:
    cluster = FakeCluster()
    cluster.add_deployment(make_deployment("crashy-app", images={"crashy-app": "crashy:1.0"}))
    cluster.add_pod(
        make_pod(
            "crashy-app-5f7b9c6d4e-xyz12",
            containers=[{"name": "crashy-app", "state": "running", "restart_count": 7, "ready": True}],
        )
    )
    cluster.add_event(
        make_event("BackOff", "Back-off restarting failed container crashy-app", object_name="crashy-app-5f7b9c6d4e-xyz12")
    )
    cluster.add_logs(
        "crashy-app-5f7b9c6d4e-xyz12",
        "crashy-app",
        "2024-01-01T00:00:00Z startup\n2024-01-01T00:00:01Z DATABASE_HOST=db.invalid\n2024-01-01T00:00:02Z dial tcp: lookup db.invalid: no such host\n",
        previous=True,
    )
    return cluster


def _healthy_cluster() -> FakeCluster:
    cluster = FakeCluster()
    cluster.add_deployment(make_deployment("web", images={"app": "nginx:1.25"}))
    cluster.add_pod(make_pod("web-7c8d9e0f1a-11111", containers=[{"name": "app", "state": "running", "ready": True}]))
    cluster.add_service(make_service("web"))
    return cluster


def build(name: str) -> Scenario:
    if name == "image_pull_diagnosis":
        return Scenario(
            name=name,
            question="Why is broken-nginx not working? Diagnose from the cluster.",
            cluster=_image_pull_cluster(),
            steps=[
                calls_step(call("get_pods")),
                calls_step(call("get_events", object_name="broken-nginx", limit=20)),
                text_step("broken-nginx is failing to start: the nginx container is in ImagePullBackOff because the image tag does not exist (ErrImagePull)."),
            ],
        )
    if name == "crashloop_diagnosis":
        return Scenario(
            name=name,
            question="Why is crashy-app restarting? Diagnose from the cluster.",
            cluster=_crashloop_cluster(),
            steps=[
                calls_step(call("get_pods")),
                calls_step(
                    call(
                        "get_pod_logs",
                        pod_name="crashy-app-5f7b9c6d4e-xyz12",
                        container_name="crashy-app",
                        tail_lines=100,
                        previous=True,
                    )
                ),
                text_step("crashy-app is in CrashLoopBackOff: the previous container logs show DATABASE_HOST=db.invalid, so the app cannot resolve its database host."),
            ],
        )
    if name == "healthy_no_action":
        return Scenario(
            name=name,
            question="Is the web deployment healthy? Do not change anything.",
            cluster=_healthy_cluster(),
            steps=[
                calls_step(call("get_deployments")),
                text_step("The web deployment is healthy: all replicas are ready and available."),
            ],
        )
    if name == "image_fix_proposal":
        return Scenario(
            name=name,
            question="Diagnose broken-nginx and prepare a safe image-fix proposal. Do not change anything yet.",
            cluster=_image_pull_cluster(),
            steps=[
                calls_step(call("get_pods")),
                calls_step(call("get_events", object_name="broken-nginx", limit=20)),
                calls_step(
                    call(
                        "propose_set_image",
                        deployment_name="broken-nginx",
                        container_name="nginx",
                        image="nginx:1.25",
                        rationale="The configured tag does not exist; pin to a known-good image.",
                    )
                ),
                text_step("I prepared a pending proposal to set nginx:1.25. Nothing has been changed; human approval is required."),
            ],
        )
    if name == "scale_proposal":
        return Scenario(
            name=name,
            question="Scale the web deployment to 3 replicas. Prepare a proposal only.",
            cluster=_healthy_cluster(),
            steps=[
                calls_step(call("get_deployments")),
                calls_step(
                    call(
                        "propose_scale_deployment",
                        deployment_name="web",
                        replicas=3,
                        rationale="User asked for three replicas.",
                    )
                ),
                text_step("I prepared a pending scale proposal to 3 replicas. Nothing has been changed yet."),
            ],
        )
    if name == "noop_image_proposal":
        return Scenario(
            name=name,
            question="Set the web image to nginx:1.25. Prepare a proposal only.",
            cluster=_healthy_cluster(),
            steps=[
                calls_step(
                    call(
                        "propose_set_image",
                        deployment_name="web",
                        container_name="app",
                        image="nginx:1.25",
                        rationale="Already requested image.",
                    )
                ),
                text_step("The deployment already runs nginx:1.25, so the no-op proposal was rejected. Nothing was changed."),
            ],
        )
    if name == "out_of_range_scale":
        return Scenario(
            name=name,
            question="Scale the web deployment to 42 replicas. Prepare a proposal only.",
            cluster=_healthy_cluster(),
            steps=[
                calls_step(
                    call(
                        "propose_scale_deployment",
                        deployment_name="web",
                        replicas=42,
                        rationale="User asked for many replicas.",
                    )
                ),
                text_step("Replicas must be between 0 and 10, so no proposal was created."),
            ],
        )
    raise KeyError(f"unknown scenario: {name}")


SCENARIO_NAMES = [
    "image_pull_diagnosis",
    "crashloop_diagnosis",
    "healthy_no_action",
    "image_fix_proposal",
    "scale_proposal",
    "noop_image_proposal",
    "out_of_range_scale",
]
