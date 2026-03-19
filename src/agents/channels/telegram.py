import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from loguru import logger

from ..constants import (
    METHOD_CHAT,
    MSG_TYPE_REQ,
    ROLE_TELEGRAM,
    TELEGRAM_TOKEN,
)
from ..protocol import Message
from .base import BaseChannel

class TelegramChannel(BaseChannel):
    def __init__(self, gateway, token: str = TELEGRAM_TOKEN):
        self.gateway = gateway
        self.token = token
        self.app = None
        self.sender_id = f"telegram_channel_{id(self)}"

    async def send_to_user(self, session_id: str, content: str):
        if not self.app:
            logger.error("Telegram app not initialized.")
            return
            
        try:
            chat_id = int(session_id)
            await self.app.bot.send_message(chat_id=chat_id, text=content)
            logger.debug(f"Sent message back to Telegram chat_id: {chat_id}")
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to route message back to Telegram: invalid session_id {session_id} - {e}")

    async def _handle_telegram_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        chat_id = str(update.message.chat_id)
        text = update.message.text
        
        msg = Message(
            type=MSG_TYPE_REQ,
            method=METHOD_CHAT,
            role=ROLE_TELEGRAM,
            session_id=chat_id,
            sender_id=self.sender_id,
            content=text,
        )
        # Directly call gateway's internal handling
        await self.gateway.handle_internal_message(msg)
        logger.debug(f"Forwarded Telegram message from {chat_id} directly to gateway.")

    async def start(self):
        if not self.token:
            logger.error("TELEGRAM_TOKEN not found.")
            return

        # Setup Telegram bot
        self.app = ApplicationBuilder().token(self.token).build()
        self.app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_telegram_message))
        
        logger.info("Telegram bot starting inside Gateway (direct mode)...")
        await self.app.initialize()
        await self.app.start()
        if self.app.updater:
            await self.app.updater.start_polling()
            logger.info("Telegram polling started.")
        
        while True:
            await asyncio.sleep(1)
