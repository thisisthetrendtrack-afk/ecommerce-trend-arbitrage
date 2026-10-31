"""
Notification & Delivery Module (notifier.py).
Dispatches formatted Telegram Markdown alerts with product photo creatives.
Includes CLI fallback with formatted rich tables and diagnostic panels.
"""

import io
import json
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import settings
from media_extractor import media_extractor
from models import OpportunityEvaluation, RTORiskLevel, SaturationTier, ScrapedAd

logger = logging.getLogger("TrendArbitrage.Notifier")
console = Console(force_terminal=True, legacy_windows=False)


def format_telegram_alert(evaluation: OpportunityEvaluation) -> str:
    """Formats opportunity into structured Telegram Markdown."""
    ad = evaluation.ad
    sat = evaluation.saturation
    eco = evaluation.economics

    tier_emoji = "💎" if sat.tier == SaturationTier.VIRGIN else "⚡" if sat.tier == SaturationTier.EARLY else "⚠️"
    risk_emoji = "🟢" if eco.rto_risk == RTORiskLevel.LOW else "🟡" if eco.rto_risk == RTORiskLevel.MEDIUM else "🔴"

    meesho_price_str = f"₹{sat.meesho.min_price_inr:,.0f} - ₹{sat.meesho.max_price_inr:,.0f}" if sat.meesho.min_price_inr else "None"
    amazon_price_str = f"Avg ₹{sat.amazon.avg_price_inr:,.0f}" if sat.amazon.avg_price_inr else "None"

    landing_page_md = f"[Storefront Link]({ad.landing_page_url})" if ad.landing_page_url else "N/A"
    creative_url_md = f"[View Meta Ad Creative]({ad.ad_library_url})"

    scaling_badge = (
        "🔥 HEAVILY SCALING"
        if ad.creative_variations_count >= 3
        else ("⚡ PROVEN RUNNER" if ad.days_active >= 8 else "🌱 PROMISING TEST")
    )

    text = (
        f"🔥 *E-COM ARBITRAGE OPPORTUNITY* 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Product:* `{ad.clean_product_name}`\n"
        f"🚀 *Scaling Status:* *{scaling_badge}*\n"
        f"🎯 *Arbitrage Score:* *{evaluation.arbitrage_score:.1f} / 100*  |  {tier_emoji} *Tier:* `{sat.tier.value}`\n"
        f"🛡️ *RTO Risk:* {risk_emoji} *{eco.rto_risk.value}*\n\n"
        f"🌍 *Ad Traction ({ad.source_country})*:\n"
        f"• Active Running: *{ad.days_active} consecutive days*\n"
        f"• Creative Variations: *{ad.creative_variations_count} active ad variations*\n"
        f"• 🎬 *Live Meta Ad:* {creative_url_md}\n"
        f"• 🌐 *Direct Store Link:* {landing_page_md}\n\n"
        f"🇮🇳 *India Saturation Check*:\n"
        f"• Meesho Listings: *{sat.meesho.listing_count}* ({meesho_price_str})\n"
        f"• Amazon.in Listings: *{sat.amazon.listing_count}* ({amazon_price_str})\n"
        f"• Active India Meta Ads: *{sat.india_meta_ads_count}*\n"
        f"• Saturation Status: _{sat.summary}_\n\n"
    )

    # Global Sourcing & Factory Benchmark Section
    if evaluation.sourcing:
        src = evaluation.sourcing
        if src.factory_price_rmb is not None:
            rmb_str = f"¥{src.factory_price_rmb:.1f}"
        elif src.factory_price_usd is not None:
            rmb_str = f"${src.factory_price_usd:.2f}"
        else:
            rmb_str = f"₹{src.factory_price_inr:,.0f}"

        if src.max_wholesale_inr:
            margin_status = (
                f"✅ WHOLESALE MATCH (<= ₹{src.max_wholesale_inr:,.0f})"
                if src.est_landed_cost_inr <= src.max_wholesale_inr
                else f"⚠️ EXCEEDS CAP (> ₹{src.max_wholesale_inr:,.0f})"
            )
        else:
            margin_status = "✅ VIABLE" if src.is_viable_margin else "⚠️ LOW MARGIN (<60%)"
        imart_status = f"Found ({', '.join(src.indiamart_hub_cities)})" if src.indiamart_available else "Zero local stock"

        text += (
            f"🏭 *Global Factory Sourcing (1688 / YiwuGo)*:\n"
            f"• Factory FOB Rate: *{rmb_str}* (~₹{src.factory_price_inr:,.0f})\n"
            f"• Dynamic Freight: *₹{src.freight_estimate_inr:,.0f}* (Volumetric)\n"
            f"• Customs/Taxes (35%): *₹{src.customs_taxes_inr:,.0f}*\n"
            f"• Est. Landed Cost in India: *₹{src.est_landed_cost_inr:,.0f}*\n"
            f"• Min. MOQ: *{src.moq} pcs*  |  Badge: _{src.supplier_badge}_\n"
            f"• IndiaMART Local Importers: *{imart_status}*\n"
            f"• Gross Sourcing Margin: *{src.gross_margin_pct:.1f}%* ({margin_status})\n\n"
        )

    text += (
        f"💰 *Unit Economics (Sweet Spot: ₹699 - ₹1,499)*:\n"
        f"• Target Selling Price: *₹{eco.recommended_selling_price_inr:,.0f}*\n"
        f"• Est. Sourcing Cost: ₹{eco.est_source_cost_inr:,.0f}\n"
        f"• Est. Shipping + COD RTO Buffer: ₹{(eco.est_shipping_inr + eco.est_rto_allowance_inr):,.0f}\n"
        f"• Est. Meta CPA: ₹{eco.est_marketing_cpa_inr:,.0f}\n"
        f"• Projected Net Margin: *{eco.est_net_margin_percentage:.1f}%*\n"
    )

    if eco.rto_reasons:
        text += f"\n⚠️ *RTO Warnings*: {', '.join(eco.rto_reasons)}\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    return text


