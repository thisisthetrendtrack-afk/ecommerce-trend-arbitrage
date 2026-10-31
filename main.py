"""
Main Orchestrator (main.py).
Coordinates the async trend arbitrage pipeline:
1. Western Ad Ingestion (>= 7 days longevity filter)
2. India Saturation & Competition Verification (Meesho, Amazon.in, India Meta Ads + Visual Match)
3. Unit Economics & RTO Risk Filtering (Sweet Spot: ₹699 - ₹1,499)
4. Arbitrage Scoring & Telegram Alert Delivery
"""

import argparse
import asyncio
import io
import logging
import signal
import sys
from typing import List

# Fix Windows console UTF-8 encoding support
if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.logging import RichHandler

from utils.http_client import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings
from ingestion import MetaAdLibraryIngestor, get_mock_test_feed
from models import OpportunityEvaluation, ScrapedAd
from saturation import SaturationChecker
from analyzer import OpportunityAnalyzer
from notifier import RichConsoleReporter, TelegramDispatcher
from utils.browser import browser_manager

# Configure rich structured logging
console = Console(force_terminal=True, legacy_windows=False)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, console=console)]
)
logger = logging.getLogger("TrendArbitrage.Main")


class ArbitragePipelineEngine:
    """Coordinates concurrent pipeline execution with backoff and error mitigation."""

    def __init__(self, concurrency_limit: int = 3, dry_run: bool = False):
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.ingestor = MetaAdLibraryIngestor()
        self.saturation_checker = SaturationChecker()
        self.analyzer = OpportunityAnalyzer()
        self.telegram = TelegramDispatcher()
        self.dry_run = dry_run

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=10),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        reraise=False
    )
    async def process_single_ad(self, ad: ScrapedAd) -> OpportunityEvaluation:
        """Processes a single scraped ad through saturation check, economics, and scoring."""
        async with self.semaphore:
            logger.info(f"Analyzing product: '{ad.clean_product_name}' (US Active: {ad.days_active}d)")
            
            # Step 1: India Multi-Channel Saturation Check
            saturation_report = await self.saturation_checker.analyze_product_saturation(ad)

            # Step 2: Unit Economics & Feasibility Filter
            evaluation = self.analyzer.evaluate(ad, saturation_report)

            # Step 3: Notification Dispatch if qualified
            if evaluation.qualified and not self.dry_run:
                logger.info(f"✨ Opportunity QUALIFIED! Dispatching alert: {ad.clean_product_name} (Score: {evaluation.arbitrage_score})")
                await self.telegram.send_alert(evaluation)
            elif not evaluation.qualified:
                logger.info(f"Item not qualified (Score: {evaluation.arbitrage_score}, Tier: {saturation_report.tier.value})")

            return evaluation

    async def run_pipeline(
        self,
        keywords: List[str],
        countries: List[str],
        limit: int,
        demo_mode: bool = False
    ) -> List[OpportunityEvaluation]:
        """Main execution flow for trend ingestion and verification."""
        console.print("[bold cyan]============================================================[/bold cyan]")
        console.print("[bold green] >>> STARTING E-COMMERCE TREND ARBITRAGE ENGINE <<< [/bold green]")
        console.print(f"[dim]Countries: {', '.join(countries)} | Min Longevity: {settings.MIN_AD_ACTIVE_DAYS} days | Concurrency: {settings.MAX_CONCURRENT_TASKS}[/dim]")
        console.print("[bold cyan]============================================================[/bold cyan]\n")

        # 1. Western Ad Ingestion
        if demo_mode:
            logger.info("Demo mode active: Utilizing verified dropshipping winning ad fixtures.")
            scraped_ads = get_mock_test_feed()[:limit]
        else:
            logger.info("Scanning Meta Ad Library for active winning dropshipping ads...")
            scraped_ads = await self.ingestor.ingest_batch(
                keywords=keywords,
                countries=countries,
                max_total=limit
            )

        if not scraped_ads:
            logger.warning("No ads met the >= 7 consecutive days active filter or search returned 0 items.")
            return []

        logger.info(f"Proceeding to Indian market saturation analysis for {len(scraped_ads)} candidate products...")

        # 2. Parallel Competition & Economics Processing
        tasks = [self.process_single_ad(ad) for ad in scraped_ads]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        evaluations: List[OpportunityEvaluation] = []
        for res in raw_results:
            if isinstance(res, OpportunityEvaluation):
                evaluations.append(res)
            elif isinstance(res, Exception):
                logger.error(f"Error processing ad candidate: {res}")

        if not evaluations:
            logger.warning("No candidate evaluations completed successfully.")
            return []

        # 3. Terminal Reporting
        console.print("\n")
        RichConsoleReporter.print_summary_table(evaluations)

        qualified_opps = [ev for ev in evaluations if ev.qualified]
        console.print(f"\n[bold green]Pipeline finished! Total qualified opportunities: {len(qualified_opps)} / {len(evaluations)}[/bold green]\n")

        for opp in qualified_opps:
            RichConsoleReporter.print_detailed_card(opp)

        return evaluations


async def main_async():
    """CLI Entry point with flags and graceful cancellation."""
    parser = argparse.ArgumentParser(
        description="E-Commerce Trend Arbitrage & Market Saturation Automation Engine"
    )
    parser.add_argument(
        "--keywords",
        type=str,
        help="Comma-separated dropshipping search keywords (overrides .env)",
    )
    parser.add_argument(
        "--countries",
        type=str,
        help="Comma-separated country codes, e.g., US,GB,CA (overrides .env)",
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=settings.MIN_AD_ACTIVE_DAYS,
        help="Minimum consecutive days an ad must be active (default: 7)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of candidate ads to evaluate (default: 10)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=settings.MAX_CONCURRENT_TASKS,
        help="Maximum concurrent evaluation tasks (default: 3)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run Playwright browser in headless mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute analysis without sending Telegram notifications",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run end-to-end simulation with verified dropshipping ad fixtures",
    )

    args = parser.parse_args()

    # Apply command line overrides
    settings.MIN_AD_ACTIVE_DAYS = args.min_days
    settings.MAX_CONCURRENT_TASKS = args.concurrency
    settings.HEADLESS = args.headless

    keywords = (
        [k.strip() for k in args.keywords.split(",") if k.strip()]
        if args.keywords
        else settings.AD_KEYWORDS
    )
    countries = (
        [c.strip().upper() for c in args.countries.split(",") if c.strip()]
        if args.countries
        else settings.SEARCH_COUNTRIES
    )

    engine = ArbitragePipelineEngine(
        concurrency_limit=settings.MAX_CONCURRENT_TASKS,
        dry_run=args.dry_run
    )

    try:
        await engine.run_pipeline(
            keywords=keywords,
            countries=countries,
            limit=args.limit,
            demo_mode=args.demo
        )
    finally:
        # Guarantee browser and context cleanup
        await browser_manager.close()


def main():
    """Synchronous launcher handling signals."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("\nExecution interrupted by user. Exiting cleanly...")
        sys.exit(0)


if __name__ == "__main__":
    main()
