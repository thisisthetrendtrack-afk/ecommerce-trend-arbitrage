"""
Global Sourcing & Factory Benchmark Module (sourcing.py)
Calculates Tier-1 China Factory FOB (YiwuGo/1688), Landed Cost,
and validates viable margins accounting for Indian COD RTO dynamics.
"""

import asyncio
import logging
import re
import urllib.parse
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
import httpx
from models import SourcingBenchmark
from utils.http_client import HumanizedHttpClient

logger = logging.getLogger("TrendArbitrage.Sourcing")

# Currency Constants
RMB_TO_INR_RATE = 11.85
USD_TO_INR_RATE = 86.50
CUSTOMS_TAX_RATE = 0.35  # 35% Basic Customs Duty + SWS + IGST buffer

# India COD Logistics Constants (Shiprocket / Delhivery baseline)
BASE_FORWARD_FREIGHT_INR = 65.0   # Base 500g delivery
RTO_REVERSE_FREIGHT_INR = 55.0    # Return freight penalty
COD_COLLECTION_FEE_INR = 38.0     # Flat COD fee
EXPECTED_RTO_RATE = 0.25          # 25% standard COD failure rate for winning ads


class GlobalSourcingBenchmarker:
    def __init__(self):
        self.yiwugo_search_url = "https://en.yiwugo.com/search/s.html"
        self.indiamart_search_url = "https://dir.indiamart.com/search.mp"

    def estimate_unit_weight_grams(self, clean_keyword: str) -> float:
        """
        Estimates shipping weight from keywords to calculate realistic freight.
        """
        kw = clean_keyword.lower()
        if any(w in kw for w in ["lamp", "projector", "massager", "humidifier", "dispenser", "blender", "stretcher"]):
            return 850.0  # Bulky items / small electronics
        if any(w in kw for w in ["roller", "brush", "strap", "corrector", "clipper", "cleaner"]):
            return 250.0  # Medium beauty/fitness gadget
        if any(w in kw for w in ["ring", "necklace", "patch", "sticker", "cable"]):
            return 80.0   # Lightweight
        return 400.0      # Default standard parcel

    def calculate_dynamic_freight(self, weight_grams: float) -> float:
        """
        Calculates consolidated freight slab in 500g steps.
        """
        slabs = max(1, int((weight_grams + 499) // 500))
        return round(slabs * 140.0, 2)  # ~₹140 per 500g consolidated air slab

    async def query_china_factory_price(
        self, clean_keyword: str
    ) -> Tuple[Optional[float], Optional[float], int, str, str, bool]:
        """
        Scrapes YiwuGo with strict card boundaries and price extraction.
        Returns: (lowest_rmb, lowest_usd, min_moq, badge, target_url, is_real_scrape)
        """
        encoded_query = urllib.parse.quote_plus(clean_keyword)
        target_url = f"{self.yiwugo_search_url}?q={encoded_query}"
        headers = HumanizedHttpClient.get_headers({"Referer": "https://en.yiwugo.com/"})

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(target_url, headers=headers)
                if resp.status_code == 200 and resp.text:
                    soup = BeautifulSoup(resp.text, "html.parser")

                    product_cards = soup.select(".pro_list_item, .list-item, div.product-box")
                    if not product_cards:
                        product_cards = soup.select("ul.pro_list > li")

                    prices_rmb: List[float] = []
                    moqs: List[int] = []

                    for card in product_cards[:10]:
                        # Scope to price elements first
                        price_elem = card.select_one(".price, .pri, .font-bold, .money")
                        price_text = price_elem.get_text() if price_elem else card.get_text()

                        # Non-capturing group for currency symbols
                        price_matches = re.findall(r"(?:¥|RMB|￥|\$)\s*([0-9]+\.?[0-9]*)", price_text)
                        for raw_p in price_matches:
                            try:
                                val = float(raw_p)
                                # Lower bound 0.35 RMB (~₹4.15 INR) for micro-wholesale (hair ties, cable clips, stickers)
                                if 0.35 <= val <= 3500.0:
                                    prices_rmb.append(val)
                            except ValueError:
                                continue

                        # Extract MOQ
                        moq_elem = card.select_one(".moq, .min-order, .order-num")
                        moq_text = moq_elem.get_text() if moq_elem else card.get_text()
                        moq_match = re.search(r"(?:Min\.?\s*Order|MOQ|Order:?)\s*([0-9]+)", moq_text, re.IGNORECASE)
                        if moq_match:
                            try:
                                moq_val = int(moq_match.group(1))
                                if 1 <= moq_val <= 5000:
                                    moqs.append(moq_val)
                            except ValueError:
                                pass

                    if prices_rmb:
                        lowest_rmb = min(prices_rmb)
                        min_moq = min(moqs) if moqs else 10
                        lowest_usd = round(lowest_rmb / (USD_TO_INR_RATE / RMB_TO_INR_RATE), 2)
                        return lowest_rmb, lowest_usd, min_moq, "Verified Yiwu Factory Rate", target_url, True

        except Exception as exc:
            logger.warning(f"[Sourcing] YiwuGo query notice: {exc}")

        return None, None, 50, "Estimated Factory Benchmark", target_url, False

    async def query_indiamart_local_importers(self, clean_keyword: str) -> Tuple[bool, List[str]]:
        """
        Checks IndiaMART to see if domestic importers in Delhi, Surat, Mumbai, or Rajkot
        already have local wholesale container inventory.
        """
        encoded_query = urllib.parse.quote_plus(clean_keyword)
        target_url = f"{self.indiamart_search_url}?ss={encoded_query}"
        headers = HumanizedHttpClient.get_headers({
            "Referer": "https://dir.indiamart.com/",
        })

        found_hubs: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(target_url, headers=headers)
                if resp.status_code == 200 and resp.text:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    text_content = soup.get_text()

                    for hub in ["Delhi", "Surat", "Mumbai", "Ahmedabad", "Jaipur", "Bengaluru", "Rajkot"]:
                        if re.search(rf"\b{hub}\b", text_content, re.IGNORECASE):
                            found_hubs.append(hub)

        except Exception as exc:
            logger.debug(f"[Sourcing] IndiaMART inspection notice: {exc}")

        unique_hubs = list(dict.fromkeys(found_hubs))
        return bool(unique_hubs), unique_hubs

    async def benchmark_product_sourcing(
        self,
        clean_keyword: str,
        target_selling_price_inr: float = 899.0,
        max_wholesale_inr: Optional[float] = None,
    ) -> SourcingBenchmark:
        # Run China wholesale query and IndiaMART check concurrently
        china_task = self.query_china_factory_price(clean_keyword)
        india_task = self.query_indiamart_local_importers(clean_keyword)

        results = await asyncio.gather(china_task, india_task, return_exceptions=True)

        # Parse China wholesale results
        if isinstance(results[0], tuple):
            price_rmb, price_usd, moq, badge, sourcing_url, is_real_scrape = results[0]
        else:
            price_rmb, price_usd, moq, badge, sourcing_url, is_real_scrape = None, None, 50, "Factory Benchmark", None, False

        # Parse IndiaMART results
        if isinstance(results[1], tuple):
            indiamart_avail, hub_cities = results[1]
        else:
            indiamart_avail, hub_cities = False, []

        estimated_weight = self.estimate_unit_weight_grams(clean_keyword)
        freight_inr = self.calculate_dynamic_freight(estimated_weight)

        if is_real_scrape and price_rmb:
            factory_price_inr = round(price_rmb * RMB_TO_INR_RATE, 2)
        elif is_real_scrape and price_usd:
            factory_price_inr = round(price_usd * USD_TO_INR_RATE, 2)
        else:
            # Conservative synthetic baseline (25% of selling price)
            factory_price_inr = round(target_selling_price_inr * 0.25, 2)
            price_rmb = round(factory_price_inr / RMB_TO_INR_RATE, 1)
            price_usd = round(factory_price_inr / USD_TO_INR_RATE, 2)

        # Landed Cost = Factory Unit Price (INR) + Dynamic Freight + Customs/Taxes (~35%)
        customs_taxes_inr = round(factory_price_inr * CUSTOMS_TAX_RATE, 2)
        est_landed_cost_inr = round(factory_price_inr + freight_inr + customs_taxes_inr, 2)

        # Gross Margin %
        gross_margin_pct = (
            round(((target_selling_price_inr - est_landed_cost_inr) / target_selling_price_inr) * 100, 2)
            if target_selling_price_inr > 0
            else 0.0
        )

        # Net COD Return-to-Origin (RTO) validation
        delivered_ratio = 1.0 - EXPECTED_RTO_RATE
        blended_courier_loss = (
            (BASE_FORWARD_FREIGHT_INR + COD_COLLECTION_FEE_INR) * delivered_ratio
            + (BASE_FORWARD_FREIGHT_INR + RTO_REVERSE_FREIGHT_INR) * EXPECTED_RTO_RATE
        )
        estimated_ad_cpa = round(target_selling_price_inr * 0.32, 2)
        net_revenue_per_order = target_selling_price_inr * delivered_ratio
        net_contribution_inr = round(net_revenue_per_order - est_landed_cost_inr - blended_courier_loss - estimated_ad_cpa, 2)

        # Strict Fallback & Viability Guard:
        # Require real scraping (do not hallucinate viable margins on fallback), >= 60% Gross Margin, and positive net contribution (> ₹100)
        is_viable_margin = is_real_scrape and (gross_margin_pct >= 60.0) and (net_contribution_inr > 100.0)

        if max_wholesale_inr and est_landed_cost_inr > max_wholesale_inr:
            logger.info(f"[Sourcing] Discarded: Landed cost ₹{est_landed_cost_inr} exceeds requested wholesale cap of ₹{max_wholesale_inr}")
            is_viable_margin = False

        return SourcingBenchmark(
            platform="YiwuGo / 1688 Wholesale",
            factory_price_rmb=price_rmb,
            factory_price_usd=price_usd,
            factory_price_inr=factory_price_inr,
            moq=moq,
            supplier_badge=badge,
            freight_estimate_inr=freight_inr,
            customs_taxes_inr=customs_taxes_inr,
            est_landed_cost_inr=est_landed_cost_inr,
            target_selling_price_inr=target_selling_price_inr,
            gross_margin_pct=gross_margin_pct,
            is_viable_margin=is_viable_margin,
            max_wholesale_inr=max_wholesale_inr,
            indiamart_available=indiamart_avail,
            indiamart_hub_cities=hub_cities[:3],
            sourcing_url=sourcing_url,
        )


sourcing_benchmarker = GlobalSourcingBenchmarker()