def build_inline_keyboard(ad: ScrapedAd, evaluation: OpportunityEvaluation) -> Dict[str, Any]:
    """Generates Telegram inline action buttons beneath the creative asset."""
    query = urllib.parse.quote_plus(ad.clean_product_name)
    meesho_url = f"https://www.meesho.com/search?q={query}"
    factory_url = (
        evaluation.sourcing.sourcing_url
        if (evaluation.sourcing and evaluation.sourcing.sourcing_url)
        else f"https://en.yiwugo.com/search/s.html?q={query}"
    )

    keyboard = [
        [
            {"text": "🏭 View Factory Rate", "url": factory_url},
            {"text": "🛒 Search Meesho", "url": meesho_url},
        ],
    ]

    row2 = []
    if ad.landing_page_url and ad.landing_page_url.startswith("http"):
        row2.append({"text": "🌐 View Storefront", "url": ad.landing_page_url})
    row2.append({"text": "🎬 View Source Ad", "url": ad.ad_library_url})
    keyboard.append(row2)

    keyboard.append([{"text": "🔄 New Search", "callback_data": "action:restart"}])

    return {"inline_keyboard": keyboard}


class TelegramDispatcher:
    """Dispatches qualified alerts with playable MP4 video and photo creatives directly to Telegram."""

    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID

    async def send_alert(self, evaluation: OpportunityEvaluation, target_chat_id: Optional[str] = None) -> bool:
        """
        Sends an opportunity alert:
        - Case A (Video Available): Streams/uploads MP4 via sendVideo with inline buttons.
        - Case B (Image Only): Uploads high-res photo via sendPhoto with inline buttons.
        - Case C (Fallback): Dispatches rich text message with inline buttons.
        Cleans up local temporary media files post-transmission.
        """
        if not settings.is_telegram_configured:
            logger.info("Telegram not configured or disabled; skipping network dispatch.")
            return False

        dest_chat_id = str(target_chat_id or self.chat_id)
        caption = format_telegram_alert(evaluation)
        ad = evaluation.ad
        reply_markup = build_inline_keyboard(ad, evaluation)
        reply_markup_json = json.dumps(reply_markup)

        scaling_tag = "🔥 SCALING" if ad.is_confirmed_scaling else "⚡ PROVEN"
        header_caption = (
            f"🔥 *E-COM ARBITRAGE WINNER* ({scaling_tag})\n"
            f"📦 *Product:* `{ad.clean_product_name}`\n"
            f"🎯 *Score:* *{evaluation.arbitrage_score:.1f} / 100*  |  *Tier:* `{evaluation.saturation.tier.value}`\n"
            f"🌍 Active: *{ad.days_active}d* ({ad.creative_variations_count} variations) | 💰 Sweet Spot: *₹{evaluation.economics.recommended_selling_price_inr:,.0f}*"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            # --------------------------------------------------------------------------
            # CASE A: Video Creative Available (.MP4)
            # --------------------------------------------------------------------------
            if ad.video_url and ad.video_url.startswith("http"):
                local_vid_path = None
                try:
                    logger.info(f"[Telegram] Streaming MP4 video creative for {ad.clean_product_name}...")
                    local_vid_path = await media_extractor.stream_and_download_media(ad.video_url, is_video=True)

                    if local_vid_path and local_vid_path.exists():
                        send_vid_url = f"https://api.telegram.org/bot{self.bot_token}/sendVideo"
                        vid_caption = caption if len(caption) <= 1024 else header_caption

                        with open(local_vid_path, "rb") as vid_file:
                            files = {"video": (local_vid_path.name, vid_file, "video/mp4")}
                            data = {
                                "chat_id": dest_chat_id,
                                "caption": vid_caption,
                                "parse_mode": "Markdown",
                                "supports_streaming": "true",
                                "reply_markup": reply_markup_json,
                            }
                            resp = await client.post(send_vid_url, data=data, files=files)
                            if resp.status_code != 200:
                                # Retry without markdown if formatting parsing failed
                                vid_file.seek(0)
                                data.pop("parse_mode", None)
                                resp = await client.post(send_vid_url, data=data, files=files)

                        if resp.status_code == 200:
                            logger.info(f"✅ Playable MP4 Video alert delivered to Telegram for: {ad.clean_product_name}")
                            # If caption was truncated, follow up with detailed report
                            if len(caption) > 1024:
                                detail_resp = await client.post(
                                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                                    json={"chat_id": dest_chat_id, "text": caption[:4096], "parse_mode": "Markdown"}
                                )
                                if detail_resp.status_code != 200:
                                    await client.post(
                                        f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                                        json={"chat_id": dest_chat_id, "text": caption[:4096]}
                                    )
                            return True
                        else:
                            logger.warning(f"Telegram sendVideo returned {resp.status_code}: {resp.text}. Falling back to photo.")
                except Exception as vid_err:
                    logger.warning(f"Failed sending video creative: {vid_err}")
                finally:
                    media_extractor.cleanup_file(local_vid_path)

            # --------------------------------------------------------------------------
            # CASE B: Image Creative Available (High-Res Photo)
            # --------------------------------------------------------------------------
            if ad.image_url and ad.image_url.startswith("http"):
                local_img_path = None
                try:
                    local_img_path = await media_extractor.stream_and_download_media(ad.image_url, is_video=False)
                    send_photo_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
                    photo_caption = caption if len(caption) <= 1024 else header_caption

                    if local_img_path and local_img_path.exists():
                        with open(local_img_path, "rb") as img_file:
                            files = {"photo": (local_img_path.name, img_file, "image/jpeg")}
                            data = {
                                "chat_id": dest_chat_id,
                                "caption": photo_caption,
                                "parse_mode": "Markdown",
                                "reply_markup": reply_markup_json,
                            }
                            resp = await client.post(send_photo_url, data=data, files=files)
                            if resp.status_code != 200:
                                # Retry without markdown if formatting failed
                                img_file.seek(0)
                                data.pop("parse_mode", None)
                                resp = await client.post(send_photo_url, data=data, files=files)
                    else:
                        # Fallback to direct URL if streaming failed
                        payload = {
                            "chat_id": dest_chat_id,
                            "photo": ad.image_url,
                            "caption": photo_caption,
                            "parse_mode": "Markdown",
                            "reply_markup": reply_markup,
                        }
                        resp = await client.post(send_photo_url, json=payload)
                        if resp.status_code != 200:
                            payload.pop("parse_mode", None)
                            resp = await client.post(send_photo_url, json=payload)

                    if resp.status_code == 200:
                        logger.info(f"✅ High-res Photo alert delivered to Telegram for: {ad.clean_product_name}")
                        if len(caption) > 1024:
                            detail_resp = await client.post(
                                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                                json={"chat_id": dest_chat_id, "text": caption[:4096], "parse_mode": "Markdown"}
                            )
                            if detail_resp.status_code != 200:
                                await client.post(
                                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                                    json={"chat_id": dest_chat_id, "text": caption[:4096]}
                                )
                        return True
                    else:
                        logger.warning(f"Telegram sendPhoto notice ({resp.status_code}): {resp.text}. Falling back to text.")
                except Exception as img_err:
                    logger.warning(f"Failed sending photo creative: {img_err}")
                finally:
                    media_extractor.cleanup_file(local_img_path)

            # --------------------------------------------------------------------------
            # CASE C: Text Fallback with Inline Buttons
            # --------------------------------------------------------------------------
            try:
                send_msg_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                payload = {
                    "chat_id": dest_chat_id,
                    "text": caption[:4096],
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                    "reply_markup": reply_markup,
                }
                resp = await client.post(send_msg_url, json=payload)
                if resp.status_code != 200:
                    payload.pop("parse_mode", None)
                    resp = await client.post(send_msg_url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"✅ Text alert delivered to Telegram for: {ad.clean_product_name}")
                    return True
                else:
                    logger.error(f"Telegram sendMessage failed ({resp.status_code}): {resp.text}")
                    return False
            except Exception as exc:
                logger.error(f"Telegram dispatch exception: {exc}")
                return False


class RichConsoleReporter:
    """Renders formatted CLI tables and opportunity cards in the terminal."""

    @staticmethod
    def print_summary_table(evaluations: List[OpportunityEvaluation]) -> None:
        """Prints a comprehensive summary table using rich."""
        table = Table(
            title="🎯 E-COMMERCE TREND ARBITRAGE EVALUATION PIPELINE",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )

        table.add_column("Product", style="bold white", width=25)
        table.add_column("US Days", justify="center", width=9)
        table.add_column("Meesho", justify="center", width=8)
        table.add_column("India Ads", justify="center", width=10)
        table.add_column("Target Price", justify="right", width=12)
        table.add_column("Margin %", justify="right", width=10)
        table.add_column("RTO Risk", justify="center", width=10)
        table.add_column("Score", justify="center", width=8)
        table.add_column("Status", justify="center", width=14)

        for ev in evaluations:
            ad = ev.ad
            sat = ev.saturation
            eco = ev.economics

            tier_color = "green" if sat.tier == SaturationTier.VIRGIN else "yellow" if sat.tier == SaturationTier.EARLY else "red"
            risk_color = "green" if eco.rto_risk == RTORiskLevel.LOW else "yellow" if eco.rto_risk == RTORiskLevel.MEDIUM else "red"
            status_style = "bold green" if ev.qualified else "dim red"
            status_text = "QUALIFIED" if ev.qualified else "DISCARDED"

            table.add_row(
                ad.clean_product_name[:24],
                f"{ad.days_active}d",
                str(sat.meesho.listing_count),
                str(sat.india_meta_ads_count),
                f"₹{eco.recommended_selling_price_inr:,.0f}",
                f"{eco.est_net_margin_percentage:.1f}%",
                f"[{risk_color}]{eco.rto_risk.value}[/{risk_color}]",
                f"[bold {tier_color}]{ev.arbitrage_score:.1f}[/bold {tier_color}]",
                f"[{status_style}]{status_text}[/{status_style}]",
            )

        console.print(table)

    @staticmethod
    def print_detailed_card(ev: OpportunityEvaluation) -> None:
        """Prints an in-depth opportunity breakdown card."""
        panel_color = "green" if ev.qualified else "yellow"
        ad = ev.ad
        sat = ev.saturation
        eco = ev.economics

        details = (
            f"[bold]Product:[/bold] {ad.clean_product_name}\n"
            f"[bold]Source Ad ({ad.source_country}):[/bold] Active {ad.days_active} consecutive days\n"
            f"[bold]Ad Hook:[/bold] {ad.ad_title[:90]}...\n"
            f"[bold]Creative URL:[/bold] {ad.ad_library_url}\n"
            f"[bold]Landing Store:[/bold] {ad.landing_page_url or 'N/A'}\n\n"
            f"[bold]Market Saturation:[/bold] Meesho: {sat.meesho.listing_count} | Amazon.in: {sat.amazon.listing_count} | Meta IN Ads: {sat.india_meta_ads_count}\n"
            f"[bold]Tier:[/bold] {sat.tier.value} ({sat.summary})\n\n"
            f"[bold]Target India Price:[/bold] ₹{eco.recommended_selling_price_inr:,.0f} (Sweet Spot: {eco.in_sweet_spot})\n"
            f"[bold]Projected Net Margin:[/bold] {eco.est_net_margin_percentage:.1f}%\n"
            f"[bold]RTO Risk:[/bold] {eco.rto_risk.value} {'(' + ', '.join(eco.rto_reasons) + ')' if eco.rto_reasons else ''}\n"
            f"[bold]Arbitrage Score:[/bold] {ev.arbitrage_score:.1f} / 100\n"
            f"[bold]Score Factors:[/bold]\n  - " + "\n  - ".join(ev.evaluation_notes)
        )

        console.print(
            Panel(
                details,
                title=f"Opportunity Breakdown: {ad.clean_product_name}",
                border_style=panel_color,
                expand=False,
            )
        )
