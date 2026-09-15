import json
import sqlite3
from pathlib import Path
from typing import Any

from config import DB_PATH, MEMORY_TURNS


def db_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    with db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_conversation ON conversation_turns(conversation_id, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repair_proposals (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                deployment_name TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                rationale TEXT NOT NULL,
                source_resource_version TEXT NOT NULL,
                before_snapshot_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_at TEXT,
                decision_reason TEXT,
                decided_by TEXT,
                result_json TEXT,
                verification_json TEXT,
                rollback_of TEXT,
                execution_job_name TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT,
                event_type TEXT NOT NULL,
                actor TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(repair_proposals)").fetchall()}
        if "execution_job_name" not in columns:
            conn.execute("ALTER TABLE repair_proposals ADD COLUMN execution_job_name TEXT")


def audit(event_type: str, proposal_id: str | None, actor: str | None, details: dict[str, Any] | None) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(proposal_id,event_type,actor,details_json) VALUES (?,?,?,?)",
            (proposal_id, event_type, actor, json.dumps(details or {}, ensure_ascii=False)),
        )


def save_turn(conversation_id: str, role: str, content: str) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO conversation_turns(conversation_id,role,content) VALUES (?,?,?)",
            (conversation_id, role, content),
        )


def get_recent_turns(conversation_id: str, limit: int = MEMORY_TURNS) -> list[dict[str, str]]:
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT role,content,created_at FROM conversation_turns WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def row_to_proposal(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id":row["id"], "conversation_id":row["conversation_id"], "deployment_name":row["deployment_name"], "action":row["action"],
        "payload":json.loads(row["payload_json"]), "rationale":row["rationale"], "source_resource_version":row["source_resource_version"],
        "before":json.loads(row["before_snapshot_json"]) if row["before_snapshot_json"] else None,
        "status":row["status"], "created_at":row["created_at"], "decided_at":row["decided_at"], "decision_reason":row["decision_reason"],
        "decided_by":row["decided_by"], "result":json.loads(row["result_json"]) if row["result_json"] else None,
        "verification":json.loads(row["verification_json"]) if row["verification_json"] else None,
        "rollback_of":row["rollback_of"], "execution_job_name":row["execution_job_name"],
    }
