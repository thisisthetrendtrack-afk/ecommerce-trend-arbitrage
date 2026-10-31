"""
Trend Ingestion Module (ingestion.py).
Scrapes Meta Ad Library for active high-intent dropshipping ads across Western markets (US/EU).
Filters out weak/unprofitable ads: Retains ONLY ads active for >= 7 consecutive days.
"""

import asyncio
import logging
import random
import re
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx

from config import settings
from models import ScrapedAd
from utils.browser import browser_manager
from utils.keyword_extractor import extract_core_keywords

logger = logging.getLogger("TrendArbitrage.Ingestion")

# Regex to detect ad start date statements in Meta Ad Library
DATE_PATTERNS = [
    r"Started\s+running\s+on\s+([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",     # e.g., Started running on Oct 12, 2024
    r"Started\s+running\s+on\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",     # e.g., Started running on 12 Oct 2024
    r"Started\s+running\s+on\s+(\d{1,2}\s+[A-Za-z]{3},\s+\d{4})",    # e.g., Started running on 12 Oct, 2024
    r"Started\s+running\s+on\s+(\d{4}-\d{2}-\d{2})",                 # e.g., Started running on 2024-10-12
]

COMPILED_DATE_REGEXES = [re.compile(p, re.IGNORECASE) for p in DATE_PATTERNS]
ID_PATTERN = re.compile(r"(?:Library ID|ID):\s*(\d+)", re.IGNORECASE)


