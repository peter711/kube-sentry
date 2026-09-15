from typing import Any

from kubernetes import client, config


def load_kubernetes_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def api_clients() -> tuple[client.CoreV1Api, client.AppsV1Api, client.BatchV1Api]:
    load_kubernetes_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api()


def timestamp_of_event(event: Any) -> Any:
    return event.last_timestamp or event.event_time or event.first_timestamp or event.metadata.creation_timestamp


def deployment_snapshot(dep: Any) -> dict[str, Any]:
    return {
        "name": dep.metadata.name,
        "resource_version": dep.metadata.resource_version,
        "generation": dep.metadata.generation,
        "replicas": dep.spec.replicas,
        "images": {c.name: c.image for c in dep.spec.template.spec.containers},
        "current_replicas": dep.status.replicas or 0,
        "ready_replicas": dep.status.ready_replicas or 0,
        "available_replicas": dep.status.available_replicas or 0,
        "updated_replicas": dep.status.updated_replicas or 0,
        "unavailable_replicas": dep.status.unavailable_replicas or 0,
        "observed_generation": dep.status.observed_generation or 0,
        "conditions": [
            {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
            for c in (dep.status.conditions or [])
        ],
    }
