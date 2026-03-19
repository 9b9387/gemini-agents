import json
import time
from .constants import INBOX_DIR

class MessageBus:
    def __init__(self):
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict = None,
    ) -> str:
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as file_obj:
            file_obj.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list[dict]:
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists():
            return []
        messages = [json.loads(line) for line in path.read_text().strip().splitlines() if line]
        path.write_text("")
        return messages

    def broadcast(self, sender: str, content: str, names: list[str]) -> str:
        count = 0
        for name in names:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"
