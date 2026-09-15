"""Shared pytest configuration and fixtures for the eval suite.

Import order matters here: environment variables are set and ``agent/`` is put
on ``sys.path`` *before* any agent module is imported, so that:

* ``config`` reads a writable temporary ``AGENT_DB_PATH`` (never ``/data``),
* ``observability`` disables OTLP export (no collector required),
* DeepEval telemetry is opted out for offline runs.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
os.environ.setdefault("TARGET_NAMESPACE", "ai-lab")
_TMP_DB_DIR = tempfile.mkdtemp(prefix="kube-sentry-evals-")
os.environ.setdefault("AGENT_DB_PATH", str(Path(_TMP_DB_DIR) / "agent.db"))

import pytest  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: requires a running cluster and a real model")
    config.addinivalue_line(
        "markers",
        "live_repair: live eval that approves a proposal and mutates the disposable ai-lab namespace",
    )


LIVE_AGENT_URL = os.getenv("EVAL_AGENT_URL", os.getenv("AGENT_URL", "http://localhost:8080"))


@pytest.fixture(scope="session")
def live_target():
    """HTTP client for the deployed agent; skips the live suite if unreachable."""
    from live.http_target import HttpTarget

    target = HttpTarget(LIVE_AGENT_URL)
    if not target.available():
        pytest.skip(f"live agent not reachable at {LIVE_AGENT_URL}")
    return target


@pytest.fixture
def live_cluster():
    """Real cluster access for seeding; resets demo workloads after each test."""
    from live.cluster import LiveCluster

    cluster = LiveCluster()
    if not cluster.available():
        pytest.skip("kubectl cannot reach the ai-lab namespace")
    yield cluster
    cluster.reset()


@pytest.fixture
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> "object":
    """Isolated offline environment: temp DB + fake Kubernetes API clients."""
    import config
    import db
    import tools
    import worker
    from fakes.fake_k8s import api_clients, worker_api_clients
    from harness import OfflineSession

    db_path = tmp_path / "agent.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(worker, "DB_PATH", str(db_path))
    db.init_db()

    session = OfflineSession()
    monkeypatch.setattr(tools, "api_clients", lambda: api_clients(session.cluster))
    monkeypatch.setattr(worker, "api_clients", lambda: worker_api_clients(session.cluster))
    monkeypatch.setattr(worker, "VERIFY_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(worker, "VERIFY_POLL_SECONDS", 0.01)
    return session
