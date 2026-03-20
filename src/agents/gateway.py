import asyncio
import json
import os

import websockets
from loguru import logger
from dotenv import load_dotenv

from .constants import (
    GATEWAY_HOST,
    GATEWAY_PORT,
    ADMIN_API_PORT,
    METHOD_REGISTER,
    ROLE_AGENT,
    ROLE_CLI,
    ROLE_TELEGRAM,
    WORKDIR,
)
from .logging_config import setup_logging
from .protocol import Message
from .channels.manager import ChannelManager
from .auth import AuthManager
from .admin import AdminServer

class GatewayService:
    def __init__(self, host=GATEWAY_HOST, port=GATEWAY_PORT):
        self.host = host
        self.port = port
        self.clients = {}  # {role: set(websockets)}
        self.auth_manager = AuthManager()
        self.channel_manager = ChannelManager(self, self.auth_manager)
        self.admin_server = AdminServer(self.auth_manager, self.dispatch_to_role)
        self.config_path = WORKDIR / "gateway_config.json"
        
        # Default routing
        self.routing_rules = {
            ROLE_CLI: [ROLE_AGENT],
            ROLE_TELEGRAM: [ROLE_AGENT],
            ROLE_AGENT: [ROLE_CLI, ROLE_TELEGRAM]
        }

    def _expand_env_vars(self, data):
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
                config = self._expand_env_vars(config)
                if "routing_rules" in config:
                    self.routing_rules = config["routing_rules"]
            except Exception as e:
                logger.error(f"Gateway: Failed to load config: {e}")
        return config

    async def register(self, websocket, role: str):
        if role not in self.clients:
            self.clients[role] = set()
        self.clients[role].add(websocket)
        logger.info(f"Gateway: Registered external client: {role}")

    async def unregister(self, websocket, role: str):
        for role_set in self.clients.values():
            if websocket in role_set:
                role_set.remove(websocket)
                logger.info("Gateway: Unregistered external client.")
                break

    async def handle_message(self, msg: Message):
        targets = self.routing_rules.get(msg.role, [])
        for target_role in targets:
            await self.dispatch_to_role(msg, target_role)

    async def dispatch_to_role(self, msg: Message, target_role: str):
        channel = self.channel_manager.get_channel(target_role)
        if channel:
            asyncio.create_task(channel.send_to_user(msg.session_id, msg.content))

        targets = self.clients.get(target_role, set())
        if not targets:
            return

        msg_json = msg.to_json()
        for ws in targets:
            try:
                await ws.send(msg_json)
            except Exception as e:
                logger.error(f"Gateway: Failed to send to {target_role}: {e}")

    async def handle_client(self, websocket):
        role = None
        try:
            async for message_str in websocket:
                try:
                    msg = Message.from_json(message_str)
                except Exception as e:
                    logger.error(f"Gateway: Parse error: {e}")
                    continue

                if msg.method == METHOD_REGISTER:
                    role = msg.role
                    await self.register(websocket, role)
                    continue

                await self.handle_message(msg)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if role:
                await self.unregister(websocket, role)

    async def handle_internal_message(self, msg: Message):
        await self.handle_message(msg)

    async def start(self):
        # 1. Start WebSocket Gateway
        await websockets.serve(self.handle_client, self.host, self.port)
        logger.info(f"Gateway WS server: ws://{self.host}:{self.port}")

        # 2. Start Admin API (separate module)
        asyncio.create_task(self.admin_server.start())

        # 3. Load Channels
        config_data = self._load_config()
        await self.channel_manager.load_from_config(config_data)

        await asyncio.Future()

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
