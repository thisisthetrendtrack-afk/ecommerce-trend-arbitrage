"""
========================================================================================
Interactive Telegram Bot Daemon (bot_service.py)
========================================================================================
Built with python-telegram-bot (v20+ async)
Interactive Multi-Step Inline Flow:
  Step 1: Mode Selection ([🔥 Scrape Current Viral Ads] | [🔎 Search Specific Keyword])
  Step 2: Target Country Selection ([🇮🇳 India] | [🇺🇸 USA] | [🇦🇪 UAE] | [🇬🇧 UK])
  Step 3: Max Wholesale Landed Cost Filter ([Under ₹150] | [Under ₹300] | [Under ₹500] | [No Limit])
  Step 4: Pipeline Execution & Media Delivery with action buttons ([🏭 View Factory Rate] | [🛒 Search Meesho] | [🔄 New Search])
========================================================================================
"""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import logging
import os
import re
import sys
import threading
from typing import Any, Dict, Optional, Tuple

# Fix Windows console UTF-8 encoding safely for daemon/background mode
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
from utils.dedup_cache import dedup_cache

# Configure logging with fallback to file
log_file = open("bot_daemon.log", "a", encoding="utf-8", buffering=1)
log_handlers = [logging.StreamHandler(log_file)]
if sys.stdout and hasattr(sys.stdout, "closed") and not sys.stdout.closed:
    try:
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


def extract_query_and_price_filter(text: str) -> Tuple[str, Optional[float]]:
    """
    Parses user input like 'galaxy projector under 300' into keyword and wholesale price ceiling.
    """
    raw = text.strip()
    raw = re.sub(r"^/scan\s*", "", raw, flags=re.IGNORECASE)

    patterns = [
        r"(?:wholesale\s+)?(?:under|below|less\s+than|max|maximum|upto|up\s+to|<=|<)\s*(?:rs\.?|inr|₹)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:rs\.?|inr|₹|/-)?",
        r"(?:rs\.?|inr|₹)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:rs\.?|inr|₹|/-)?\s*(?:under|below|max|or\s+less)",
        r"(?:rs\.?|inr|₹)\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:inr|rs|rupees)",
    ]

    for pat in patterns:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            try:
                price = float(m.group(1))
                cleaned_query = raw[:m.start()] + raw[m.end():]
                cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()
                cleaned_query = re.sub(r"\b(wholesale|in|for)\b", "", cleaned_query, flags=re.IGNORECASE).strip()
                if cleaned_query:
                    return cleaned_query, price
            except ValueError:
                pass

    return raw, None


# ======================================================================================
# STEP 1: MODE SELECTION
# ======================================================================================

def get_step1_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔥 Scrape Current Viral Ads", callback_data="mode:viral")],
        [InlineKeyboardButton("🔎 Search Specific Keyword", callback_data="mode:keyword")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_step1_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, is_edit: bool = False, message_id: Optional[int] = None) -> None:
    text = (
        "👋 *E-Commerce Arbitrage & Factory Sourcing Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *Step 1: Choose Discovery Mode*\n\n"
        "• *Viral Discovery*: Scrapes live high-intent dropshipping creatives running in your target country without needing keywords.\n"
        "• *Keyword Search*: Analyzes a specific product niche against Meta Ads, Meesho saturation, and 1688 factory rates.\n\n"
        "👇 _Select an option to begin:_"
    )
    if is_edit and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_step1_markup(),
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_step1_markup(),
    )


# ======================================================================================
# STEP 2: TARGET COUNTRY SELECTION
# ======================================================================================

def get_step2_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🇮🇳 India", callback_data="country:IN"),
            InlineKeyboardButton("🇺🇸 USA", callback_data="country:US"),
        ],
        [
            InlineKeyboardButton("🇦🇪 UAE", callback_data="country:AE"),
            InlineKeyboardButton("🇬🇧 UK", callback_data="country:GB"),
        ],
        [InlineKeyboardButton("⬅️ Back to Step 1", callback_data="action:restart")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_step2_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, message_id: Optional[int] = None) -> None:
    session = user_sessions.get(chat_id, {})
    mode = session.get("mode", "viral")
    kw = session.get("keyword")
    mode_label = f"Keyword: `{kw}`" if mode == "keyword" and kw else "Automated Viral Ads"

    text = (
        f"🌍 *Step 2: Select Target Market*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mode: *{mode.upper()}* ({mode_label})\n\n"
        f"Select the regional Meta Ad Library database to query for sustained winning ads (running >= 5 days):"
    )

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_step2_markup(),
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_step2_markup(),
    )


