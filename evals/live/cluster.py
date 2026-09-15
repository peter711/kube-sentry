"""kubectl-backed seeding and reset for the live eval layer.

Live evals need real workloads in the disposable ``ai-lab`` namespace. This
helper applies the ``demo/`` manifests, waits for the failure signature the
agent is meant to diagnose, and resets the namespace between cases so runs are
independent.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "demo"

DEMO_WORKLOADS = ["broken-nginx", "crashy-app", "web"]


class LiveClusterError(RuntimeError):
    """Raised when a kubectl command fails or a wait times out."""


class LiveCluster:
    def __init__(self, namespace: str = "ai-lab", kubectl: str = "kubectl", context: str | None = None) -> None:
        self.namespace = namespace
        self.kubectl = kubectl
        self.context = context

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        command = [self.kubectl]
        if self.context:
            command += ["--context", self.context]
        command += args
        proc = subprocess.run(command, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise LiveClusterError(
                f"{' '.join(command)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc

    def available(self) -> bool:
        return self._run(["get", "namespace", self.namespace], check=False).returncode == 0

    def apply(self, manifest: Path | str) -> None:
        self._run(["apply", "-f", str(manifest)])

    def delete(self, kind: str, name: str) -> None:
        self._run(["delete", kind, name, "-n", self.namespace, "--ignore-not-found"])

    def delete_repair_jobs(self) -> None:
        self._run(["delete", "jobs", "-n", self.namespace, "-l", "app=ai-agent-worker", "--ignore-not-found"])

    def reset(self) -> None:
        for name in DEMO_WORKLOADS:
            self.delete("deployment", name)
        self.delete_repair_jobs()

    def deployment_exists(self, name: str) -> bool:
        return self._run(["get", "deployment", name, "-n", self.namespace], check=False).returncode == 0

    def deployment(self, name: str) -> dict[str, Any]:
        raw = self._run(["get", "deployment", name, "-n", self.namespace, "-o", "json"]).stdout
        dep = json.loads(raw)
        spec = dep.get("spec", {})
        status = dep.get("status", {})
        containers = spec.get("template", {}).get("spec", {}).get("containers", [])
        return {
            "name": dep["metadata"]["name"],
            "images": {container["name"]: container["image"] for container in containers},
            "replicas": spec.get("replicas", 0),
            "ready_replicas": status.get("readyReplicas", 0),
            "available_replicas": status.get("availableReplicas", 0),
            "generation": dep["metadata"].get("generation"),
            "observed_generation": status.get("observedGeneration"),
        }

    def pods(self) -> list[dict[str, Any]]:
        raw = self._run(["get", "pods", "-n", self.namespace, "-o", "json"]).stdout
        return json.loads(raw).get("items", [])

    def wait(self, description: str, predicate: Callable[[], Any], timeout: float = 60.0, poll: float = 2.0) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = predicate()
            except LiveClusterError:
                result = None
            if result:
                return result
            time.sleep(poll)
        raise LiveClusterError(f"timed out after {timeout}s waiting for {description}")

    def seed(self, name: str | None) -> None:
        if name in (None, "none"):
            return
        if name == "image_pull":
            self.apply(DEMO_DIR / "broken-nginx.yaml")
            self.wait(
                "broken-nginx ImagePullBackOff",
                lambda: self._pod_waiting_reason("broken-nginx", {"ImagePullBackOff", "ErrImagePull"}),
            )
            return
        if name == "crashloop":
            self.apply(DEMO_DIR / "crashy-app.yaml")
            self.wait("crashy-app container restart", lambda: self._container_restarts("crashy-app") >= 1, timeout=90.0)
            return
        if name == "healthy":
            self.apply(DEMO_DIR / "healthy-web.yaml")
            self.wait("web deployment ready", lambda: self._deployment_ready("web"), timeout=90.0)
            return
        raise ValueError(f"unknown seed: {name}")

    def _pods_for(self, deployment: str) -> list[dict[str, Any]]:
        prefix = deployment + "-"
        return [pod for pod in self.pods() if pod["metadata"]["name"].startswith(prefix)]

    def _pod_waiting_reason(self, deployment: str, reasons: set[str]) -> str | None:
        for pod in self._pods_for(deployment):
            for container in pod.get("status", {}).get("containerStatuses") or []:
                waiting = container.get("state", {}).get("waiting")
                if waiting and waiting.get("reason") in reasons:
                    return waiting["reason"]
        return None

    def _container_restarts(self, deployment: str) -> int:
        restarts = 0
        for pod in self._pods_for(deployment):
            for container in pod.get("status", {}).get("containerStatuses") or []:
                restarts = max(restarts, container.get("restartCount", 0))
        return restarts

    def _deployment_ready(self, deployment: str) -> bool:
        snapshot = self.deployment(deployment)
        desired = snapshot["replicas"] or 0
        return desired > 0 and snapshot["ready_replicas"] == desired
