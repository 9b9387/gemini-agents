import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

WORKDIR = Path.cwd()
MODEL_ID = os.environ.get("MODEL_ID", "models/gemini-2.5-flash-lite")

TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / ".tasks"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
LOGS_DIR = WORKDIR / "logs"

# Gateway Configuration
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", 8765))
GATEWAY_URI = f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}"

# Protocol Roles
ROLE_USER = "user"
ROLE_AGENT = "agent"
ROLE_GATEWAY = "gateway"
ROLE_CLI = "cli"
ROLE_TELEGRAM = "telegram"

# Message Types
MSG_TYPE_EVENT = "event"
MSG_TYPE_REQ = "req"
MSG_TYPE_RES = "res"

# Message Methods
METHOD_REGISTER = "register_node"
METHOD_CHAT = "chat"
METHOD_CHAT_RES = "chat_response"

TOKEN_THRESHOLD = 100000
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}
