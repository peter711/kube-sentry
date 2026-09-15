import os

NAMESPACE = os.getenv("TARGET_NAMESPACE", "ai-lab")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
DB_PATH = os.getenv("AGENT_DB_PATH", "/data/agent.db")
WORKER_IMAGE = os.getenv("WORKER_IMAGE", "ai-agent:dev")
MAX_TOOL_ROUNDS = 8
MAX_LOG_CHARS = 12000
MEMORY_TURNS = 12
