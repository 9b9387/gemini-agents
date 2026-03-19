import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """
    Enhanced standard message protocol for communication between components.
    """

    # 1. Network & RPC Control Layer
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str  # 'event' (broadcast), 'req' (request), 'res' (response)
    method: Optional[str] = None  # e.g., 'register_node', 'chat'
    reply_to: Optional[str] = None  # ID of the original request for 'res' types

    # 2. Core Routing Layer
    session_id: str  # Context ID (e.g., "cli_session_123")
    sender_id: str  # Physical source (e.g., "cli_node_1", "agent_node_1")
    workspace: str = "default"  # Sandbox isolation

    # 3. Business Content Layer
    role: str  # 'user', 'agent', 'gateway'
    content: str = ""

    # 4. Extension & Memory Layer
    timestamp: float = Field(default_factory=time.time)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        return cls.model_validate_json(json_str)