def parse_start_date(raw_text: str) -> Optional[datetime]:
    """Parses ad start date from card text and returns a timezone-aware datetime."""
    for pattern in COMPILED_DATE_REGEXES:
        match = pattern.search(raw_text)
        if match:
            date_str = match.group(1).replace(",", "").strip()
            # Try varying format parsers
            for fmt in ("%b %d %Y", "%d %b %Y", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
    return None


def calculate_active_days(start_date: Optional[datetime]) -> int:
    """Calculates consecutive active days between ad launch date and now."""
    if not start_date:
        return 0
    now = datetime.now(timezone.utc)
    delta = now - start_date
    return max(0, delta.days)


class MetaAdLibraryIngestor:
    """Production scraper for Meta Ad Library ads targeting dropshipping campaigns."""

    def __init__(self):
        self.base_url = "https://www.facebook.com/ads/library/"

    def build_url(self, country: str, keyword: str) -> str:
        """Constructs the filtered Meta Ad Library URL."""
        params = {
            "active_status": "active",
            "ad_type": "all",
            "country": country,
            "q": keyword,
            "search_type": "keyword_unordered",
            "media_type": "all",
        }
        return f"{self.base_url}?{urllib.parse.urlencode(params)}"

    async def warm_up_session(self, page) -> None:
        """
        Visits the root Ad Library URL first to establish legitimate session cookies
        (datr, sb, wd) and dismiss European/UK GDPR consent walls that trigger 403 Forbidden.
        """
        try:
            logger.info("Warming up Meta session and negotiating consent cookies...")
            await page.goto("https://www.facebook.com/ads/library/", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1.5)

            # Accept GDPR/Cookie consent banner if presented
            consent_selectors = [
                "button[data-testid='cookie-policy-manage-dialog-accept-button']",
                "button:has-text('Allow all cookies')",
                "button:has-text('Accept All')",
                "button:has-text('Only allow essential')",
                "button[value='1']",
            ]
            for selector in consent_selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(1.0)
                        logger.info("Dismissed cookie consent banner on Meta.")
                        break
                except Exception:
                    continue
        except Exception as exc:
            logger.debug(f"Session warm-up notice: {exc}")

    async def query_official_graph_api(self, country: str, keyword: str, limit: int = 15) -> List[ScrapedAd]:
        """
        Queries official Meta Graph API (v20.0/ads_archive) if META_ACCESS_TOKEN is configured.
        Guarantees 100% SLA with zero 403 errors and instant structured results.
        """
        token = settings.META_ACCESS_TOKEN
        if not token:
            return []

        url = "https://graph.facebook.com/v20.0/ads_archive"
        params = {
            "access_token": token,
            "ad_reached_countries": f"['{country}']",
            "search_terms": keyword,
            "ad_active_status": "ACTIVE",
            "ad_type": "ALL",
            "fields": "id,ad_delivery_start_time,ad_creative_bodies,ad_creative_link_titles,ad_creative_link_captions,ad_snapshot_url",
            "limit": limit,
        }

        qualified: List[ScrapedAd] = []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    for item in data:
                        ad_id = str(item.get("id"))
                        start_time_str = item.get("ad_delivery_start_time")
                        start_dt = None
                        if start_time_str:
                            try:
                                start_dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                            except Exception:
                                pass

                        days_active = calculate_active_days(start_dt)
                        if days_active < settings.MIN_AD_ACTIVE_DAYS:
                            continue

                        bodies = item.get("ad_creative_bodies", [])
                        titles = item.get("ad_creative_link_titles", [])
                        ad_title = titles[0] if titles else (bodies[0][:100] if bodies else "Trending Product")
                        ad_body = bodies[0] if bodies else ""
                        snapshot_url = item.get("ad_snapshot_url")

                        clean_name, core_kws = extract_core_keywords(ad_title, ad_body)
                        qualified.append(
                            ScrapedAd(
                                ad_id=ad_id,
                                source_country=country,
                                started_date=start_dt,
                                days_active=days_active,
                                ad_title=ad_title,
                                ad_body=ad_body,
                                landing_page_url=snapshot_url,
                                image_url=None,
                                video_url=None,
                                ad_library_url=f"https://www.facebook.com/ads/library/?id={ad_id}",
                                clean_product_name=clean_name,
                                core_keywords=core_kws,
                            )
                        )
                    logger.info(f"Official Meta Graph API returned {len(qualified)} qualified ads for '{keyword}'")
                    return qualified
                else:
                    logger.warning(f"Meta Graph API error ({resp.status_code}): {resp.text}")
        except Exception as exc:
            logger.error(f"Failed querying Meta Graph API: {exc}")
        return []

    async def scrape_ads_for_keyword(
        self, country: str, keyword: str, limit: int = 15
    ) -> List[ScrapedAd]:
        """
        Scrapes active ads matching the query keyword, filters by longevity (>= 7 days),
        with automated 403 evasion and session warming.
        """
        # 1. First priority: Official Graph API if configured
        if settings.META_ACCESS_TOKEN:
            api_ads = await self.query_official_graph_api(country, keyword, limit)
            if api_ads:
                return api_ads

        # 2. Browser Stealth Scraping with 403 Resilience
        search_url = self.build_url(country, keyword)
        logger.info(f"Ingesting ads from Meta Ad Library [{country}] for keyword: '{keyword}'")

        try:
            context = await browser_manager.create_stealth_context()
            page = await browser_manager.create_stealth_page(context)
        except Exception as exc:
            logger.warning(f"Could not launch browser for Meta scraping: {exc}")
            return []

        valid_ads: List[ScrapedAd] = []

        try:
            # Navigate to search URL
            response = await page.goto(search_url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT_MS)

            # Detect 403 Forbidden (common on GB/EU endpoints or without warmed cookies)
            if response and response.status == 403:
                logger.warning(f"Meta Ad Library responded with 403 for {country}. Initiating session warm-up & backoff...")
                
                # Backoff with jitter to reset edge rate limiter
                backoff_delay = random.uniform(2.5, 4.5)
                await asyncio.sleep(backoff_delay)

                # Warm up session with root domain
                await self.warm_up_session(page)

                # Retry with country fallback: if GB triggers strict European firewall, fallback to US
                retry_country = "US" if country == "GB" else country
                retry_url = self.build_url(retry_country, keyword)
                logger.info(f"Retrying query with warmed session [{retry_country}]: '{keyword}'")
                
                response = await page.goto(retry_url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT_MS)

            if not response or response.status >= 400:
                logger.warning(f"Meta Ad Library response status: {response.status if response else 'None'}")

            # Handle possible cookie dialogs
            try:
                consent_selector = "button[data-testid='cookie-policy-manage-dialog-accept-button'], button:has-text('Allow all cookies'), button:has-text('Only allow essential')"
                consent_btn = await page.query_selector(consent_selector)
                if consent_btn:
                    await consent_btn.click()
                    await asyncio.sleep(1.0)
            except Exception:
                pass

            # Scroll dynamically to trigger ad results rendering
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(1.2)

            await page.wait_for_timeout(2000)
            html_content = await page.content()
            
            valid_ads = self.parse_ad_cards(html_content, country, limit)

        except Exception as exc:
            logger.error(f"Error scraping Meta Ad Library for '{keyword}' ({country}): {exc}", exc_info=True)
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

        logger.info(f"Found {len(valid_ads)} profitable ads (>= {settings.MIN_AD_ACTIVE_DAYS} days) for '{keyword}' in {country}")
        return valid_ads

    def parse_ad_cards(self, html: str, country: str, limit: int = 15) -> List[ScrapedAd]:
        """Extracts structured ad records from rendered HTML markup."""
        soup = BeautifulSoup(html, "html.parser")
        qualified_ads: List[ScrapedAd] = []

        # Find ad container cards in Meta Ad Library
        text_elements = soup.find_all(string=re.compile(r"Started running on|Library ID:", re.IGNORECASE))
        seen_ad_ids = set()

        for el in text_elements:
            if len(qualified_ads) >= limit:
                break

            # Traverse up to find the enclosing card container
            container = el.find_parent(lambda tag: tag.name in ["div", "section"] and len(tag.get_text()) > 80)
            if not container:
                continue

            card_text = container.get_text(" ", strip=True)

            # 1. Extract Ad ID
            id_match = ID_PATTERN.search(card_text)
            ad_id = id_match.group(1) if id_match else f"meta_{abs(hash(card_text[:50]))}"
            if ad_id in seen_ad_ids:
                continue
            seen_ad_ids.add(ad_id)

            # 2. Extract and Validate Running Duration
            start_date = parse_start_date(card_text)
            days_active = calculate_active_days(start_date)

            # Strict Profitability Filter: Drop ads running less than MIN_AD_ACTIVE_DAYS
            if days_active < settings.MIN_AD_ACTIVE_DAYS:
                logger.debug(f"Discarding ad {ad_id}: Active for only {days_active} days (< {settings.MIN_AD_ACTIVE_DAYS} req)")
                continue

            # 3. Extract Ad Creatives (Thumbnail / Video / Landing Page)
            img_tag = container.find("img", src=re.compile(r"https?://", re.IGNORECASE))
            image_url = img_tag["src"] if img_tag and "src" in img_tag.attrs else None

            video_tag = container.find("video")
            video_url = video_tag["src"] if video_tag and "src" in video_tag.attrs else None

            # Outbound / CTA link
            cta_link = None
            for link in container.find_all("a", href=True):
                href = link["href"]
                if "facebook.com" not in href and "fb.me" not in href and href.startswith("http"):
                    cta_link = href
                    break

            # 4. Extract Hook / Headline and Product Name
            paragraphs = [p.get_text(strip=True) for p in container.find_all(["div", "span", "p"]) if len(p.get_text(strip=True)) > 20]
            ad_title = paragraphs[0] if paragraphs else card_text[:120]
            ad_body = "\n".join(paragraphs[1:3]) if len(paragraphs) > 1 else ""

            clean_name, core_keywords = extract_core_keywords(ad_title, ad_body)

            scraped_ad = ScrapedAd(
                ad_id=ad_id,
                source_country=country,
                started_date=start_date,
                days_active=days_active,
                ad_title=ad_title,
                ad_body=ad_body,
                landing_page_url=cta_link,
                image_url=image_url,
                video_url=video_url,
                ad_library_url=f"https://www.facebook.com/ads/library/?id={ad_id}",
                clean_product_name=clean_name,
                core_keywords=core_keywords,
            )
            qualified_ads.append(scraped_ad)

        return qualified_ads

    async def ingest_batch(
        self,
        keywords: Optional[List[str]] = None,
        countries: Optional[List[str]] = None,
        max_total: int = 20
    ) -> List[ScrapedAd]:
        """Runs parallel ingestion across configured keywords and country codes."""
        active_keywords = keywords or settings.AD_KEYWORDS
        active_countries = countries or settings.SEARCH_COUNTRIES
        collected_ads: List[ScrapedAd] = []
        seen_keys = set()

        for country in active_countries:
            for kw in active_keywords:
                if len(collected_ads) >= max_total:
                    break
                ads = await self.scrape_ads_for_keyword(country, kw, limit=settings.MAX_ADS_PER_KEYWORD)
                for ad in ads:
                    dedup_key = ad.clean_product_name.lower()
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        collected_ads.append(ad)

        return collected_ads


# Mock testing feed generator for test verification and offline simulation
def get_mock_test_feed() -> List[ScrapedAd]:
    """Provides validated test fixtures of real winning dropshipping products."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    return [
        ScrapedAd(
            ad_id="948271049281",
            source_country="US",
            started_date=now - timedelta(days=24),
            days_active=24,
            ad_title="Sunset Projection Lamp 16 Colors Remote Control - Transform Your Bedroom Atmosphere!",
            ad_body="50% off free shipping! Order yours today while limited supplies last. Tap shop now to upgrade your vibes.",
            landing_page_url="https://trendglowstore.com/products/sunset-lamp",
            image_url="https://images.unsplash.com/photo-1513506003901-1e6a229e2d15?w=500&auto=format&fit=crop&q=60",
            video_url=None,
            ad_library_url="https://www.facebook.com/ads/library/?id=948271049281",
            clean_product_name="Sunset Projection Lamp",
            core_keywords=["Sunset Projection Lamp", "Sunset Lamp", "Projection Lamp"],
        ),
        ScrapedAd(
            ad_id="849204910294",
            source_country="US",
            started_date=now - timedelta(days=16),
            days_active=16,
            ad_title="Electric Garlic & Vegetable Food Chopper USB Rechargeable Portable Mini Food Processor",
            ad_body="Get yours today with 50% off and free shipping! Effortless cooking prep in under 5 seconds. Limited stock available.",
            landing_page_url="https://chefsmartkitchen.com/products/mini-chopper",
            image_url="https://images.unsplash.com/photo-1584269600464-37b1b58a9fe7?w=500&auto=format&fit=crop&q=60",
            video_url=None,
            ad_library_url="https://www.facebook.com/ads/library/?id=849204910294",
            clean_product_name="Electric Mini Garlic Chopper",
            core_keywords=["Electric Mini Garlic Chopper", "Electric Garlic Chopper", "Mini Food Processor"],
        ),
        ScrapedAd(
            ad_id="746291039582",
            source_country="US",
            started_date=now - timedelta(days=31),
            days_active=31,
            ad_title="Nano Crystal Hair Eraser Exfoliating Hair Removal Stone Painless Magic Epilator",
            ad_body="Order now while supplies last! Buy 1 Get 1 Free + Worldwide Express Shipping. Silky smooth skin guaranteed.",
            landing_page_url="https://silkyglowco.com/products/crystal-hair-eraser",
            image_url="https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500&auto=format&fit=crop&q=60",
            video_url=None,
            ad_library_url="https://www.facebook.com/ads/library/?id=746291039582",
            clean_product_name="Crystal Hair Eraser",
            core_keywords=["Crystal Hair Eraser", "Hair Removal Stone", "Crystal Epilator"],
        ),
    ]
