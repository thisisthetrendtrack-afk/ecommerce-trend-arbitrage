"""
Quick Telegram Alert Verification Script (test_telegram_phone.py)
Sends a sample verified arbitrage opportunity directly to your phone via Telegram.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
import httpx

from config import settings
from models import (
    OpportunityEvaluation,
    PlatformCompetition,
    RTORiskLevel,
    SaturationReport,
    SaturationTier,
    ScrapedAd,
    SourcingBenchmark,
    UnitEconomics,
)
from notifier import TelegramDispatcher, format_telegram_alert


def create_sample_opportunity() -> OpportunityEvaluation:
    """Creates a sample verified winning dropshipping opportunity."""
    ad = ScrapedAd(
        ad_id="1536941208479218",
        source_country="US",
        started_date=datetime.now(timezone.utc),
        days_active=28,
        ad_title="Uproot Clean - The Ultimate Pet Hair Remover for Carpets & Rugs",
        ad_body="That musty smell in your house isn't your dog. It's what's buried in your carpet. Pet hair locks between carpet fibers. 50% off today only with free express shipping!",
        landing_page_url="https://cc.uprootclean.com/main/phr",
        image_url="https://images.unsplash.com/photo-1583337130417-3346a1be7dee?w=600&auto=format&fit=crop&q=80",
        video_url="https://video.fluh3-2.fna.fbcdn.net/o1/v/t2/f2/m366/AQNgPxH6-wsmIoeK2xAPz1U0vJxaZsIwmxaCtJeo7Ev8eQabKNVIpeqlV6M7kxP81VEbxov7EoGzZhhOYuVuLi7iZC2UgtrO8_KAEiof6BbFIw.mp4?_nc_cat=103&_nc_oc=Adqy-GVE55XDn6fRJmEBk1A6fEhGJDlDprH9rsVrpk56qDNEF6lSxZi7bBghh0WOKes&_nc_sid=b66105&_nc_ht=video.fluh3-2.fna.fbcdn.net&_nc_ohc=XKIbH23lmc8Q7kNvwGiWq3k&efg=eyJ2ZW5jb2RlX3RhZyI6Inhwdl9wcm9ncmVzc2l2ZS5WSV9VU0VDQVNFX1BST0RVQ1RfVFlQRS4uQzMuNzIwLmRhc2hfaDI2NC1iYXNpYy1nZW4yXzcyMHAiLCJ4cHZfYXNzZXRfaWQiOjEzOTg2MzQxMjE1MDI0MjYsImFzc2V0X2FnZV9kYXlzIjozMTcsInZpX3VzZWNhc2VfaWQiOjEwNzk5LCJkdXJhdGlvbl9zIjoxNSwidXJsZ2VuX3NvdXJjZSI6Ind3dyJ9&ccb=17-1&vs=ec2e951785b5ce35&_nc_vs=HBksFQIYRWZiX2VwaGVtZXJhbC8zRTRENDcwNjMwRUVBRDlBODM2MEQxMDEyQ0JEM0JCN19tdF8xX3ZpZGVvX2Rhc2hpbml0Lm1wNBUAAsgBEgAVAhhAZmJfcGVybWFuZW50L0YxNDdDQUIxRTEzMkZFNENDRjBFMjQyM0UyNjU4Njg4X2F1ZGlvX2Rhc2hpbml0Lm1wNBUCAsgBEgAoABgAGwKIB3VzZV9vaWwBMRJwcm9ncmVzc2l2ZV9yZWNpcGUBMRUAACa0-9yfnIP8BBUCKAJDMywXQC4HrhR64UgYGWRhc2hfaDI2NC1iYXNpYy1nZW4yXzcyMHARAHUAZd6oAQA&_nc_gid=qYAFaDW6DguU_iu88_8Gwg&_nc_ss=7a289&_nc_zt=28&oh=00_AQScVnmIfS2jmklrsAi2BTvYA3UPtHQ8V7jlNI1U2PhtYg&oe=6AEBEC0D",
        ad_library_url="https://www.facebook.com/ads/library/?id=1536941208479218",
        clean_product_name="Uproot Clean - Pet Hair Remover",
        core_keywords=["Pet Hair Remover", "Uproot Clean"],
    )

    saturation = SaturationReport(
        meesho=PlatformCompetition(
            platform="Meesho",
            listing_count=1,
            min_price_inr=450.0,
            max_price_inr=599.0,
            avg_price_inr=524.0,
        ),
        amazon=PlatformCompetition(
            platform="Amazon.in",
            listing_count=2,
            min_price_inr=649.0,
            max_price_inr=749.0,
            avg_price_inr=699.0,
        ),
        india_meta_ads_count=0,
        india_meta_ad_urls=[],
        tier=SaturationTier.VIRGIN,
        summary="VIRGIN OPPORTUNITY: Only 1 Meesho listing and 0 active India ads. Untapped blue ocean.",
    )

    economics = UnitEconomics(
        est_source_cost_inr=198.0,
        est_shipping_inr=90.0,
        est_marketing_cpa_inr=260.0,
        est_rto_allowance_inr=35.0,
        recommended_selling_price_inr=899.0,
        est_net_margin_percentage=35.2,
        rto_risk=RTORiskLevel.LOW,
        rto_reasons=[],
        in_sweet_spot=True,
    )

    sourcing = SourcingBenchmark(
        platform="YiwuGo / 1688 Wholesale",
        factory_price_rmb=15.0,
        factory_price_usd=2.10,
        factory_price_inr=174.0,
        moq=10,
        supplier_badge="Verified Gold Factory",
        freight_estimate_inr=120.0,
        customs_taxes_inr=60.9,
        est_landed_cost_inr=354.9,
        target_selling_price_inr=899.0,
        gross_margin_pct=60.5,
        is_viable_margin=True,
        indiamart_available=True,
        indiamart_hub_cities=["Delhi", "Surat"],
        sourcing_url="https://en.yiwugo.com/search/s.html?q=sunset+lamp",
    )

    return OpportunityEvaluation(
        ad=ad,
        saturation=saturation,
        economics=economics,
        sourcing=sourcing,
        arbitrage_score=85.0,
        qualified=True,
        evaluation_notes=[
            "+35 pts: Sustained 24 days running in US",
            "+40 pts: VIRGIN market opportunity",
            "+15 pts: Target price within ₹699-₹1499 sweet spot",
            "+10 pts: High net margin (35.2%)",
        ],
    )


async def main():
    parser = argparse.ArgumentParser(description="Test Telegram Notification Delivery on Phone")
    parser.add_argument("--token", type=str, help="Telegram Bot Token (e.g. 123456:ABC-DEF...)")
    parser.add_argument("--chat-id", type=str, help="Telegram Chat ID or @channel (e.g. 987654321 or @my_channel)")
    args = parser.parse_args()

    token = args.token or settings.TELEGRAM_BOT_TOKEN
    chat_id = args.chat_id or settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        print("\n[!] Telegram credentials missing.")
        print("Please provide them via CLI arguments:")
        print("   python test_telegram_phone.py --token YOUR_BOT_TOKEN --chat-id YOUR_CHAT_ID")
        print("Or set them inside your .env file:")
        print("   TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN")
        print("   TELEGRAM_CHAT_ID=YOUR_CHAT_ID")
        print("   TELEGRAM_ENABLED=true\n")
        sys.exit(1)

    # Temporarily override settings if passed via CLI
    settings.TELEGRAM_BOT_TOKEN = token
    settings.TELEGRAM_CHAT_ID = chat_id
    settings.TELEGRAM_ENABLED = True

    sample_ev = create_sample_opportunity()
    print(f"[*] Sending sample Arbitrage Opportunity to Telegram ({chat_id})...")

    dispatcher = TelegramDispatcher()
    success = await dispatcher.send_alert(sample_ev)

    if success:
        print("[SUCCESS] Alert delivered to your phone! Please check your Telegram app.")
    else:
        print("[FAILED] Could not send message to Telegram. Check your Bot Token and Chat ID.")


if __name__ == "__main__":
    asyncio.run(main())
