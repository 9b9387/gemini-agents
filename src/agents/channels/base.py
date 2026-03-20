from abc import ABC, abstractmethod

class BaseChannel(ABC):
    role: str = "base"

    @abstractmethod
    async def start(self):
        """Start the channel's listener/polling loop."""
        pass

    @abstractmethod
    async def send_to_user(self, session_id: str, content: str):
        """Send a message back to the end-user (e.g., via Telegram)."""
        pass

    @classmethod
    @abstractmethod
    def from_config(cls, gateway, auth_manager, config: dict):
        """Factory method to create a channel instance from a config dict."""
        pass
