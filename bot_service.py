"""
========================================================================================
Viral Dropshipping Product & Video Scraper (bot_service.py)
========================================================================================
A clean, fast Telegram bot that scrapes winning, scaling video ads from Meta Ad Library.
Features:
- Instant 1-click viral video feed (US, IN, UAE, UK)
- Direct keyword search (just type any product name)
- Playable MP4 video streaming directly in Telegram
- 1-click supplier buttons (1688, YiwuGo, AliExpress, Meesho)
- Integrated Render HTTP health check server on $PORT (10000) for 24/7 cloud hosting
========================================================================================
"""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import logging
import os
import re
import sys
import threading
from typing import Any, Dict, Optional, Tuple

# Fix Windows console UTF-8 encoding safely for daemon mode
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "buffer") and not sys.stdout.closed:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        if sys.stderr and hasattr(sys.stderr, "buffer") and not sys.stderr.closed:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.constants import ParseMode
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    InlineKeyboardButton = object
    InlineKeyboardMarkup = object
    Update = object
    ParseMode = type('ParseMode', (), {'MARKDOWN': 'Markdown', 'HTML': 'HTML'})
    Application = None
    ContextTypes = type('ContextTypes', (), {'DEFAULT_TYPE': Any})
    filters = None

from config import settings
from notifier import TelegramDispatcher
from reverse_scanner import ReverseNetworkScanner

log_handlers = [logging.FileHandler("bot_daemon.log", encoding="utf-8")]
try:
    if sys.stdout and hasattr(sys.stdout, "closed") and not sys.stdout.closed:
        log_handlers.append(logging.StreamHandler(sys.stdout))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger("TrendArbitrage.TelegramBot")

# In-memory user session state store
user_sessions: Dict[int, Dict[str, Any]] = {}

# Global singletons
scanner = ReverseNetworkScanner()
dispatcher = TelegramDispatcher()


def is_authorized(user_id: int) -> bool:
    """Validates if user is the authorized chat ID."""
    if not settings.TELEGRAM_CHAT_ID:
        return True
    return str(user_id) == str(settings.TELEGRAM_CHAT_ID)


def get_user_country(user_id: int) -> str:
    """Returns the user's active country preference (defaults to US)."""
    session = user_sessions.setdefault(user_id, {})
    return session.get("country", "US")


# ======================================================================================
# KEYBOARDS & MENUS
# ======================================================================================

