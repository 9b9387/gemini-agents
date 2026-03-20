import asyncio
import os

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
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
    role = ROLE_TELEGRAM

    def __init__(self, gateway, auth_manager, token: str = TELEGRAM_TOKEN):
        self.gateway = gateway
        self.auth_manager = auth_manager
        self.token = token
        self.app = None
        self.sender_id = f"telegram_channel_{id(self)}"

    @classmethod
    def from_config(cls, gateway, auth_manager, config: dict):
        """Standard way to create TelegramChannel from configuration."""
        token = config.get("token") or os.environ.get("TELEGRAM_TOKEN")
        if not token:
            logger.warning("Telegram channel enabled but no token found.")
            return None
        return cls(gateway, auth_manager, token=token)

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

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        if self.auth_manager.is_authorized(self.role, chat_id):
            await update.message.reply_text("You are already authorized and ready to chat!")
        else:
            await update.message.reply_text(
                "Welcome! To use this agent, you must be authorized first.\n"
                "Please use /pair to generate an authorization code."
            )

    async def _pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        if self.auth_manager.is_authorized(self.role, chat_id):
            await update.message.reply_text("You are already authorized!")
            return

        code = self.auth_manager.request_pairing(self.role, chat_id)
        await update.message.reply_text(
            f"Your authorization code is: `{code}`\n\n"
            f"Please run the following command on the server to approve:\n\n"
            f"`owlet approve telegram {code}`",
            parse_mode="Markdown"
        )

    async def _handle_telegram_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        chat_id = str(update.effective_chat.id)
        if not self.auth_manager.is_authorized(self.role, chat_id):
            await update.message.reply_text("Access denied. Please use /pair to get authorized.")
            return

        text = update.message.text
        msg = Message(
            type=MSG_TYPE_REQ,
            method=METHOD_CHAT,
            role=ROLE_TELEGRAM,
            session_id=chat_id,
            sender_id=self.sender_id,
            content=text,
        )
        await self.gateway.handle_internal_message(msg)
        logger.debug(f"Forwarded Telegram message from {chat_id} to gateway.")

    async def start(self):
        if not self.token:
            logger.error("TELEGRAM_TOKEN not found.")
            return

        # Setup Telegram bot
        self.app = ApplicationBuilder().token(self.token).build()
        
        # Command handlers
        self.app.add_handler(CommandHandler("start", self._start_command))
        self.app.add_handler(CommandHandler("pair", self._pair_command))
        
        # Message handler for normal text
        self.app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_telegram_message))
        
        logger.info("Telegram bot starting inside Gateway (direct mode with dynamic pairing)...")
        await self.app.initialize()
        await self.app.start()
        if self.app.updater:
            await self.app.updater.start_polling()
            logger.info("Telegram polling started.")
        
        while True:
            await asyncio.sleep(1)
