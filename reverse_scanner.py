"""
========================================================================================
Reverse-Engineered Public Frontend Network Scanner (reverse_scanner.py)
========================================================================================
ZERO API Keys | ZERO OAuth Tokens | ZERO Fragile DOM / CSS Scraping

Architecture & Operational Flow:
1. Playwright + stealth is used solely to initiate a clean, unauthenticated browser session.
2. Network response interception (`page.on('response', ...)`) captures internal JSON/GraphQL
   payloads dispatched by official client web applications.
3. Fallback extracts hydration state blobs (`<script type="application/json" data-sjs>` on Meta,
   `<script id="__NEXT_DATA__">` on Meesho) directly from memory/source.
4. Data extraction operates purely on typed dictionary trees, computing ad longevity and
   India market saturation with zero CSS selector fragility.
========================================================================================
"""

import asyncio
import io
import json
import logging
import random
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Fix Windows console encoding for UTF-8 and Rich
if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import settings
from media_extractor import media_extractor
from analyzer import OpportunityAnalyzer
from models import (
    OpportunityEvaluation,
    PlatformCompetition,
    RTORiskLevel,
    SaturationReport,
    SaturationTier,
    ScrapedAd,
    UnitEconomics,
)
from notifier import TelegramDispatcher
from sourcing import sourcing_benchmarker
from utils.browser import browser_manager
from utils.dedup_cache import dedup_cache
from utils.http_client import HumanizedHttpClient
from utils.keyword_extractor import (
    calculate_token_overlap,
    extract_core_keywords,
    is_meesho_algorithmic_fallback,
    sanitize_text,
)

logger = logging.getLogger("TrendArbitrage.ReverseScanner")
console = Console(force_terminal=True, legacy_windows=False)


# ======================================================================================
# JSON Tree Helper Utilities
# ======================================================================================

def find_nodes_by_key(root: Any, target_key: str) -> List[Any]:
    """
    Recursively navigates any arbitrary nested dictionary/list structure to extract
    all values mapped to `target_key`. Used to decouple scanner from dynamic bundle wrappers.
    """
    matches = []
    if isinstance(root, dict):
        if target_key in root:
            matches.append(root[target_key])
        for value in root.values():
            matches.extend(find_nodes_by_key(value, target_key))
    elif isinstance(root, list):
        for item in root:
            matches.extend(find_nodes_by_key(item, target_key))
    return matches


# ======================================================================================
# Meta Ad Library Zero-API Interceptor
# ======================================================================================

COUNTRY_VIRAL_FOOTPRINTS: Dict[str, List[str]] = {
    "IN": [
        '"Cash on delivery" "Shop Now"',
        '"Free shipping all over India" "Order Now"',
        '"Pay on delivery" "Buy 1 Get 1"',
    ],
    "US": [
        '"50% OFF" "Free Worldwide Shipping" "Shop Now"',
        '"Limited quantity available" "Shop Now"',
    ],
    "AE": [
        '"Cash on delivery" "Free delivery" "Shop Now"',
        '"COD available" "Order Now UAE"',
    ],
    "GB": [
        '"Free UK delivery" "Order Now"',
        '"50% off sale ends today"',
    ],
}


def is_valid_ecommerce_landing_page(url: Optional[str]) -> bool:
    """
    Anti-Noise Landing Page Gate:
    Disqualifies non-ecommerce domains and junk lead paths.
    """
    if not url or not url.startswith("http"):
        return False
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    # Disqualified domains (social networks, app stores, messaging)
    disqualified = [
        "facebook.com", "instagram.com", "wa.me", "whatsapp.com",
        "play.google.com", "apps.apple.com", "youtube.com", "youtu.be",
        "twitter.com", "x.com", "linkedin.com", "t.me"
    ]
    if any(d in domain for d in disqualified):
        return False

    # Reject non-product junk/lead paths
    junk_paths = [
        "/webinar", "/course", "/login", "/terms", "/privacy", "/policy"
    ]
    if any(j in path for j in junk_paths):
        return False

    return True