# ======================================================================================
# STEP 3: MAX WHOLESALE LANDED COST FILTER (INR)
# ======================================================================================

def get_step3_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Under ₹150", callback_data="budget:150"),
            InlineKeyboardButton("Under ₹300", callback_data="budget:300"),
        ],
        [
            InlineKeyboardButton("Under ₹500", callback_data="budget:500"),
            InlineKeyboardButton("No Limit (All)", callback_data="budget:none"),
        ],
        [InlineKeyboardButton("⬅️ Back to Step 2", callback_data="action:back_country")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_step3_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, message_id: Optional[int] = None) -> None:
    session = user_sessions.get(chat_id, {})
    country = session.get("country", "IN")

    text = (
        f"💰 *Step 3: Max Wholesale Landed Cost Filter (INR)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Target Country: *{country}*\n\n"
        f"Filter products by estimated Indian Landed Cost:\n"
        f"$$\\text{{Landed Cost}} = \\text{{FOB Rate}} + \\text{{Volumetric Freight}} + 35\\% \\text{{ Customs}}$$\n\n"
        f"Choose your wholesale ceiling or select *No Limit* to evaluate all active opportunities:"
    )

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_step3_markup(),
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_step3_markup(),
    )


# ======================================================================================
# STEP 4: PIPELINE EXECUTION & RESULT DISPATCH
# ======================================================================================

