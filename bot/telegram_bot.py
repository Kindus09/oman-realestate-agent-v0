# bot/telegram_bot.py
#
# Telegram bot interface for the Oman Real Estate Agent.
#
# Run with:
#   python -m bot.telegram_bot
#
# Prerequisites:
#   1. Scrape + clean data:  python -m scraper.runner && python -m scraper.data_cleaner
#   2. Set .env:  ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN
#
# Architecture:
#   This file is purely a transport layer. It receives Telegram messages,
#   passes them to run_agent_turn() from agent/main.py, and sends the reply
#   back to the user. No agent logic lives here.
#
# How python-telegram-bot v20 works:
#   - It is fully async (built on asyncio).
#   - Handlers are async functions that receive an Update and a Context.
#   - Application.run_polling() starts the event loop and polls Telegram for
#     new messages every few seconds.
#   - Because the Anthropic SDK is synchronous, we run run_agent_turn() in a
#     thread pool via asyncio.to_thread() so it doesn't block the event loop.
#
# Per-user conversation history:
#   Stored in USER_HISTORIES dict keyed by Telegram user_id.
#   History persists for the lifetime of the bot process (in-memory only).
#   Each user gets their own independent conversation thread.

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import anthropic
from agent.main import run_agent_turn
from agent.tools import load_listings
from config.settings import (
    ANTHROPIC_API_KEY,
    CLEAN_DATA_FILE,
    CLAUDE_MODEL,
)

# ─── Setup ────────────────────────────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("telegram_bot")

# Silence noisy telegram library loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ─── Global state ─────────────────────────────────────────────────────────────

# One Anthropic client shared across all users.
_anthropic_client: anthropic.Anthropic | None = None

# Per-user conversation history.
# Key: Telegram user_id (int)
# Value: list of message dicts in Claude's format [{"role": ..., "content": ...}]
USER_HISTORIES: dict[int, list[dict]] = {}

# Telegram message length limit
TELEGRAM_MAX_LENGTH = 4096

# ─── Command handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — welcome message.
    Also clears any existing conversation history for this user so they
    get a fresh session.
    """
    user_id = update.effective_user.id
    USER_HISTORIES[user_id] = []   # fresh session

    name = update.effective_user.first_name or "there"
    welcome = (
        f"Hi {name}! I'm the Oman Real Estate Agent.\n\n"
        "I have data on 600+ property listings across Muscat from sites like "
        "OpenSooq, Dubizzle, Tibiaan, and more.\n\n"
        "Ask me anything about the Muscat property market:\n"
        "• Finding apartments or villas for rent or sale\n"
        "• Price ranges in specific areas\n"
        "• Comparing neighbourhoods\n"
        "• Statistics and market overview\n\n"
        "Try: \"What are the cheapest 2-bedroom apartments for rent?\"\n\n"
        "Type /help to see all the things I can do."
    )
    await update.message.reply_text(welcome)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — list what the agent can do.
    """
    help_text = (
        "Here's what you can ask me:\n\n"
        "*Search listings*\n"
        "• Find properties by area, price, bedrooms, type\n"
        "• Example: \"3-bedroom villa for rent in Al Khuwair\"\n"
        "• Example: \"Apartments for sale under 80,000 OMR\"\n\n"
        "*Price information*\n"
        "• Average, min, max prices for any area\n"
        "• Example: \"What is the average rent in Bausher?\"\n"
        "• Example: \"Price range for studios in Muscat\"\n\n"
        "*Area comparison*\n"
        "• Compare prices between areas or sources\n"
        "• Example: \"Compare Al Khuwair and Qurm\"\n\n"
        "*Market overview*\n"
        "• Which areas have the most listings\n"
        "• Overall price ranges by bedroom count\n\n"
        "*Commands*\n"
        "/start — start a new session\n"
        "/help — show this message\n"
        "/clear — clear your conversation history\n\n"
        "_Data covers Muscat listings scraped from OpenSooq, Dubizzle, "
        "Tibiaan, Savills, Vista Oman, and Omanreal. "
        "Always verify details directly with the listing site._"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /clear — wipe conversation history for this user.
    """
    user_id = update.effective_user.id
    USER_HISTORIES[user_id] = []
    await update.message.reply_text(
        "Conversation cleared. Ask me anything about Muscat real estate!"
    )


# ─── Message handler ──────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main handler for all non-command text messages.
    Passes the message to the Claude agent and sends the reply back.
    """
    user_id   = update.effective_user.id
    user_text = update.message.text.strip()

    if not user_text:
        return

    # Initialise history for new users.
    if user_id not in USER_HISTORIES:
        USER_HISTORIES[user_id] = []

    messages = USER_HISTORIES[user_id]
    messages.append({"role": "user", "content": user_text})

    # Show "typing…" indicator while the agent is thinking.
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    # run_agent_turn is synchronous (Anthropic SDK). We run it in a thread
    # so it doesn't block the async event loop for other users.
    try:
        reply = await asyncio.to_thread(
            run_agent_turn,
            _anthropic_client,
            messages,
        )
        # Add Claude's reply to history so the next turn has context.
        messages.append({"role": "assistant", "content": reply})

    except anthropic.RateLimitError:
        messages.pop()   # remove the user message — it wasn't answered
        reply = (
            "I'm getting too many requests right now. "
            "Please wait a moment and try again."
        )
    except anthropic.APIStatusError as e:
        messages.pop()
        logger.error(f"Anthropic API error for user {user_id}: {e}")
        reply = (
            "I ran into an issue connecting to the AI service. "
            "Please try again in a moment."
        )
    except Exception as e:
        messages.pop()
        logger.error(f"Unexpected error for user {user_id}: {e}", exc_info=True)
        reply = (
            "Sorry, something went wrong on my end. "
            "Please try again, or type /clear to start fresh."
        )

    # Telegram has a 4096-character message limit.
    # Split long responses into chunks.
    await send_long_message(update, reply)


async def send_long_message(update: Update, text: str) -> None:
    """
    Send a message, splitting it into chunks if it exceeds Telegram's limit.
    Tries Markdown first; falls back to plain text if parsing fails
    (Claude sometimes produces Markdown that Telegram's parser rejects).
    """
    chunks = _split_text(text, TELEGRAM_MAX_LENGTH)

    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Markdown parse error — send as plain text instead.
            await update.message.reply_text(chunk)


def _split_text(text: str, max_len: int) -> list[str]:
    """
    Split text into chunks of at most max_len characters,
    breaking at newlines where possible.
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline near the limit.
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip()

    return chunks


# ─── Bot startup ──────────────────────────────────────────────────────────────

def main() -> None:
    # ── Validate environment ───────────────────────────────────────────────────
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set in .env")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set in .env")
        sys.exit(1)

    # ── Load listings into memory ──────────────────────────────────────────────
    logger.info("Loading listings ...")
    listings = load_listings(str(CLEAN_DATA_FILE))
    if not listings:
        logger.warning(
            f"No listings found in {CLEAN_DATA_FILE}. "
            "Run scraper.runner and scraper.data_cleaner first."
        )
    else:
        logger.info(f"{len(listings)} listings loaded.")

    # ── Init Anthropic client (shared, module-level) ───────────────────────────
    global _anthropic_client
    _anthropic_client = anthropic.Anthropic(api_key=api_key)

    # ── Build Telegram application ─────────────────────────────────────────────
    app = Application.builder().token(bot_token).build()

    # Register command handlers.
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))

    # Register message handler — catches all non-command text messages.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ── Start polling ──────────────────────────────────────────────────────────
    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
