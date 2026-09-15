"""In-memory Kubernetes API fakes for the offline eval layer.

These fakes implement only the surface the agent actually uses. They never talk
to a cluster and they record every write attempt so tests can assert that the
read-only agent identity never mutates anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from kubernetes.client import ApiException


def _ns(**kwargs: Any) -> Any:
    return SimpleNamespace(**kwargs)


def make_pod(
    name: str,
    phase: str = "Running",
    node: str = "k3d-ai-lab-agent-0",
    pod_ip: str = "10.42.0.10",
    containers: list[dict[str, Any]] | None = None,
) -> Any:
    containers = containers or []
    statuses = []
    for container in containers:
        state = _ns(running=None, waiting=None, terminated=None)
        kind = container.get("state", "running")
        if kind == "waiting":
            state.waiting = _ns(reason=container.get("reason"))
        elif kind == "terminated":
            state.terminated = _ns(reason=container.get("reason"))
        else:
            state.running = _ns()
        statuses.append(
            _ns(
                name=container["name"],
                ready=container.get("ready", kind == "running"),
                restart_count=container.get("restart_count", 0),
                state=state,
            )
        )
    spec_containers = [
        _ns(
            name=container["name"],
            image=container.get("image", "nginx:latest"),
            command=container.get("command"),
            args=container.get("args"),
            readiness_probe=container.get("readiness_probe"),
            liveness_probe=container.get("liveness_probe"),
        )
        for container in containers
    ]
    return _ns(
        metadata=_ns(name=name, uid=f"uid-pod-{name}"),
        status=_ns(phase=phase, pod_ip=pod_ip, container_statuses=statuses),
        spec=_ns(node_name=node, service_account_name="default", containers=spec_containers),
    )


def make_deployment(
    name: str,
    replicas: int = 1,
    generation: int = 1,
    resource_version: str = "1",
    images: dict[str, str] | None = None,
    status: dict[str, Any] | None = None,
    conditions: list[dict[str, Any]] | None = None,
) -> Any:
    images = images or {"app": "nginx:1.25"}
    status = status or {}
    containers = [_ns(name=container, image=image) for container, image in images.items()]
    return _ns(
        metadata=_ns(
            name=name,
            uid=f"uid-deploy-{name}",
            generation=generation,
            resource_version=resource_version,
        ),
        spec=_ns(replicas=replicas, template=_ns(spec=_ns(containers=containers))),
        status=_ns(
            replicas=status.get("replicas", replicas),
            ready_replicas=status.get("ready_replicas", replicas),
            available_replicas=status.get("available_replicas", replicas),
            updated_replicas=status.get("updated_replicas", replicas),
            unavailable_replicas=status.get("unavailable_replicas", 0),
            observed_generation=status.get("observed_generation", generation),
            conditions=[
                _ns(type=c["type"], status=c["status"], reason=c.get("reason"), message=c.get("message"))
                for c in (conditions or [])
            ],
        ),
    )


def make_event(
    reason: str,
    message: str,
    object_name: str,
    object_kind: str = "Pod",
    type: str = "Warning",
    last_timestamp: str | None = None,
) -> Any:
    timestamp = last_timestamp or "2024-01-01T00:00:00Z"
    return _ns(
        type=type,
        reason=reason,
        involved_object=_ns(kind=object_kind, name=object_name),
        message=message,
        last_timestamp=timestamp,
        event_time=None,
        first_timestamp=None,
        metadata=_ns(creation_timestamp=timestamp),
    )


def make_service(name: str, type: str = "ClusterIP", cluster_ip: str = "10.43.0.1", ports: list[dict[str, Any]] | None = None) -> Any:
    ports = ports or [{"name": "http", "port": 80, "target_port": 8080, "protocol": "TCP"}]
    return _ns(
        metadata=_ns(name=name),
        spec=_ns(
            type=type,
            cluster_ip=cluster_ip,
            ports=[
                _ns(name=p["name"], port=p["port"], target_port=p.get("target_port"), protocol=p.get("protocol", "TCP"))
                for p in ports
            ],
        ),
    )


@dataclass
class FakeCluster:
    pods: dict[str, Any] = field(default_factory=dict)
    deployments: dict[str, Any] = field(default_factory=dict)
    services: dict[str, Any] = field(default_factory=dict)
    events: list[Any] = field(default_factory=list)
    logs: dict[tuple[str, str, bool], str] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)
    namespace_calls: list[str] = field(default_factory=list)
    healthy_after_patch: bool = True

    def add_pod(self, pod: Any) -> Any:
        self.pods[pod.metadata.name] = pod
        return pod

    def add_deployment(self, deployment: Any) -> Any:
        self.deployments[deployment.metadata.name] = deployment
        return deployment

    def add_service(self, service: Any) -> Any:
        self.services[service.metadata.name] = service
        return service

    def add_event(self, event: Any) -> Any:
        self.events.append(event)
        return event

    def add_logs(self, pod_name: str, container: str, text: str, previous: bool = False) -> None:
        self.logs[(pod_name, container, previous)] = text


class _FakeCoreV1Api:
    def __init__(self, cluster: FakeCluster) -> None:
        self._c = cluster

    def list_namespaced_pod(self, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        return _ns(items=list(self._c.pods.values()))

    def read_namespaced_pod(self, name: str, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        if name not in self._c.pods:
            raise ApiException(status=404, reason="Not Found")
        return self._c.pods[name]

    def list_namespaced_service(self, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        return _ns(items=list(self._c.services.values()))

    def list_namespaced_event(self, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        return _ns(items=list(self._c.events))

    def read_namespaced_pod_log(
        self,
        name: str,
        namespace: str,
        container: str | None = None,
        tail_lines: int | None = None,
        previous: bool = False,
        timestamps: bool = False,
    ) -> str:
        self._c.namespace_calls.append(namespace)
        key = (name, container, previous)
        if key not in self._c.logs:
            raise ApiException(status=400, reason="Bad Request")
        return self._c.logs[key]


class _FakeAppsV1Api:
    def __init__(self, cluster: FakeCluster) -> None:
        self._c = cluster

    def list_namespaced_deployment(self, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        return _ns(items=list(self._c.deployments.values()))

    def read_namespaced_deployment(self, name: str, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        if name not in self._c.deployments:
            raise ApiException(status=404, reason="Not Found")
        return self._c.deployments[name]

    def list_namespaced_replica_set(self, namespace: str) -> Any:
        self._c.namespace_calls.append(namespace)
        return _ns(items=[])

    def patch_namespaced_deployment(self, name: str, namespace: str, body: dict[str, Any]) -> Any:
        self._c.namespace_calls.append(namespace)
        self._c.writes.append(f"apps.patch_namespaced_deployment:{name}")
        deployment = self._c.deployments[name]
        if "replicas" in body.get("spec", {}):
            deployment.spec.replicas = body["spec"]["replicas"]
        for container in body.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []) or []:
            for existing in deployment.spec.template.spec.containers:
                if existing.name == container["name"]:
                    existing.image = container["image"]
        deployment.metadata.generation += 1
        deployment.metadata.resource_version = str(int(deployment.metadata.resource_version) + 1)
        if self._c.healthy_after_patch:
            desired = deployment.spec.replicas or 0
            deployment.status.replicas = desired
            deployment.status.ready_replicas = desired
            deployment.status.available_replicas = desired
            deployment.status.updated_replicas = desired
            deployment.status.unavailable_replicas = 0
            deployment.status.observed_generation = deployment.metadata.generation
        return deployment


class _FakeBatchV1Api:
    def __init__(self, cluster: FakeCluster) -> None:
        self._c = cluster

    def create_namespaced_job(self, namespace: str, body: Any) -> Any:
        self._c.namespace_calls.append(namespace)
        self._c.writes.append(f"batch.create_namespaced_job:{body.metadata.name}")
        return body


def api_clients(cluster: FakeCluster) -> tuple[_FakeCoreV1Api, _FakeAppsV1Api, _FakeBatchV1Api]:
    """Three-tuple matching agent/k8s.py::api_clients."""
    return _FakeCoreV1Api(cluster), _FakeAppsV1Api(cluster), _FakeBatchV1Api(cluster)


def worker_api_clients(cluster: FakeCluster) -> tuple[_FakeCoreV1Api, _FakeAppsV1Api]:
    """Two-tuple matching the tuple unpacking inside agent/worker.py."""
    return _FakeCoreV1Api(cluster), _FakeAppsV1Api(cluster)
