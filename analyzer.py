"""
Unit Economics & Feasibility Filter (analyzer.py).
Evaluates target selling price in India (sweet spot: ₹699 - ₹1,499).
Detects high Return-to-Origin (RTO) risk (fragile, liquids, heavy/bulky items).
Calculates composite Arbitrage Score (0-100) based on US longevity vs. India market saturation.
"""

import logging
import re
from typing import List, Tuple
from config import settings
from models import (
    OpportunityEvaluation,
    RTORiskLevel,
    SaturationReport,
    SaturationTier,
    ScrapedAd,
    UnitEconomics,
)

logger = logging.getLogger("TrendArbitrage.Analyzer")


class OpportunityAnalyzer:
    """Evaluates unit economics, logistics feasibility, and arbitrage potential."""

    def detect_rto_risk(self, title: str, body: str, keywords: List[str]) -> Tuple[RTORiskLevel, List[str]]:
        """
        Analyzes product metadata for Return-To-Origin (RTO) danger triggers.
        In Indian COD dropshipping (70-80% COD), fragile, liquid, or bulky items
        experience disastrous 30-45% RTO rates.
        Uses word-boundary regex to prevent false positives (e.g., 'table' in 'portable',
        'cup' in 'occupy', 'oil' in 'coil').
        """
        reasons: List[str] = []
        combined_text = f"{title} {body} {' '.join(keywords)}".lower()

        def match_keywords(keyword_list: List[str]) -> List[str]:
            matches = []
            for kw in keyword_list:
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue
                # Word boundary check for word/phrase
                pattern = rf"\b{re.escape(kw_clean)}\b"
                if re.search(pattern, combined_text):
                    matches.append(kw_clean)
            return matches

        # 1. Fragile Risk
        fragile_matches = match_keywords(settings.RTO_FRAGILE_KEYWORDS)
        if fragile_matches:
            reasons.append(f"Fragile material detected: {', '.join(fragile_matches)} (high transit breakage & rejection)")

        # 2. Liquid / Chemical Risk
        liquid_matches = match_keywords(settings.RTO_LIQUID_KEYWORDS)
        if liquid_matches:
            reasons.append(f"Liquid/Cosmetic detected: {', '.join(liquid_matches)} (spill hazard, courier compliance hurdles)")

        # 3. Bulky / Heavy Weight Risk
        heavy_matches = match_keywords(settings.RTO_HEAVY_KEYWORDS)
        if heavy_matches:
            reasons.append(f"Heavy/Bulky item detected: {', '.join(heavy_matches)} (punitive volumetric courier charges)")

        if len(reasons) >= 2 or fragile_matches:
            risk_level = RTORiskLevel.HIGH
        elif len(reasons) == 1:
            risk_level = RTORiskLevel.MEDIUM
        else:
            risk_level = RTORiskLevel.LOW

        return risk_level, reasons

    def calculate_unit_economics(
        self,
        ad: ScrapedAd,
        saturation: SaturationReport,
        rto_risk: RTORiskLevel,
        rto_reasons: List[str]
    ) -> UnitEconomics:
        """
        Calculates projected India dropshipping unit economics.
        Target sweet spot: ₹699 - ₹1,499.
        """
        # Determine recommended India retail price
        comp_price = saturation.amazon.avg_price_inr or saturation.meesho.avg_price_inr

        if comp_price:
            # Price competitively while staying inside sweet spot
            target_price = min(max(comp_price * 0.95, settings.MIN_TARGET_PRICE_INR), settings.MAX_TARGET_PRICE_INR)
        else:
            # Default to ideal impulse buy anchor
            target_price = 899.0

        target_price = round(target_price, 0)
        in_sweet_spot = settings.MIN_TARGET_PRICE_INR <= target_price <= settings.MAX_TARGET_PRICE_INR

        # Cost Breakdown (Standard Indian E-Commerce COD benchmarks)
        # 1. Estimated landed sourcing cost (Wholesale/B2B China-India or local Surat/Delhi hub)
        est_source_cost = round(target_price * 0.22, 2)  # ~22% sourcing ratio

        # 2. Forward Delivery Shipping (Delhivery, Bluedart, Shadowfax)
        est_shipping = 90.0

        # 3. Marketing CAC / Facebook Ad CPA in India (broad target)
        est_marketing_cpa = 260.0

        # 4. RTO Loss Provision per delivered order
        if rto_risk == RTORiskLevel.HIGH:
            est_rto_allowance = 110.0  # Assumes 35% RTO
        elif rto_risk == RTORiskLevel.MEDIUM:
            est_rto_allowance = 60.0   # Assumes 22% RTO
        else:
            est_rto_allowance = 35.0   # Assumes 12% RTO

        total_costs = est_source_cost + est_shipping + est_marketing_cpa + est_rto_allowance
        net_profit = target_price - total_costs
        net_margin_pct = round((net_profit / target_price) * 100, 2) if target_price > 0 else 0.0

        return UnitEconomics(
            est_source_cost_inr=est_source_cost,
            est_shipping_inr=est_shipping,
            est_marketing_cpa_inr=est_marketing_cpa,
            est_rto_allowance_inr=est_rto_allowance,
            recommended_selling_price_inr=target_price,
            est_net_margin_percentage=net_margin_pct,
            rto_risk=rto_risk,
            rto_reasons=rto_reasons,
            in_sweet_spot=in_sweet_spot,
        )

    def calculate_arbitrage_score(
        self,
        ad: ScrapedAd,
        saturation: SaturationReport,
        economics: UnitEconomics
    ) -> Tuple[float, List[str]]:
        """
        Assigns an Arbitrage Score (0-100) based on:
        - Proof of profitability (US active days) [Max 35 pts]
        - Market vacancy (VIRGIN vs EARLY vs SATURATED) [Max 40 pts]
        - Retail pricing sweet spot (₹699 - ₹1,499) [Max 15 pts]
        - Unit net profit margin spread [Max 10 pts]
        - RTO risk penalty [-20 to 0 pts]
        """
        score = 0.0
        notes: List[str] = []

        # 1. Western Ad Longevity (Traction & Profitability proof) [0 - 35 pts]
        if ad.days_active >= 30:
            score += 35.0
            notes.append(f"+35 pts: Sustained high-scale ad ({ad.days_active} active days in {ad.source_country})")
        elif ad.days_active >= 14:
            score += 25.0
            notes.append(f"+25 pts: Strong verified longevity ({ad.days_active} days active)")
        elif ad.days_active >= 7:
            score += 15.0
            notes.append(f"+15 pts: Meets minimum 7-day profitability threshold ({ad.days_active} days active)")
        else:
            score += 5.0
            notes.append(f"+5 pts: Less than 7 days active ({ad.days_active} days)")

        # 2. India Saturation Gap [0 - 40 pts]
        if saturation.tier == SaturationTier.VIRGIN:
            score += 40.0
            notes.append("+40 pts: VIRGIN market opportunity (0-2 Meesho listings, 0 India Meta ads)")
        elif saturation.tier == SaturationTier.EARLY:
            score += 20.0
            notes.append("+20 pts: EARLY stage opportunity (low competition, rising interest)")
        else:
            score += 0.0
            notes.append("+0 pts: SATURATED market (heavy competition on Meesho/India ads)")

        # 3. Pricing Sweet Spot [0 - 15 pts]
        if economics.in_sweet_spot:
            score += 15.0
            notes.append(f"+15 pts: Target price (₹{economics.recommended_selling_price_inr:,.0f}) within impulse buy sweet spot (₹699-₹1499)")
        else:
            score += 5.0
            notes.append(f"+5 pts: Target price (₹{economics.recommended_selling_price_inr:,.0f}) outside ideal sweet spot")

        # 4. Projected Margin Spread [0 - 10 pts]
        if economics.est_net_margin_percentage >= 30.0:
            score += 10.0
            notes.append(f"+10 pts: High net margin ({economics.est_net_margin_percentage}%)")
        elif economics.est_net_margin_percentage >= 20.0:
            score += 6.0
            notes.append(f"+6 pts: Healthy net margin ({economics.est_net_margin_percentage}%)")
        elif economics.est_net_margin_percentage > 0:
            score += 2.0
            notes.append(f"+2 pts: Thin net margin ({economics.est_net_margin_percentage}%)")
        else:
            score += 0.0
            notes.append(f"+0 pts: Negative projected margin ({economics.est_net_margin_percentage}%)")

        # 5. RTO Risk Penalty [-20 to 0 pts]
        if economics.rto_risk == RTORiskLevel.HIGH:
            score -= 20.0
            notes.append("-20 pts penalty: HIGH RTO Risk detected (fragile/liquid/bulky)")
        elif economics.rto_risk == RTORiskLevel.MEDIUM:
            score -= 8.0
            notes.append("-8 pts penalty: MEDIUM RTO Risk detected")
        else:
            notes.append("0 pts penalty: LOW RTO Risk profile")

        # Clamp between 0.0 and 100.0
        final_score = max(0.0, min(100.0, round(score, 1)))
        return final_score, notes

    def evaluate(self, ad: ScrapedAd, saturation: SaturationReport) -> OpportunityEvaluation:
        """Executes full unit economics assessment and assigns arbitrage qualification."""
        rto_risk, rto_reasons = self.detect_rto_risk(ad.ad_title, ad.ad_body, ad.core_keywords)
        economics = self.calculate_unit_economics(ad, saturation, rto_risk, rto_reasons)
        arbitrage_score, notes = self.calculate_arbitrage_score(ad, saturation, economics)

        # Qualification Criteria:
        # 1. Not SATURATED
        # 2. Score >= Threshold (default 65)
        # 3. Not HIGH RTO risk
        is_qualified = (
            saturation.tier != SaturationTier.SATURATED and
            arbitrage_score >= settings.MIN_ARBITRAGE_SCORE_TO_NOTIFY and
            economics.rto_risk != RTORiskLevel.HIGH
        )

        return OpportunityEvaluation(
            ad=ad,
            saturation=saturation,
            economics=economics,
            arbitrage_score=arbitrage_score,
            qualified=is_qualified,
            evaluation_notes=notes,
        )