class MetaAdInterceptor:
    """
    Captures internal Meta GraphQL and Relay SSR responses without OAuth tokens or official API rate limits.
    """

    def __init__(self):
        self.base_url = "https://www.facebook.com/ads/library/"

    def _clean_and_parse_json(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        Strips Meta security prefixes ('for (;;);') and extracts valid JSON blocks
        from single payloads or chunked streaming responses.
        """
        payloads = []
        cleaned = raw_text.replace("for (;;);", "").strip()

        # Try standard JSON parsing
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

        # Split newline-delimited JSON chunks (Meta GraphQL streaming)
        for line in cleaned.splitlines():
            line = line.strip()
            if not line or not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return payloads

    def extract_structured_ads(self, raw_payloads: List[Dict[str, Any]], min_days_active: int = 5) -> List[Dict[str, Any]]:
        """
        Parses internal Meta GraphQL structures to extract clean, actionable ad cards.
        Enforces longevity detection, direct video/image extraction, and scaling density detection.
        """
        extracted_ads = []
        seen_ad_ids = set()
        now = datetime.now(timezone.utc)

        for blob in raw_payloads:
            connections = find_nodes_by_key(blob, "search_results_connection")
            for conn in connections:
                edges = conn.get("edges", [])
                for edge in edges:
                    node = edge.get("node", {}) if isinstance(edge, dict) else {}
                    collated = node.get("collated_results", [node])
                    for item in collated:
                        if not isinstance(item, dict):
                            continue
                        ad_archive_id = item.get("ad_archive_id") or item.get("archive_id")
                        if not ad_archive_id or str(ad_archive_id) in seen_ad_ids:
                            continue

                        # Calculate days active from start_date timestamp
                        start_date_ts = item.get("start_date") or item.get("creation_time") or item.get("startDate")
                        days_active = 0
                        start_dt = None
                        if start_date_ts:
                            try:
                                ts_val = int(start_date_ts)
                                if ts_val > 100000000000:
                                    ts_val = ts_val // 1000
                                start_dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                                days_active = max(0, (now - start_dt).days)
                            except Exception:
                                pass

                        # Filter: accept ads running >= min_days_active
                        if days_active < min_days_active:
                            continue

                        snapshot = item.get("snapshot", {}) or {}

                        # Extract raw .mp4 video URL
                        videos = snapshot.get("videos", []) or []
                        cards = snapshot.get("cards", []) or []
                        raw_video_url = None
                        if videos and isinstance(videos, list):
                            for v in videos:
                                if isinstance(v, dict):
                                    raw_video_url = v.get("video_hd_url") or v.get("video_sd_url")
                                    if raw_video_url:
                                        break
                        if not raw_video_url and cards:
                            for c in cards:
                                if isinstance(c, dict):
                                    raw_video_url = c.get("video_hd_url") or c.get("video_sd_url")
                                    if raw_video_url:
                                        break

                        # Extract high-res image fallback
                        images = snapshot.get("images", []) or []
                        raw_image_url = None
                        if images and isinstance(images, list) and isinstance(images[0], dict):
                            raw_image_url = images[0].get("original_image_url") or images[0].get("resized_image_url")
                        if not raw_image_url and cards and isinstance(cards, list) and isinstance(cards[0], dict):
                            raw_image_url = cards[0].get("original_image_url") or cards[0].get("resized_image_url")

                        # Extract merchant landing page
                        cta_link = snapshot.get("link_url")
                        if not cta_link and cards and isinstance(cards, list) and isinstance(cards[0], dict):
                            cta_link = cards[0].get("link_url")

                        # Anti-Noise Landing Page Gate
                        if cta_link and not is_valid_ecommerce_landing_page(cta_link):
                            continue

                        page_name = snapshot.get("page_name") or item.get("page_name", "Unknown Brand")
                        body_obj = snapshot.get("body", {}) or {}
                        body_text = body_obj.get("text", "") if isinstance(body_obj, dict) else str(body_obj)
                        raw_title = snapshot.get("title") or ""

                        ad_entry = {
                            "ad_id": str(ad_archive_id),
                            "page_name": str(page_name),
                            "days_active": max(days_active, 1),
                            "start_dt": start_dt,
                            "raw_title": raw_title,
                            "body_text": body_text,
                            "cta_destination_url": cta_link,
                            "raw_video_url": raw_video_url,
                            "raw_image_url": raw_image_url,
                            "ad_library_permalink": f"https://www.facebook.com/ads/library/?id={ad_archive_id}",
                            "is_video": bool(raw_video_url),
                            "snapshot": snapshot,
                        }

                        seen_ad_ids.add(str(ad_archive_id))
                        extracted_ads.append(ad_entry)

        # Ad Scaling Density & Longevity Detector: Group ads by page_name
        page_counts: Dict[str, int] = {}
        for ad in extracted_ads:
            p = ad["page_name"].lower().strip()
            page_counts[p] = page_counts.get(p, 0) + 1

        for ad in extracted_ads:
            p = ad["page_name"].lower().strip()
            cnt = page_counts.get(p, 1)
            ad["creative_variations_count"] = cnt
            ad["is_confirmed_scaling"] = (cnt >= 3) or (ad["days_active"] >= 8)

        return extracted_ads

    async def intercept_meta_network(
        self, page, keyword: str, country: str = "US", min_days_active: int = 5
    ) -> List[Dict[str, Any]]:
        captured_payloads: List[Dict[str, Any]] = []

        async def handle_response(response):
            try:
                # Pre-filter before touching headers or body
                if "graphql" not in response.url and "ads/library" not in response.url:
                    return

                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type or "text/javascript" in content_type:
                    body = await response.text()
                    if "search_results_connection" in body or "collated_results" in body or "ad_archive_id" in body:
                        parsed_list = self._clean_and_parse_json(body)
                        captured_payloads.extend(parsed_list)
            except Exception as e:
                logger.debug(f"[MetaInterceptor] Parsing frame skipped: {e}")

        # Attach response listener
        page.on("response", handle_response)

        # Warm up session with root domain to acquire valid session cookies and avoid 403
        try:
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=12000)
            await asyncio.sleep(1.0)
        except Exception:
            pass

        encoded_keyword = urllib.parse.quote_plus(keyword)
        target_url = (
            f"{self.base_url}?active_status=active&ad_type=all"
            f"&country={country}&q={encoded_keyword}&sort_data[direction]=desc&sort_data[mode]=relevancy_monthly_grouped"
        )

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)

            try:
                await page.wait_for_selector("div[role='main']", timeout=8000)
            except Exception:
                pass

            # Scroll in increments to trigger pagination
            for _ in range(3):
                await page.mouse.wheel(0, 1800)
                await asyncio.sleep(1.2)

            await asyncio.sleep(1.5)

            # Extract from HTML script tags (where Meta embeds the initial Relay SSR payload)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script"):
                raw_text = script.get_text()
                if "search_results_connection" in raw_text or "collated_results" in raw_text:
                    parsed_list = self._clean_and_parse_json(raw_text)
                    captured_payloads.extend(parsed_list)

        finally:
            page.remove_listener("response", handle_response)

        structured_ads = self.extract_structured_ads(captured_payloads, min_days_active=min_days_active)
        return structured_ads

    async def discover_viral_products(
        self, page, country: str = "IN", min_days_active: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Discovers active viral dropshipping/D2C products running in the specified country
        using randomized high-intent e-commerce seed footprints.
        """
        country_code = country.upper()
        seeds = COUNTRY_VIRAL_FOOTPRINTS.get(country_code, COUNTRY_VIRAL_FOOTPRINTS["IN"])
        seed_phrase = random.choice(seeds)
        logger.info(f"[Meta Viral Discovery] Scanning country={country_code} with viral seed: '{seed_phrase}'")
        return await self.intercept_meta_network(
            page=page,
            keyword=seed_phrase,
            country=country_code,
            min_days_active=min_days_active,
        )


meta_interceptor = MetaAdInterceptor()

async def intercept_meta_network(page, keyword: str, country: str = "US") -> List[Dict[str, Any]]:
    return await meta_interceptor.intercept_meta_network(page, keyword=keyword, country=country)

async def discover_viral_products(page, country: str = "IN", min_days_active: int = 5) -> List[Dict[str, Any]]:
    return await meta_interceptor.discover_viral_products(page, country=country, min_days_active=min_days_active)


# ======================================================================================
# Core Reverse-Engineered Network Scanner
# ======================================================================================

class ReverseNetworkScanner:
    """
    Zero-auth, zero-DOM network scanner capturing internal frontend JSON microservices.
    """

    def __init__(self):
        self.meta_base_url = "https://www.facebook.com/ads/library/"
        self.meesho_search_url = "https://www.meesho.com/search"
        self.interceptor = meta_interceptor

    # ----------------------------------------------------------------------------------
    # 1. Reverse Engineering Meta Ad Library (Internal GraphQL & Relay SSR Payloads)
    # ----------------------------------------------------------------------------------

    async def scan_meta_ads(
        self,
        keyword: Optional[str] = None,
        country: str = "IN",
        min_days: int = 5,
        limit: int = 20,
    ) -> List[ScrapedAd]:
        """
        Intercepts Meta Ad Library unauthenticated internal GraphQL and Relay preloader
        JSON payloads. If keyword is None or 'viral', triggers automated viral discovery footprints.
        """
        country_code = country.upper()
        is_viral_mode = not keyword or keyword.strip().lower() in ["viral", "current viral", "scrape viral", "all"]
        log_term = f"Viral Discovery ({country_code})" if is_viral_mode else f"'{keyword}' ({country_code})"
        logger.info(f"[Meta Reverse] Intercepting internal traffic for {log_term}...")

        try:
            context = await browser_manager.create_stealth_context()
            page = await browser_manager.create_stealth_page(context)
        except Exception as exc:
            logger.warning(f"[Meta Reverse] Could not launch browser: {exc}")
            return []

        try:
            if is_viral_mode:
                raw_ads = await self.interceptor.discover_viral_products(
                    page=page,
                    country=country_code,
                    min_days_active=min_days,
                )
            else:
                raw_ads = await self.interceptor.intercept_meta_network(
                    page=page,
                    keyword=keyword,
                    country=country_code,
                    min_days_active=min_days,
                )
        except Exception as exc:
            logger.error(f"[Meta Reverse] Exception during network interception: {exc}")
            raw_ads = []
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

        extracted_ads: List[ScrapedAd] = []
        for raw in raw_ads:
            clean_title = sanitize_text(raw.get("raw_title", ""))
            page_name = raw.get("page_name", "")
            if not clean_title or ("." in clean_title and len(clean_title.split()) <= 2):
                if page_name and not is_viral_mode and keyword:
                    product_name = f"{page_name.strip()} - {keyword.strip().title()}"
                elif page_name:
                    product_name = page_name.strip()
                elif not is_viral_mode and keyword:
                    product_name = keyword.strip().title()
                else:
                    first_line = raw.get("body_text", "").split("\n")[0][:35].strip()
                    cleaned_line = sanitize_text(first_line).title()
                    product_name = cleaned_line if cleaned_line and len(cleaned_line) > 3 else "Viral Trending Product"
            else:
                product_name = clean_title.title()

            video_url = raw.get("raw_video_url")
            img_url = raw.get("raw_image_url")
            if not video_url and not img_url and "snapshot" in raw:
                video_url, img_url = media_extractor.extract_direct_urls_from_snapshot(raw["snapshot"])

            _, core_kws = extract_core_keywords(product_name, raw.get("body_text", ""))

            ad = ScrapedAd(
                ad_id=raw["ad_id"],
                source_country=country_code,
                started_date=raw.get("start_dt"),
                days_active=raw["days_active"],
                ad_title=raw.get("raw_title") or product_name,
                ad_body=raw.get("body_text", ""),
                landing_page_url=raw.get("cta_destination_url"),
                image_url=img_url,
                video_url=video_url,
                ad_library_url=raw["ad_library_permalink"],
                clean_product_name=product_name,
                core_keywords=core_kws,
                creative_variations_count=raw.get("creative_variations_count", 1),
                is_confirmed_scaling=raw.get("is_confirmed_scaling", False),
            )
            extracted_ads.append(ad)

        logger.info(
            f"[Meta Reverse] Extracted {len(extracted_ads)} ads running >= {min_days} days."
        )
        return extracted_ads[:limit]

    async def scrape_viral_products(
        self,
        keyword: Optional[str] = None,
        country: str = "US",
        min_days: int = 3,
        limit: int = 3,
    ) -> List[ScrapedAd]:
        """
        Directly discovers winning video ads from Meta Ad Library without strict margin discards.
        Prioritizes active video creatives with proven longevity and valid e-commerce storefronts.
        """
        is_viral = not keyword or keyword.strip().lower() in ["viral", "all", "trending"]
        search_kw = None if is_viral else keyword.strip()

        # Primary scan with min_days
        raw_ads = await self.scan_meta_ads(
            keyword=search_kw,
            country=country,
            min_days=min_days,
            limit=30,
        )

        # Fallback to 1-day threshold if initial scan yielded no ads
        if not raw_ads and min_days > 1:
            logger.info(f"[Meta Viral] No ads >= {min_days}d. Relaxing longevity filter to >= 1d...")
            raw_ads = await self.scan_meta_ads(
                keyword=search_kw,
                country=country,
                min_days=1,
                limit=30,
            )

        if not raw_ads:
            return []

        # Sort ads: prioritize video creatives, then longevity (days active)
        raw_ads.sort(key=lambda a: (bool(a.video_url), a.days_active), reverse=True)

        # Prefer ads that have video or image
        media_ads = [a for a in raw_ads if a.video_url or a.image_url]
        return media_ads[:limit] if media_ads else raw_ads[:limit]

    # ----------------------------------------------------------------------------------
    # 2. Reverse Engineering Meesho Public Search (Internal API & NEXT_DATA)
    # ----------------------------------------------------------------------------------

    async def scan_meesho_saturation(self, keyword: str) -> PlatformCompetition:
        """
        Intercepts Meesho's internal catalog search microservice:
        `https://www.meesho.com/api/v1/products/search`
        
        Zero HTML elements or CSS classes are inspected.
        """
        encoded_query = urllib.parse.quote_plus(keyword)
        target_url = f"{self.meesho_search_url}?q={encoded_query}"
        logger.info(f"[Meesho Reverse] Intercepting internal product microservice for: '{keyword}'...")

        intercepted_api_json: List[Dict[str, Any]] = []

        try:
            context = await browser_manager.create_stealth_context()
            page = await browser_manager.create_stealth_page(context)
        except Exception as exc:
            logger.warning(f"[Meesho Reverse] Could not launch browser: {exc}")
            return PlatformCompetition(platform="Meesho", listing_count=0)

        # Network Response Listener: Captures internal search microservice
        async def on_response(response):
            if "api/v1/products/search" in response.url:
                try:
                    data = await response.json()
                    intercepted_api_json.append(data)
                except Exception:
                    pass

        page.on("response", on_response)

        prices: List[float] = []
        catalog_items: List[Dict[str, Any]] = []
        total_count = 0

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT_MS)
            await asyncio.sleep(2.5)

            # --- Strategy A: Use Direct Intercepted API JSON ---
            if intercepted_api_json:
                api_payload = intercepted_api_json[0]
                catalog_items = api_payload.get("catalogs", [])
                total_count = api_payload.get("count", len(catalog_items))
                logger.info(f"[Meesho Reverse] Captured live API response ({len(catalog_items)} catalogs, count={total_count}).")

            # --- Strategy B: Fallback to Embedded __NEXT_DATA__ SSR Blob ---
            if not catalog_items:
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                next_data_script = soup.find("script", id="__NEXT_DATA__")
                if next_data_script and next_data_script.string:
                    data = json.loads(next_data_script.string)
                    # Traverse into initialState.searchListing
                    catalogs = find_nodes_by_key(data, "catalogs")
                    if catalogs and isinstance(catalogs[0], list):
                        catalog_items = catalogs[0]
                        total_count = len(catalog_items)
                        logger.info(f"[Meesho Reverse] Extracted from __NEXT_DATA__ ({len(catalog_items)} catalogs).")

        except Exception as exc:
            logger.error(f"[Meesho Reverse] Error intercepting search API: {exc}")
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

        # Enhancement 2: Meesho Search Fallback Detection (Token Overlap & Jaccard Check)
        # When Meesho has 0 results for a niche query, it returns unrelated popular items (clothes/watches).
        candidate_titles = [item.get("name", "") for item in catalog_items]
        is_fallback = is_meesho_algorithmic_fallback(keyword, candidate_titles, threshold=0.20)

        if is_fallback:
            logger.info(f"[Meesho] Algorithmic fallback detected (< 20% token overlap for '{keyword}'). Marking listing_count = 0 (True Virgin).")
            effective_listing_count = 0
            prices = []
        else:
            # Filter strictly to relevant items sharing >= 20% token overlap with the clean query
            relevant_items = [
                item for item in catalog_items
                if calculate_token_overlap(keyword, item.get("name", "")) >= 0.20
            ]
            effective_listing_count = len(relevant_items) if relevant_items else len(catalog_items)
            for item in (relevant_items or catalog_items):
                price = item.get("min_product_price") or item.get("min_catalog_price")
                if price and isinstance(price, (int, float)):
                    prices.append(float(price))

        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        avg_price = (sum(prices) / len(prices)) if prices else None

        # Build sample listing URLs from product slugs
        sample_urls = []
        for item in catalog_items[:3]:
            slug = item.get("slug")
            pid = item.get("id") or item.get("product_id")
            if slug:
                sample_urls.append(f"https://www.meesho.com/p/{slug}")
            elif pid:
                sample_urls.append(f"https://www.meesho.com/p/{pid}")

        return PlatformCompetition(
            platform="Meesho",
            listing_count=effective_listing_count,
            min_price_inr=min_price,
            max_price_inr=max_price,
            avg_price_inr=round(avg_price, 2) if avg_price else None,
            top_sellers=[],
            visually_matched_count=0,
            sample_listing_urls=sample_urls,
        )

    # ----------------------------------------------------------------------------------
    # 3. Arbitrage Pipeline Runner (Trend Ingestion + Meesho Saturation + Economics)
    # ----------------------------------------------------------------------------------

    async def scan_and_evaluate(
        self,
        keyword: Optional[str] = None,
        country: str = "IN",
        min_days: int = 5,
        limit: int = 5,
        send_telegram: bool = False,
        max_wholesale_inr: Optional[float] = None,
    ) -> List[OpportunityEvaluation]:
        """
        Executes complete reverse-engineered arbitrage scanning:
        - Ingests active winning ads (or triggers viral discovery) from Meta JSON.
        - Checks India saturation on Meesho via internal search API.
        - Evaluates unit economics (₹699 - ₹1,499 sweet spot), COD RTO risk, and 1688 wholesale.
        """
        # 1. Ingest winning ads
        ads = await self.scan_meta_ads(keyword=keyword, country=country, min_days=min_days, limit=limit)
        log_term = keyword or f"Viral Discovery ({country})"
        if not ads:
            logger.warning(f"No active ads found for {log_term} with >= {min_days} days running.")
            return []

        # Filter out already evaluated ads using the SQLite de-duplication cache
        fresh_ads = dedup_cache.filter_fresh_ads(ads)
        if not fresh_ads:
            logger.info(f"[Dedup Cache] All {len(ads)} ads for {log_term} were previously analyzed. Evaluating fresh subset or skipping.")
            # For interactive/custom search, if all were processed, take the top 1 to re-evaluate or use fresh_ads
            target_ads = ads[:limit]
        else:
            target_ads = fresh_ads[:limit]

        evaluations: List[OpportunityEvaluation] = []

        for ad in target_ads:
            # Enhancement 1: Core 2-3 word clean noun phrase search
            search_query = ad.core_keywords[0] if ad.core_keywords else ad.clean_product_name
            meesho_comp = await self.scan_meesho_saturation(search_query)

            # Saturation Tiering
            # VIRGIN (0-2 listings) | EARLY (3-8 listings) | SATURATED (> 8 listings)
            if meesho_comp.listing_count <= 2:
                tier = SaturationTier.VIRGIN
                summary = f"VIRGIN MARKET: Only {meesho_comp.listing_count} listings on Meesho. High first-mover advantage."
            elif meesho_comp.listing_count <= 8:
                tier = SaturationTier.EARLY
                summary = f"EARLY STAGE: {meesho_comp.listing_count} listings on Meesho. Healthy demand with low competition."
            else:
                tier = SaturationTier.SATURATED
                summary = f"SATURATED: {meesho_comp.listing_count} active listings found on Meesho. Market already discounted."

            saturation_report = SaturationReport(
                meesho=meesho_comp,
                amazon=PlatformCompetition(platform="Amazon.in", listing_count=0),
                india_meta_ads_count=0,
                india_meta_ad_urls=[],
                tier=tier,
                summary=summary,
            )

            # Economics & RTO Risk (using OpportunityAnalyzer with word-boundary matching)
            analyzer = OpportunityAnalyzer()
            rto_risk, rto_reasons = analyzer.detect_rto_risk(ad.ad_title, ad.ad_body, ad.core_keywords)

            # Recommended Price (Sweet Spot: ₹699 - ₹1,499)
            comp_price = meesho_comp.avg_price_inr or 899.0
            target_price = min(max(comp_price * 1.15, settings.MIN_TARGET_PRICE_INR), settings.MAX_TARGET_PRICE_INR)
            target_price = round(target_price, 0)

            # Global Sourcing & Factory Benchmark (1688 / YiwuGo / IndiaMART)
            sourcing_info = await sourcing_benchmarker.benchmark_product_sourcing(
                clean_keyword=search_query,
                target_selling_price_inr=target_price,
                max_wholesale_inr=max_wholesale_inr,
            )

            # Sourcing landed cost in India
            est_source = sourcing_info.est_landed_cost_inr
            est_ship = 90.0
            est_cpa = 260.0
            est_rto = 110.0 if rto_risk == RTORiskLevel.HIGH else (60.0 if rto_risk == RTORiskLevel.MEDIUM else 35.0)
            net_profit = target_price - (est_source + est_ship + est_cpa + est_rto)
            margin_pct = round((net_profit / target_price) * 100, 2) if target_price > 0 else 0.0

            economics = UnitEconomics(
                est_source_cost_inr=est_source,
                est_shipping_inr=est_ship,
                est_marketing_cpa_inr=est_cpa,
                est_rto_allowance_inr=est_rto,
                recommended_selling_price_inr=target_price,
                est_net_margin_percentage=margin_pct,
                rto_risk=rto_risk,
                rto_reasons=rto_reasons,
                in_sweet_spot=settings.MIN_TARGET_PRICE_INR <= target_price <= settings.MAX_TARGET_PRICE_INR,
            )

            # Arbitrage Score (0-100)
            score = 0.0
            score += 35.0 if ad.days_active >= 30 else (25.0 if ad.days_active >= 14 else 15.0)
            score += 40.0 if tier == SaturationTier.VIRGIN else (20.0 if tier == SaturationTier.EARLY else 0.0)
            score += 15.0 if economics.in_sweet_spot else 5.0
            score += 10.0 if margin_pct >= 25.0 else 5.0
            if rto_risk == RTORiskLevel.HIGH:
                score -= 20.0
            elif rto_risk == RTORiskLevel.MEDIUM:
                score -= 8.0

            final_score = max(0.0, min(100.0, round(score, 1)))

            # Viability Rule:
            # 1. Not SATURATED
            # 2. Score >= 65
            # 3. Not HIGH RTO risk
            # 4. Gross Margin >= 60% (Discard if < 60% as CAC + COD RTO eats the remaining margin)
            is_qualified = (
                tier != SaturationTier.SATURATED and
                final_score >= 65.0 and
                rto_risk != RTORiskLevel.HIGH and
                sourcing_info.is_viable_margin
            )

            eval_notes = [
                f"Longevity: {ad.days_active}d",
                f"Meesho Listings: {meesho_comp.listing_count}",
                f"Gross Sourcing Margin: {sourcing_info.gross_margin_pct}%"
            ]
            if not sourcing_info.is_viable_margin:
                if max_wholesale_inr and sourcing_info.est_landed_cost_inr > max_wholesale_inr:
                    eval_notes.append(f"DISCARD: Landed Cost (₹{sourcing_info.est_landed_cost_inr:,.0f}) > Wholesale Cap (₹{max_wholesale_inr:,.0f})")
                else:
                    eval_notes.append(f"DISCARD: Gross Margin ({sourcing_info.gross_margin_pct}%) < 60% threshold")

            ev = OpportunityEvaluation(
                ad=ad,
                saturation=saturation_report,
                economics=economics,
                sourcing=sourcing_info,
                arbitrage_score=final_score,
                qualified=is_qualified,
                evaluation_notes=eval_notes,
            )
            evaluations.append(ev)

            # Enhancement 4: Record into SQLite de-duplication cache
            dedup_cache.record_ad(
                ad_id=ad.ad_id,
                product_name=ad.clean_product_name,
                days_active=ad.days_active,
                score=final_score,
                qualified=is_qualified
            )

            # Dispatch to Telegram if qualified or forced
            if (is_qualified or send_telegram) and settings.is_telegram_configured:
                telegram_dispatcher = TelegramDispatcher()
                await telegram_dispatcher.send_alert(ev)

        return evaluations


