import asyncio
import json
import os

import websockets
from loguru import logger

from .constants import (
    GATEWAY_HOST,
    GATEWAY_PORT,
    METHOD_REGISTER,
    ROLE_AGENT,
    ROLE_CLI,
    ROLE_TELEGRAM,
    WORKDIR,
)
from .logging_config import setup_logging
from .protocol import Message
from .channels.telegram import TelegramChannel

class GatewayService:
    def __init__(self, host=GATEWAY_HOST, port=GATEWAY_PORT):
        self.host = host
        self.port = port
        self.clients = {}  # {role: set(websockets)}
        self.internal_channels = {}  # {role: channel_instance}
        self.config_path = WORKDIR / "gateway_config.json"
        
        # Default routing: Clients -> Agent, Agent -> All Clients
        # TODO Update Routing Rules.
        self.routing_rules = {
            ROLE_CLI: [ROLE_AGENT],
            ROLE_TELEGRAM: [ROLE_AGENT],
            ROLE_AGENT: [ROLE_CLI, ROLE_TELEGRAM]
        }

    def _expand_env_vars(self, data):
        """Recursively expand ${VAR} strings in a dictionary or list."""
        if isinstance(data, dict):
            return {k: self._expand_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._expand_env_vars(i) for i in data]
        elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
            env_var = data[2:-1]
            return os.environ.get(env_var, data)
        return data

    def _load_config(self) -> dict:
        config = {"channels": [{"type": "telegram", "enabled": True}]}
        if self.config_path.exists():
            try:
                config = json.loads(self.config_path.read_text())
                # Expand environment variables like ${TELEGRAM_TOKEN}
                config = self._expand_env_vars(config)
                
                if "routing_rules" in config:
                    self.routing_rules = config["routing_rules"]
                    logger.info(f"Loaded custom routing rules: {self.routing_rules}")
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        return config

    async def register(self, websocket, role: str):
        if role not in self.clients:
            self.clients[role] = set()
        self.clients[role].add(websocket)
        logger.info(f"Registered external client with role: {role}")

    async def unregister(self, websocket, role: str):
        for role_set in self.clients.values():
            if websocket in role_set:
                role_set.remove(websocket)
                logger.info("Unregistered an external client.")
                break

    async def handle_message(self, msg: Message):
        """Unified entry point for both internal and external messages."""
        # Find where this message should go based on the sender's role
        targets = self.routing_rules.get(msg.role, [])
        if not targets:
            logger.warning(f"No routing rules defined for role: {msg.role}")
            return

        for target_role in targets:
            await self.dispatch_to_role(msg, target_role)

    async def dispatch_to_role(self, msg: Message, target_role: str):
        """Dispatch a message to a specific role (internal or external)."""
        # 1. Check Internal Channels
        if target_role in self.internal_channels:
            channel = self.internal_channels[target_role]
            asyncio.create_task(channel.send_to_user(msg.session_id, msg.content))
            # Note: We continue even if found internal, because there might be 
            # external clients with the same role (e.g., multiple agents).

        # 2. Check External WebSocket Clients
        targets = self.clients.get(target_role, set())
        if not targets:
            return

        msg_json = msg.to_json()
        for ws in targets:
            try:
                await ws.send(msg_json)
            except Exception as e:
                logger.error(f"Failed to send to {target_role}: {e}")

    async def handle_client(self, websocket):
        """Handle external WebSocket connections."""
        role = None
        try:
            async for message_str in websocket:
                try:
                    msg = Message.from_json(message_str)
                except Exception as e:
                    logger.error(f"Parse error: {e}")
                    continue

                if msg.method == METHOD_REGISTER:
                    role = msg.role
                    await self.register(websocket, role)
                    continue

                # Use the unified routing logic
                await self.handle_message(msg)

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if role:
                await self.unregister(websocket, role)

    async def handle_internal_message(self, msg: Message):
        """Entry point for internal channels."""
        await self.handle_message(msg)

    async def start(self):
        # 1. Start Server
        await websockets.serve(self.handle_client, self.host, self.port)
        logger.info(f"Gateway server running on ws://{self.host}:{self.port}")

        # 2. Load Channels
        config = self._load_config()
        for ch_conf in config.get("channels", []):
            if not ch_conf.get("enabled"):
                continue
                
            ch_type = ch_conf.get("type")
            if ch_type == "telegram":
                token = ch_conf.get("token") or os.environ.get("TELEGRAM_TOKEN")
                if token:
                    channel = TelegramChannel(self, token=token)
                    self.internal_channels[ROLE_TELEGRAM] = channel
                    asyncio.create_task(channel.start())
                    logger.info("Started internal Telegram channel.")
                else:
                    logger.warning("Telegram token missing.")

        await asyncio.Future()

from dotenv import load_dotenv

def main():
    setup_logging()
    load_dotenv()
    gateway = GatewayService()
    try:
        asyncio.run(gateway.start())
    except KeyboardInterrupt:
        logger.info("Gateway stopped.")

if __name__ == "__main__":
    main()
