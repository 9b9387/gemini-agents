import json
import random
import time
from pathlib import Path
from loguru import logger
from .constants import OWLET_DIR

class AuthManager:
    def __init__(self):
        OWLET_DIR.mkdir(parents=True, exist_ok=True)
        self.whitelist_file = OWLET_DIR / "allowed_users.json"
        self.allowed_users = self._load_whitelist()
        self.pending_pairs = {}  # {code: (channel, user_id, timestamp)}

    def _load_whitelist(self) -> dict:
        """Load allowed users from disk: {channel: [user_ids]}"""
        if self.whitelist_file.exists():
            try:
                return json.loads(self.whitelist_file.read_text())
            except Exception as e:
                logger.error(f"AuthManager: Failed to load whitelist: {e}")
        return {}

    def _save_whitelist(self):
        """Save the allowed users to disk."""
        try:
            self.whitelist_file.write_text(json.dumps(self.allowed_users, indent=2))
        except Exception as e:
            logger.error(f"AuthManager: Failed to save whitelist: {e}")

    def is_authorized(self, channel: str, user_id: str) -> bool:
        """Check if a user is authorized for a specific channel."""
        return user_id in self.allowed_users.get(channel, [])

    def request_pairing(self, channel: str, user_id: str) -> str:
        """Generate a random 6-digit code and store it for 10 minutes."""
        now = time.time()
        # Clean up expired codes
        self.pending_pairs = {k: v for k, v in self.pending_pairs.items() if now - v[2] < 600}
        
        # Generate unique 6-digit code
        while True:
            code = f"{random.randint(100000, 999999)}"
            if code not in self.pending_pairs:
                break
        
        self.pending_pairs[code] = (channel, user_id, now)
        logger.info(f"AuthManager: Generated pairing code {code} for {channel}:{user_id}")
        return code

    def approve_pairing(self, code: str) -> tuple[str, str] | None:
        """Verify code and add user to whitelist."""
        if code not in self.pending_pairs:
            return None
            
        channel, user_id, timestamp = self.pending_pairs.pop(code)
        
        if channel not in self.allowed_users:
            self.allowed_users[channel] = []
            
        if user_id not in self.allowed_users[channel]:
            self.allowed_users[channel].append(user_id)
            self._save_whitelist()
            
        logger.info(f"AuthManager: Approved pairing for {channel}:{user_id} via code {code}")
        return channel, user_id
