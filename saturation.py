"""
India Saturation & Competition Checker (saturation.py).
Cross-verifies products on Meesho, Amazon.in, and India Meta Ad Library.
Applies visual similarity fallback (pHash/dHash) and categorizes products into Saturation Tiers:
VIRGIN, EARLY, or SATURATED.
"""

import asyncio
import logging
import re
import urllib.parse
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
import httpx

from config import settings
from models import PlatformCompetition, SaturationReport, SaturationTier, ScrapedAd
from utils.browser import browser_manager
from utils.image_matcher import check_visual_saturation_matches
from utils.keyword_extractor import calculate_token_overlap, is_meesho_algorithmic_fallback

logger = logging.getLogger("TrendArbitrage.Saturation")

PRICE_REGEX = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9,]+)", re.IGNORECASE)


def parse_inr_price(text: str) -> Optional[float]:
    """Extracts numeric INR price value from raw display text."""
    if not text:
        return None
    match = PRICE_REGEX.search(text)
    if match:
        clean_num = match.group(1).replace(",", "")
        try:
            return float(clean_num)
        except ValueError:
            return None
    return None


class SaturationChecker:
    """Orchestrates competition discovery and market saturation analysis across India."""

    def __init__(self):
        self.http_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        }

    async def check_meesho(
        self,
        product_name: str,
        query: str,
        thumbnail_url: Optional[str]
    ) -> PlatformCompetition:
        """
        Scrapes Meesho search results for listing count, price brackets, and visual similarity.
        Applies algorithmic fallback detection (detects unrelated popular items on 0-result queries).
        """
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.meesho.com/search?q={encoded_query}"
        logger.info(f"Checking Meesho saturation for: '{query}'")

        prices: List[float] = []
        candidate_images: List[str] = []
        listing_urls: List[str] = []
        candidate_titles: List[str] = []
        sellers: List[str] = []
        listing_count = 0

        try:
            context = await browser_manager.create_stealth_context()
            page = await browser_manager.create_stealth_page(context)
        except Exception as exc:
            logger.warning(f"Could not launch browser for Meesho check: {exc}")
            return PlatformCompetition(platform="Meesho", listing_count=0)

        try:
            resp = await page.goto(search_url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT_MS)
            await asyncio.sleep(1.5)

            # Wait for product grid elements or no-results message
            try:
                await page.wait_for_selector("div[class*='ProductList'], div[class*='Card'], div[data-testid]", timeout=5000)
            except Exception:
                pass

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Check for explicit "No results found"
            no_results = soup.find(string=re.compile(r"no results found|we couldn't find any matches", re.IGNORECASE))
            if no_results:
                listing_count = 0
            else:
                # Find product cards
                product_cards = soup.find_all("a", href=re.compile(r"/p/"))
                if not product_cards:
                    product_cards = soup.find_all("div", class_=re.compile(r"ProductCard|Card__BaseCard", re.IGNORECASE))

                for card in product_cards[:12]:
                    # Extract title / name from card
                    title_elem = card.find(["span", "p", "h2", "h3"], string=True) or card
                    card_title = title_elem.get_text(" ", strip=True) if title_elem else ""
                    if card_title:
                        candidate_titles.append(card_title)

                    card_text = card.get_text(" ", strip=True)
                    price_val = parse_inr_price(card_text)
                    if price_val:
                        prices.append(price_val)

                    # Extract product image URL
                    img_tag = card.find("img", src=True)
                    if img_tag and img_tag["src"].startswith("http"):
                        candidate_images.append(img_tag["src"])

                    # Extract relative or absolute listing URL
                    if card.name == "a" and "href" in card.attrs:
                        href = card["href"]
                        full_url = href if href.startswith("http") else f"https://www.meesho.com{href}"
                        listing_urls.append(full_url)

                # Algorithmic Fallback Detection: Meesho returns sarees/watches on 0-result niche queries
                if is_meesho_algorithmic_fallback(query, candidate_titles, threshold=0.20):
                    logger.info(f"Meesho algorithmic fallback detected for '{query}' (<20% overlap). Marking 0 listings (True Virgin).")
                    listing_count = 0
                    prices = []
                    listing_urls = []
                else:
                    relevant_titles = [
                        t for t in candidate_titles
                        if calculate_token_overlap(query, t) >= 0.20
                    ]
                    listing_count = len(relevant_titles) if relevant_titles else len(product_cards)

        except Exception as exc:
            logger.warning(f"Meesho scraping exception for '{query}': {exc}")
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

        # Visual Match Fallback against candidate product photos
        visual_matches = 0
        if settings.VISUAL_MATCH_ENABLED and thumbnail_url and candidate_images:
            visual_matches, matched_images = await check_visual_saturation_matches(
                thumbnail_url,
                candidate_images,
                similarity_threshold=settings.VISUAL_SIMILARITY_THRESHOLD
            )
            # If visual matches reveal disguised listings, ensure count reflects them
            listing_count = max(listing_count, visual_matches)

        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        avg_price = (sum(prices) / len(prices)) if prices else None

        return PlatformCompetition(
            platform="Meesho",
            listing_count=listing_count,
            min_price_inr=min_price,
            max_price_inr=max_price,
            avg_price_inr=round(avg_price, 2) if avg_price else None,
            top_sellers=sellers[:3],
            visually_matched_count=visual_matches,
            sample_listing_urls=listing_urls[:3],
        )

    async def check_amazon_in(
        self,
        product_name: str,
        query: str,
        thumbnail_url: Optional[str]
    ) -> PlatformCompetition:
        """
        Scrapes Amazon.in search results for competition density and price benchmarks.
        """
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.amazon.in/s?k={encoded_query}"
        logger.info(f"Checking Amazon.in competition for: '{query}'")

        prices: List[float] = []
        candidate_images: List[str] = []
        listing_urls: List[str] = []
        listing_count = 0

        try:
            context = await browser_manager.create_stealth_context()
            page = await browser_manager.create_stealth_page(context)
        except Exception as exc:
            logger.warning(f"Could not launch browser for Amazon.in check: {exc}")
            return PlatformCompetition(platform="Amazon.in", listing_count=0)

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT_MS)
            await asyncio.sleep(1.5)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Check for no results indicator
            no_results = soup.find(string=re.compile(r"No results for|did not match any products", re.IGNORECASE))
            if no_results:
                listing_count = 0
            else:
                # Target Amazon search result cards
                result_cards = soup.find_all("div", attrs={"data-component-type": "s-search-result"})
                listing_count = len(result_cards)

                # Also attempt to parse total results header, e.g. "1-16 of over 100 results"
                header_span = soup.find("span", string=re.compile(r"results for", re.IGNORECASE))
                if header_span:
                    m = re.search(r"of (?:over )?([0-9,]+) results", header_span.get_text())
                    if m:
                        try:
                            listing_count = int(m.group(1).replace(",", ""))
                        except ValueError:
                            pass

                for card in result_cards[:10]:
                    price_whole = card.find("span", class_="a-price-whole")
                    if price_whole:
                        p_val = parse_inr_price(price_whole.get_text())
                        if p_val:
                            prices.append(p_val)

                    img_tag = card.find("img", class_="s-image")
                    if img_tag and "src" in img_tag.attrs:
                        candidate_images.append(img_tag["src"])

                    link_tag = card.find("a", class_="a-link-normal s-no-outline")
                    if link_tag and "href" in link_tag.attrs:
                        listing_urls.append(f"https://www.amazon.in{link_tag['href']}")

        except Exception as exc:
            logger.warning(f"Amazon.in scraping exception for '{query}': {exc}")
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

        # Visual Match Check
        visual_matches = 0
        if settings.VISUAL_MATCH_ENABLED and thumbnail_url and candidate_images:
            visual_matches, _ = await check_visual_saturation_matches(
                thumbnail_url,
                candidate_images,
                similarity_threshold=settings.VISUAL_SIMILARITY_THRESHOLD
            )
            listing_count = max(listing_count, visual_matches)

        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        avg_price = (sum(prices) / len(prices)) if prices else None

        return PlatformCompetition(
            platform="Amazon.in",
            listing_count=listing_count,
            min_price_inr=min_price,
            max_price_inr=max_price,
            avg_price_inr=round(avg_price, 2) if avg_price else None,
            top_sellers=[],
            visually_matched_count=visual_matches,
            sample_listing_urls=listing_urls[:3],
        )

    async def check_india_meta_ads(self, query: str) -> Tuple[int, List[str]]:
        """
        Inspects Meta Ad Library (country=IN) to verify whether Indian dropshippers
        have already saturated the ad space for this product.
        """
        params = {
            "active_status": "active",
            "ad_type": "all",
            "country": "IN",
            "q": query,
            "search_type": "keyword_unordered",
            "media_type": "all",
        }
        url = f"https://www.facebook.com/ads/library/?{urllib.parse.urlencode(params)}"
        logger.info(f"Checking India Meta Ad Library for existing campaigns: '{query}'")

        ad_count = 0
        ad_urls: List[str] = []

        try:
            context = await browser_manager.create_stealth_context()
            page = await browser_manager.create_stealth_page(context)
        except Exception as exc:
            logger.warning(f"Could not launch browser for Meta India check: {exc}")
            return 0, []

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT_MS)
            await asyncio.sleep(2.0)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Check for "0 results" or "No ads match your search criteria"
            zero_results = soup.find(string=re.compile(r"0 results|No ads match your search", re.IGNORECASE))
            if zero_results:
                ad_count = 0
            else:
                # Count ad cards
                id_elements = soup.find_all(string=re.compile(r"Library ID:\s*\d+", re.IGNORECASE))
                ad_count = len(id_elements)
                for el in id_elements[:5]:
                    match = re.search(r"\d+", el)
                    if match:
                        ad_urls.append(f"https://www.facebook.com/ads/library/?id={match.group(0)}")

        except Exception as exc:
            logger.warning(f"India Meta Ad Library inspection exception for '{query}': {exc}")
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

        return ad_count, ad_urls

    def classify_saturation_tier(
        self,
        meesho_listings: int,
        india_ads: int,
        amazon_listings: int
    ) -> Tuple[SaturationTier, str]:
        """
        Classifies product into VIRGIN, EARLY, or SATURATED tier:
        - VIRGIN (0-2 listings on Meesho, 0 ads in India) -> Ultra High Priority
        - EARLY (3-8 listings, < 3 ads in India) -> Moderate Priority
        - SATURATED (> 8 listings or widely present on Meesho) -> Discard
        """
        if meesho_listings <= settings.VIRGIN_MAX_MEESHO_LISTINGS and india_ads <= settings.VIRGIN_MAX_INDIA_ADS:
            tier = SaturationTier.VIRGIN
            summary = (
                f"🌟 VIRGIN OPPORTUNITY: Only {meesho_listings} Meesho listings and {india_ads} active India ads. "
                f"Untapped blue ocean for first-mover dropshippers."
            )
        elif meesho_listings <= settings.EARLY_MAX_MEESHO_LISTINGS and india_ads <= settings.EARLY_MAX_INDIA_ADS:
            tier = SaturationTier.EARLY
            summary = (
                f"⚡ EARLY STAGE: {meesho_listings} Meesho listings and {india_ads} active India ads. "
                f"Growing demand, moderate competition, high win potential."
            )
        else:
            tier = SaturationTier.SATURATED
            summary = (
                f"❌ SATURATED: {meesho_listings} Meesho listings and {india_ads} active India ads. "
                f"Discounter race-to-the-bottom in progress. Immediate discard."
            )
        return tier, summary

    async def analyze_product_saturation(self, ad: ScrapedAd) -> SaturationReport:
        """Runs the full multi-channel saturation check pipeline for a candidate product."""
        # Select best search keyword
        query = ad.core_keywords[0] if ad.core_keywords else ad.clean_product_name

        # Concurrently query Meesho, Amazon.in, and India Meta Ads
        meesho_task = self.check_meesho(ad.clean_product_name, query, ad.image_url) if settings.MEESHO_ENABLED else None
        amazon_task = self.check_amazon_in(ad.clean_product_name, query, ad.image_url) if settings.AMAZON_IN_ENABLED else None
        meta_task = self.check_india_meta_ads(query) if settings.META_INDIA_ENABLED else None

        results = await asyncio.gather(
            meesho_task or asyncio.sleep(0),
            amazon_task or asyncio.sleep(0),
            meta_task or asyncio.sleep(0),
            return_exceptions=True
        )

        # Parse Meesho results
        if isinstance(results[0], PlatformCompetition):
            meesho_res = results[0]
        else:
            meesho_res = PlatformCompetition(platform="Meesho", listing_count=0)

        # Parse Amazon results
        if isinstance(results[1], PlatformCompetition):
            amazon_res = results[1]
        else:
            amazon_res = PlatformCompetition(platform="Amazon.in", listing_count=0)

        # Parse Meta India results
        if isinstance(results[2], tuple):
            india_ads_count, india_ad_urls = results[2]
        else:
            india_ads_count, india_ad_urls = 0, []

        tier, summary = self.classify_saturation_tier(
            meesho_listings=meesho_res.listing_count,
            india_ads=india_ads_count,
            amazon_listings=amazon_res.listing_count,
        )

        return SaturationReport(
            meesho=meesho_res,
            amazon=amazon_res,
            india_meta_ads_count=india_ads_count,
            india_meta_ad_urls=india_ad_urls,
            tier=tier,
            summary=summary,
        )