def get_main_menu_markup(current_country: str = "US") -> InlineKeyboardMarkup:
    """Generates the primary action dashboard."""
    keyboard = [
        [
            InlineKeyboardButton(f"🔥 Viral Feed ({current_country})", callback_data=f"feed:{current_country}"),
            InlineKeyboardButton("🇮🇳 India Feed", callback_data="feed:IN"),
        ],
        [
            InlineKeyboardButton("🇺🇸 US Feed", callback_data="feed:US"),
            InlineKeyboardButton("🇦🇪 UAE Feed", callback_data="feed:AE"),
            InlineKeyboardButton("🇬🇧 UK Feed", callback_data="feed:GB"),
        ],
        [
            InlineKeyboardButton("🌍 Change Default Country", callback_data="action:country_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_country_selection_markup() -> InlineKeyboardMarkup:
    """Generates country selection keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 United States", callback_data="set_country:US"),
            InlineKeyboardButton("🇮🇳 India", callback_data="set_country:IN"),
        ],
        [
            InlineKeyboardButton("🇦🇪 UAE / Middle East", callback_data="set_country:AE"),
            InlineKeyboardButton("🇬🇧 United Kingdom", callback_data="set_country:GB"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="action:start"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ======================================================================================
# CORE SCRAPER EXECUTION
# ======================================================================================

async def run_viral_scraper(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    keyword: Optional[str] = None,
    country: str = "US",
    limit: int = 3,
    status_msg_id: Optional[int] = None,
) -> None:
    """
    Executes the streamlined viral video scraper and sends playable MP4 videos to Telegram.
    """
    country_code = country.upper()
    is_keyword = bool(keyword and keyword.strip())
    label = f'for *"{keyword}"*' if is_keyword else "*current viral scaling winners*"

    status_text = (
        f"⚡ *Scraping Meta Ad Library* {label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Country: `{country_code}`\n"
        f"• Filter: *Active Video Creatives*\n"
        f"• Proof: *Proven Multi-Day Longevity*\n\n"
        f"🔎 Intercepting live video ads...\n"
        f"⏱️ _Please wait ~8-15 seconds for video compilation..._"
    )

    if status_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=status_text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            status_msg = await context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode=ParseMode.MARKDOWN)
            status_msg_id = status_msg.message_id
    else:
        status_msg = await context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode=ParseMode.MARKDOWN)
        status_msg_id = status_msg.message_id

    try:
        # Fetch top video ads
        ads = await scanner.scrape_viral_products(
            keyword=keyword,
            country=country_code,
            min_days=3,
            limit=limit,
        )

        if not ads:
            no_ads_text = (
                f"❌ *No active video campaigns found* {label} in `{country_code}`.\n\n"
                f"💡 _Tip: Try another product keyword (e.g. 'lamp', 'projector', 'brush', 'gadget') or tap below:_"
            )
            retry_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔥 Try Viral Feed ({country_code})", callback_data=f"feed:{country_code}")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="action:start")],
            ])
            await context.bot.send_message(chat_id=chat_id, text=no_ads_text, parse_mode=ParseMode.MARKDOWN, reply_markup=retry_markup)
            return

        # Deliver playable video cards to Telegram
        delivered = 0
        for ad in ads:
            success = await dispatcher.send_viral_ad(ad, target_chat_id=str(chat_id))
            if success:
                delivered += 1
            await asyncio.sleep(1.0)

        # Done summary message
        done_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 More Viral Winners", callback_data=f"feed:{country_code}"),
                InlineKeyboardButton("🔄 New Search", callback_data="action:start"),
            ]
        ])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ *Delivered {delivered} winning video products!*\n\n_Type any new keyword to search again or tap below:_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=done_markup,
        )

    except Exception as exc:
        logger.error(f"Scraper error for chat {chat_id}: {exc}", exc_info=True)
        err_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="action:start")]])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ *An error occurred during scraping:*\n`{str(exc)[:160]}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=err_markup,
        )


# ======================================================================================
# HANDLERS (COMMANDS, CALLBACKS, TEXT MESSAGES)
# ======================================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcoming dashboard with 1-click viral feed buttons."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    country = get_user_country(user_id)
    text = (
        "🔥 *Viral Dropshipping Video Scraper* 🔥\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Scrapes active, scaling video ads from Meta Ad Library with direct playable MP4 videos, clean product names, and Shopify store links.\n\n"
        f"🌍 *Active Country:* `{country}`\n\n"
        "👇 *Tap a button to get winning products or simply type any product name:*"
    )
    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_markup(country),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple operational guide."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    text = (
        "📖 *How to Use the Viral Video Scraper*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "• *Find Viral Winners:* Tap *[🔥 Viral Feed]* or type `/viral`\n"
        "• *Search Any Product:* Simply send the name into chat (e.g. `galaxy projector`, `sunset lamp`, `car cleaner`)\n"
        "• *Target Country:* `/country US`, `/country IN`, `/country AE`, or `/country GB`\n\n"
        "📦 *Every Alert Delivers:*\n"
        "1. Playable MP4 Video Creative\n"
        "2. Clean Product Title\n"
        "3. Active Running Days (Proof of ad spend)\n"
        "4. Live Storefront Link (Shopify/D2C landing page)\n"
        "5. 1-Click Factory Buttons (1688 / YiwuGo / AliExpress / Meesho)"
    )
    await update.message.reply_text(text=text, parse_mode=ParseMode.MARKDOWN)


async def viral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggers instant viral discovery for a specified or default country."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    args = context.args
    country = get_user_country(user_id)
    if args:
        c_arg = args[0].strip().upper()
        if c_arg in ["IN", "US", "AE", "GB"]:
            country = c_arg
            session = user_sessions.setdefault(user_id, {})
            session["country"] = country

    await run_viral_scraper(
        chat_id=update.effective_chat.id,
        context=context,
        keyword=None,
        country=country,
        limit=3,
    )


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Direct keyword search command: /scrape <product>."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("🔎 Please provide a product keyword. Example: `/scrape sunset lamp`", parse_mode=ParseMode.MARKDOWN)
        return

    query = " ".join(args).strip()
    country = get_user_country(user_id)
    await run_viral_scraper(
        chat_id=update.effective_chat.id,
        context=context,
        keyword=query,
        country=country,
        limit=3,
    )


async def country_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sets or views target country."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    args = context.args
    session = user_sessions.setdefault(user_id, {})
    if not args:
        current = session.get("country", "US")
        await update.message.reply_text(
            f"🌍 Current target country: *{current}*\n\nChange country with: `/country US` or `/country IN`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_markup(),
        )
        return

    code = args[0].strip().upper()
    if code in ["IN", "US", "AE", "GB"]:
        session["country"] = code
        await update.message.reply_text(f"✅ Target country updated to: *{code}*", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_markup(code))
    else:
        await update.message.reply_text("⚠️ Supported countries: `US`, `IN`, `AE`, `GB`", parse_mode=ParseMode.MARKDOWN)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Natural text handling: any sent text is treated as a product keyword search."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    country = get_user_country(user_id)
    await run_viral_scraper(
        chat_id=update.effective_chat.id,
        context=context,
        keyword=text,
        country=country,
        limit=3,
    )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline button clicks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    session = user_sessions.setdefault(user_id, {})

    if data.startswith("feed:"):
        country = data.split(":")[1]
        session["country"] = country
        await run_viral_scraper(
            chat_id=chat_id,
            context=context,
            keyword=None,
            country=country,
            limit=3,
            status_msg_id=query.message.message_id,
        )

    elif data == "action:next_viral":
        country = get_user_country(user_id)
        await run_viral_scraper(
            chat_id=chat_id,
            context=context,
            keyword=None,
            country=country,
            limit=2,
        )

    elif data == "action:country_menu":
        await query.edit_message_text(
            "🌍 *Select Target Country:*\nChoose which regional Meta Ad Library to query for scaling winning products:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_country_selection_markup(),
        )

    elif data.startswith("set_country:"):
        country = data.split(":")[1]
        session["country"] = country
        await query.edit_message_text(
            f"✅ Country set to *{country}*!\n\nTap below to explore viral video ads:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_markup(country),
        )

    elif data in ["action:start", "action:restart"]:
        country = get_user_country(user_id)
        text = (
            "🔥 *Viral Dropshipping Video Scraper* 🔥\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Scrapes active, scaling video ads from Meta Ad Library with direct playable MP4 videos, clean product names, and Shopify store links.\n\n"
            f"🌍 *Active Country:* `{country}`\n\n"
            "👇 *Tap a button to get winning products or simply type any product name:*"
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_markup(country),
        )


# ======================================================================================
# RENDER CLOUD HEALTH CHECK SERVER
# ======================================================================================

def start_render_health_server():
    """
    Render Free Web Services require binding an HTTP port ($PORT, usually 10000).
    Spins up a lightweight background HTTP server returning 200 OK so Render
    marks the deployment healthy without crashing or timing out.
    """
    port_str = os.environ.get("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok","service":"ViralVideoScraperBot","state":"running"}')

            def log_message(self, *args):
                pass  # suppress access logs from health pings

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Render HTTP health check server started on 0.0.0.0:{port}")
    except Exception as exc:
        logger.warning(f"Could not start Render health check server on port {port_str}: {exc}")


# ======================================================================================
# APPLICATION ENTRYPOINT
# ======================================================================================

def main():
    """Initializes and runs the simplified viral video scraper bot."""
    if not HAS_TELEGRAM:
        logger.error("python-telegram-bot is not installed. Please run: pip install python-telegram-bot>=20.0")
        print("[!] python-telegram-bot is required to run the bot daemon. Install with: pip install python-telegram-bot>=20.0")
        return
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_BOT_TOKEN":
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env.")
        return

    # Start cloud health server if PORT is defined (Render requirement)
    start_render_health_server()

    logger.info(f"Initializing Viral Video Scraper Daemon for bot token prefix: {token[:10]}...")
    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("viral", viral_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("search", scrape_command))
    app.add_handler(CommandHandler("country", country_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Viral Video Scraper Bot listening for interactive events...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot daemon stopped.")
