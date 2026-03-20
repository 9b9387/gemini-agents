import asyncio
from loguru import logger
from .telegram import TelegramChannel

# Registry of supported channel types
CHANNEL_MAP = {
    "telegram": TelegramChannel
}

class ChannelManager:
    def __init__(self, gateway, auth_manager):
        self.gateway = gateway
        self.auth_manager = auth_manager
        self.channels = {}  # {role: channel_instance}

    async def load_from_config(self, config: dict):
        """Instantiate and start channels based on the provided configuration."""
        for ch_conf in config.get("channels", []):
            if not ch_conf.get("enabled"):
                continue
                
            ch_type = ch_conf.get("type")
            ch_class = CHANNEL_MAP.get(ch_type)
            
            if not ch_class:
                logger.warning(f"ChannelManager: Unknown channel type: {ch_type}")
                continue

            # Utilize abstraction to create instance, passing auth_manager
            channel = ch_class.from_config(self.gateway, self.auth_manager, ch_conf)
            if channel:
                self.channels[channel.role] = channel
                asyncio.create_task(channel.start())
                logger.info(f"ChannelManager: Started {ch_type} channel.")

    def get_channel(self, role: str):
        return self.channels.get(role)

    def is_internal(self, role: str) -> bool:
        return role in self.channels
