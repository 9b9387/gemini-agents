from abc import ABC, abstractmethod

class BaseChannel(ABC):
    @abstractmethod
    async def start(self):
        """Start the channel's listener/polling loop."""
        pass

    @abstractmethod
    async def send_to_user(self, session_id: str, content: str):
        """Send a message back to the end-user (e.g., via Telegram)."""
        pass