# ======================================================================================
# CLI Runner & Pretty Table Output
# ======================================================================================

def render_rich_results(evaluations: List[OpportunityEvaluation]) -> None:
    """Renders formatted evaluation table."""
    table = Table(
        title="⚡ REVERSE-ENGINEERED ARBITRAGE SCANNER (INTERNAL CLIENT PAYLOADS)",
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )

    table.add_column("Product", style="bold white", width=24)
    table.add_column("US Days", justify="center", width=8)
    table.add_column("Meesho", justify="center", width=8)
    table.add_column("Landed Cost", justify="right", width=12)
    table.add_column("Target", justify="right", width=10)
    table.add_column("Gross %", justify="right", width=9)
    table.add_column("RTO Risk", justify="center", width=9)
    table.add_column("Score", justify="center", width=7)
    table.add_column("Status", justify="center", width=13)

    for ev in evaluations:
        ad = ev.ad
        sat = ev.saturation
        eco = ev.economics
        src = ev.sourcing

        status_style = "bold green" if ev.qualified else "dim red"
        status_text = "QUALIFIED" if ev.qualified else "DISCARDED"
        landed_str = f"₹{src.est_landed_cost_inr:,.0f}" if src else f"₹{eco.est_source_cost_inr:,.0f}"
        gross_str = f"{src.gross_margin_pct:.1f}%" if src else f"{eco.est_net_margin_percentage:.1f}%"

        table.add_row(
            ad.clean_product_name[:23],
            f"{ad.days_active}d",
            str(sat.meesho.listing_count),
            landed_str,
            f"₹{eco.recommended_selling_price_inr:,.0f}",
            gross_str,
            eco.rto_risk.value,
            f"{ev.arbitrage_score:.1f}",
            f"[{status_style}]{status_text}[/{status_style}]",
        )

    console.print(table)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Reverse-Engineered Network Scanner for Trend Arbitrage")
    parser.add_argument("--keyword", type=str, default=None, help="Product keyword (omit for automated viral discovery)")
    parser.add_argument("--country", type=str, default="IN", choices=["IN", "US", "AE", "GB"], help="Target market: IN, US, AE, GB (default: IN)")
    parser.add_argument("--min-days", type=int, default=5, help="Minimum active running days (default: 5)")
    parser.add_argument("--limit", type=int, default=5, help="Maximum ads to evaluate")
    parser.add_argument("--max-wholesale", type=float, default=None, help="Max Landed/Wholesale price ceiling in INR (e.g. 250)")
    parser.add_argument("--telegram", action="store_true", help="Force send opportunity alerts to Telegram")
    args = parser.parse_args()

    scanner = ReverseNetworkScanner()
    try:
        results = await scanner.scan_and_evaluate(
            keyword=args.keyword,
            country=args.country,
            min_days=args.min_days,
            limit=args.limit,
            send_telegram=args.telegram,
            max_wholesale_inr=args.max_wholesale,
        )
        if results:
            render_rich_results(results)
        else:
            console.print("[yellow]No qualified opportunities met the criteria.[/yellow]")
    finally:
        await browser_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
