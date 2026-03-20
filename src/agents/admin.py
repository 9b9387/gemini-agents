import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger

from .constants import ADMIN_API_PORT
from .protocol import Message

class AdminServer:
    def __init__(self, auth_manager, dispatch_callback):
        self.auth_manager = auth_manager
        self.dispatch_callback = dispatch_callback
        self.app = self._setup_app()

    def _setup_app(self):
        app = FastAPI()

        @app.post("/approve/{channel}/{code}")
        async def approve(channel: str, code: str):
            result = self.auth_manager.approve_pairing(code)
            if not result:
                raise HTTPException(status_code=404, detail="Invalid or expired code")
            
            target_channel, user_id = result
            
            # Notify the user via the channel callback
            msg = Message(
                type="res",
                role="gateway",
                session_id=user_id,
                sender_id="gateway_admin_api",
                content="Authorization successful! You can now use the agent."
            )
            
            # Use the provided callback to route the message
            await self.dispatch_callback(msg, target_channel)
            
            return {"status": "success", "channel": target_channel, "user_id": user_id}

        return app

    async def start(self):
        """Run the admin API server."""
        config = uvicorn.Config(
            self.app, 
            host="127.0.0.1", 
            port=ADMIN_API_PORT, 
            log_level="warning"
        )
        server = uvicorn.Server(config)
        logger.info(f"Admin API Server starting on http://127.0.0.1:{ADMIN_API_PORT}")
        await server.serve()
