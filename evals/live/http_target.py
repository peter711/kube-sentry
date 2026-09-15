"""HTTP client for the live (deployed) agent.

Talks to the FastAPI agent over HTTP using only the standard library, so the
live eval layer needs no extra dependencies. Mirrors the read / propose /
approve / reject / operation surface of ``agent/app.py``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

TERMINAL_STATUSES = frozenset({"verified", "failed", "rejected", "stale"})


class LiveAgentError(RuntimeError):
    """Raised when the live agent cannot be reached or returns an error."""


@dataclass
class LiveRunResult:
    question: str
    conversation_id: str
    answer: str
    namespace: str = ""
    model: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str | None = None

    @property
    def tool_names(self) -> list[str]:
        return [entry["tool"] for entry in self.tool_calls]


class HttpTarget:
    def __init__(self, base_url: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise LiveAgentError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LiveAgentError(f"{method} {path} failed: {exc.reason}") from exc
        return json.loads(body) if body else {}

    def available(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except LiveAgentError:
            return False

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def ask(self, question: str, conversation_id: str | None = None) -> LiveRunResult:
        conversation_id = conversation_id or "conv_eval_" + uuid.uuid4().hex[:12]
        payload = self._request("POST", "/ask", {"question": question, "conversation_id": conversation_id})
        proposal_ids = payload.get("proposal_ids") or []
        return LiveRunResult(
            question=question,
            conversation_id=payload.get("conversation_id", conversation_id),
            answer=payload.get("answer", ""),
            namespace=payload.get("namespace", ""),
            model=payload.get("model", ""),
            tool_calls=payload.get("tool_calls") or [],
            proposal_ids=proposal_ids,
            proposals=[self.get_proposal(proposal_id) for proposal_id in proposal_ids],
            trace_id=payload.get("trace_id"),
        )

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self._request("GET", f"/repair/proposals/{proposal_id}")

    def list_proposals(self) -> list[dict[str, Any]]:
        return self._request("GET", "/repair/proposals").get("proposals", [])

    def approve(self, proposal_id: str, approved_by: str = "eval-runner") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repair/proposals/{proposal_id}/approve",
            {"confirmation": "APPLY", "approved_by": approved_by},
        )

    def reject(self, proposal_id: str, reason: str = "rejected by eval runner", rejected_by: str = "eval-runner") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repair/proposals/{proposal_id}/reject",
            {"reason": reason, "rejected_by": rejected_by},
        )

    def operation(self, proposal_id: str) -> dict[str, Any]:
        return self._request("GET", f"/operations/{proposal_id}")

    def audit(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._request("GET", f"/audit?limit={limit}").get("events", [])

    def wait_for_operation(
        self,
        proposal_id: str,
        timeout: float = 180.0,
        poll: float = 2.0,
        terminal: frozenset[str] = TERMINAL_STATUSES,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.operation(proposal_id)
            if last.get("status") in terminal:
                return last
            time.sleep(poll)
        raise LiveAgentError(
            f"proposal {proposal_id} did not reach {sorted(terminal)} within {timeout}s "
            f"(last status={last.get('status')!r})"
        )