async def run_pipeline_execution(chat_id: int, context: ContextTypes.DEFAULT_TYPE, message_id: Optional[int] = None) -> None:
    session = user_sessions.get(chat_id, {})
    mode = session.get("mode", "viral")
    keyword = session.get("keyword")
    country = session.get("country", "IN")
    budget = session.get("budget")

    budget_label = f"<= ₹{budget:.0f}" if budget else "No Cap"
    term_label = f"`{keyword}`" if keyword else "_Automated E-Com Viral Footprint_"

    exec_text = (
        f"⚡ *Step 4: Pipeline Execution Active*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Country:* `{country}`\n"
        f"• *Target Query:* {term_label}\n"
        f"• *Wholesale Ceiling:* `{budget_label}`\n\n"
        f"🔎 Intercepting Meta Ads GraphQL stream...\n"
        f"🛒 Cross-checking Meesho catalog saturation...\n"
        f"🏭 Computing Tier-1 China FOB (1688 / YiwuGo)...\n"
        f"📦 Factoring courier forward, COD fee & 25% RTO loss...\n\n"
        f"⏱️ _Please wait ~12-18 seconds for asset compilation..._"
    )

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=exec_text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=exec_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id=chat_id, text=exec_text, parse_mode=ParseMode.MARKDOWN)

    try:
        evaluations = await scanner.scan_and_evaluate(
            keyword=keyword,
            country=country,
            min_days=5,
            limit=3,
            send_telegram=False,
            max_wholesale_inr=budget,
        )

        if not evaluations:
            fail_text = (
                f"❌ *No sustained profitable ads found for your criteria.*\n\n"
                f"• Country: `{country}`\n"
                f"• Target: {term_label}\n"
                f"• Wholesale Cap: `{budget_label}`\n\n"
                f"Either no active campaigns met the >= 5 days longevity threshold, or sourcing costs exceeded your budget cap."
            )
            restart_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 New Search", callback_data="action:restart")]])
            await context.bot.send_message(chat_id=chat_id, text=fail_text, parse_mode=ParseMode.MARKDOWN, reply_markup=restart_keyboard)
            return

        # Deliver cards to phone
        delivered_count = 0
        for ev in evaluations:
            success = await dispatcher.send_alert(ev, target_chat_id=str(chat_id))
            if success:
                delivered_count += 1
            await asyncio.sleep(1.0)

        done_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 New Search", callback_data="action:restart")]])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ *Pipeline Scan Complete!*\nDelivered *{delivered_count}* verified market opportunities to your feed.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=done_markup,
        )

    except Exception as exc:
        logger.error(f"Execution error for chat {chat_id}: {exc}", exc_info=True)
        err_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="action:restart")]])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ *An error occurred during scan execution:*\n`{str(exc)[:180]}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=err_markup,
        )


# ======================================================================================
# HANDLERS (COMMANDS, CALLBACKS, MESSAGES)
# ======================================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        return

    user_sessions[user_id] = {}
    await send_step1_menu(update.effective_chat.id, context)


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    args = context.args
    if not args:
        # Launch Step 1 interactive wizard
        user_sessions[user_id] = {}
        await send_step1_menu(update.effective_chat.id, context)
        return

    full_text = " ".join(args)
    query, max_price = extract_query_and_price_filter(full_text)
    session = user_sessions.setdefault(user_id, {})
    session["mode"] = "keyword"
    session["keyword"] = query
    session["budget"] = max_price if max_price is not None else session.get("default_budget")

    ack_text = f"🔎 Product query: *{query}*"
    if session.get("budget"):
        ack_text += f"\n🎯 Wholesale Cap: *<= ₹{session['budget']:.0f}*"

    await update.message.reply_text(
        f"{ack_text}\n\nSelect target market to analyze:",
        parse_mode=ParseMode.MARKDOWN,
    )
    await send_step2_menu(update.effective_chat.id, context)


async def viral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    args = context.args
    country = "IN"
    if args:
        c_input = args[0].strip().upper()
        if c_input in ["IN", "US", "AE", "GB"]:
            country = c_input
        else:
            await update.message.reply_text("⚠️ Unsupported country code. Supported: `IN`, `US`, `AE`, `GB`. Defaulting to `IN`.", parse_mode=ParseMode.MARKDOWN)

    session = user_sessions.setdefault(user_id, {})
    session["mode"] = "viral"
    session["keyword"] = None
    session["country"] = country
    session["budget"] = session.get("default_budget")

    # Run pipeline directly
    await run_pipeline_execution(update.effective_chat.id, context)


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    args = context.args
    session = user_sessions.setdefault(user_id, {})
    if not args:
        current_b = session.get("default_budget")
        msg = (
            f"💰 *Wholesale Landed Cost Budget*\n"
            f"Current Setting: *{f'<= ₹{current_b:.0f} INR' if current_b else 'No Limit (All Items)'}*\n\n"
            f"To set a new default cap: `/budget 250` or `/budget 400`\n"
            f"To clear the cap: `/budget clear`"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    val = args[0].strip().lower()
    if val in ["clear", "none", "reset", "0"]:
        session["default_budget"] = None
        session["budget"] = None
        await update.message.reply_text("✅ Wholesale price ceiling cleared (No Limit).", parse_mode=ParseMode.MARKDOWN)
    else:
        try:
            amt = float(re.sub(r"[^\d.]", "", val))
            session["default_budget"] = amt
            session["budget"] = amt
            await update.message.reply_text(f"✅ Default wholesale landed cost cap set to: *<= ₹{amt:.0f} INR*.", parse_mode=ParseMode.MARKDOWN)
        except ValueError:
            await update.message.reply_text("⚠️ Invalid amount. Example: `/budget 300` or `/budget clear`.", parse_mode=ParseMode.MARKDOWN)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_sessions[user_id] = {}
    await update.message.reply_text("🔄 Session reset successfully. Send `/start` to begin a new scan.", parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    help_text = (
        "📖 *E-Commerce Arbitrage & Sourcing Bot Commands*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "• `/start` - Launch interactive 4-step wizard.\n"
        "• `/scrape <keyword>` - One-shot analysis (e.g. `/scrape crystal lamp` or `/scrape galaxy projector under 300`).\n"
        "• `/viral [country]` - Instant viral discovery without keywords (defaults to `IN`; accepts `US`, `AE`, `GB`).\n"
        "• `/budget <amount>` - Set default wholesale landed cost cap (e.g. `/budget 250` or `/budget clear`).\n"
        "• `/reset` - Clear current session and input states.\n"
        "• `/stats` - View SQLite cache and analyzed ad statistics.\n"
        "• `/help` - View this command guide.\n\n"
        "🌍 *Supported Countries:* `IN` (India), `US` (United States), `AE` (UAE), `GB` (United Kingdom).\n"
        "💰 *Wholesale Sourcing:* Tier-1 1688 / YiwuGo factory FOB + Dynamic Freight + 35% Customs + Indian COD RTO viability check."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    stats = dedup_cache.get_stats()
    text = (
        f"📊 *SQLite Cache & System Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Total Processed Unique Ads: *{stats['total_processed']}*\n"
        f"• Qualified Arbitrage Wins: *{stats['qualified_count']}*\n"
        f"• Local Cache Database: `processed_ads.db`"
    )
    restart_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start New Scan", callback_data="action:restart")]])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=restart_markup)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_authorized(user_id):
        return

    data = query.data
    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    if user_id not in user_sessions:
        user_sessions[user_id] = {}

    # Action restart
    if data == "action:restart":
        user_sessions[user_id] = {}
        await send_step1_menu(chat_id, context, is_edit=True, message_id=msg_id)
        return

    if data == "action:back_country":
        await send_step2_menu(chat_id, context, message_id=msg_id)
        return

    # Step 1 handlers
    if data == "mode:viral":
        user_sessions[user_id]["mode"] = "viral"
        user_sessions[user_id]["keyword"] = None
        await send_step2_menu(chat_id, context, message_id=msg_id)
        return

    if data == "mode:keyword":
        user_sessions[user_id]["mode"] = "keyword_pending"
        prompt_text = (
            "🔎 *Enter Product Keyword*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Please type the product keyword or niche in chat (e.g. `galaxy projector`, `ice roller`, `neck stretcher`):"
        )
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Step 1", callback_data="action:restart")]])
        await query.edit_message_text(prompt_text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_markup)
        return

    # Step 2 handlers
    if data.startswith("country:"):
        country_code = data.split(":")[1].upper()
        user_sessions[user_id]["country"] = country_code

        # If user pre-set a budget via fast-track text search, execute immediately
        if user_sessions[user_id].get("budget") is not None:
            await run_pipeline_execution(chat_id, context, message_id=msg_id)
        else:
            await send_step3_menu(chat_id, context, message_id=msg_id)
        return

    # Step 3 handlers
    if data.startswith("budget:"):
        raw_budget = data.split(":")[1]
        budget_val = None if raw_budget == "none" else float(raw_budget)
        user_sessions[user_id]["budget"] = budget_val
        await run_pipeline_execution(chat_id, context, message_id=msg_id)
        return


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    text = update.message.text.strip()
    session = user_sessions.setdefault(user_id, {})

    # If user was prompted to type keyword for Step 1
    if session.get("mode") == "keyword_pending":
        query, max_price = extract_query_and_price_filter(text)
        session["mode"] = "keyword"
        session["keyword"] = query
        if max_price:
            session["budget"] = max_price

        await update.message.reply_text(
            f"✅ Keyword received: *{query}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        await send_step2_menu(update.effective_chat.id, context)
        return

    # Shortcut: User typed directly without /start (e.g. 'galaxy projector under 300' or 'sunset lamp')
    query, max_price = extract_query_and_price_filter(text)
    session["mode"] = "keyword"
    session["keyword"] = query
    if max_price:
        session["budget"] = max_price

    ack_text = f"🔎 Product query: *{query}*"
    if max_price:
        ack_text += f"\n🎯 Wholesale Cap: *<= ₹{max_price:.0f}*"

    await update.message.reply_text(
        f"{ack_text}\n\nProceed to choose target market:",
        parse_mode=ParseMode.MARKDOWN,
    )
    await send_step2_menu(update.effective_chat.id, context)


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
                self.wfile.write(b'{"status":"ok","service":"MyTrendsAlertBot","state":"running"}')

            def log_message(self, *args):
                pass  # suppress access logs from health pings

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Render HTTP health check server started on 0.0.0.0:{port}")
    except Exception as exc:
        logger.warning(f"Could not start Render health check server on port {port_str}: {exc}")


def main():
    """Initializes and runs the python-telegram-bot application."""
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

    logger.info(f"Initializing Telegram Daemon for bot token prefix: {token[:10]}...")
    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("viral", viral_command))
    app.add_handler(CommandHandler("budget", budget_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Telegram Bot Daemon listening for interactive inline events...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot daemon stopped.")
