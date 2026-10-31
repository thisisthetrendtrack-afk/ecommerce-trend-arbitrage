"""
Data models and typed schemas for E-Commerce Trend Arbitrage Engine.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SaturationTier(str, Enum):
    VIRGIN = "VIRGIN"       # 0-2 listings on Meesho, 0 ads in India -> Ultra High Priority
    EARLY = "EARLY"         # 3-8 listings, < 3 ads in India -> Moderate Priority
    SATURATED = "SATURATED" # > 8 listings or widely present on Meesho -> Discard


class RTORiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ScrapedAd(BaseModel):
    """Represents a validated active ad extracted from Western Meta Ad Library."""
    ad_id: str
    source_country: str
    started_date: Optional[datetime] = None
    days_active: int = Field(ge=0, description="Consecutive running days")
    ad_title: str
    ad_body: str = ""
    landing_page_url: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    ad_library_url: str
    clean_product_name: str
    core_keywords: List[str] = Field(default_factory=list)
    creative_variations_count: int = 1
    is_confirmed_scaling: bool = False


class PlatformCompetition(BaseModel):
    """Competition profile extracted from an Indian e-commerce marketplace."""
    platform: str
    listing_count: int = 0
    min_price_inr: Optional[float] = None
    max_price_inr: Optional[float] = None
    avg_price_inr: Optional[float] = None
    top_sellers: List[str] = Field(default_factory=list)
    visually_matched_count: int = 0
    sample_listing_urls: List[str] = Field(default_factory=list)


class SaturationReport(BaseModel):
    """Consolidated market competition and saturation status across India channels."""
    meesho: PlatformCompetition
    amazon: PlatformCompetition
    india_meta_ads_count: int = 0
    india_meta_ad_urls: List[str] = Field(default_factory=list)
    tier: SaturationTier
    summary: str


class UnitEconomics(BaseModel):
    """Financial feasibility and India COD fulfillment projections."""
    est_source_cost_inr: float
    est_shipping_inr: float
    est_marketing_cpa_inr: float
    est_rto_allowance_inr: float
    recommended_selling_price_inr: float
    est_net_margin_percentage: float
    rto_risk: RTORiskLevel
    rto_reasons: List[str] = Field(default_factory=list)
    in_sweet_spot: bool = True


class SourcingBenchmark(BaseModel):
    """Global China wholesale sourcing and Indian landed cost analysis."""
    platform: str = "YiwuGo / 1688"
    factory_price_rmb: Optional[float] = None
    factory_price_usd: Optional[float] = None
    factory_price_inr: float
    moq: int = 1
    supplier_badge: str = "Verified Factory"
    freight_estimate_inr: float = 120.0
    customs_taxes_inr: float = 0.0
    est_landed_cost_inr: float
    target_selling_price_inr: float
    gross_margin_pct: float
    is_viable_margin: bool = True  # True if gross margin >= 60%
    max_wholesale_inr: Optional[float] = None  # User requested wholesale ceiling
    indiamart_available: bool = False
    indiamart_hub_cities: List[str] = Field(default_factory=list)
    sourcing_url: Optional[str] = None


class OpportunityEvaluation(BaseModel):
    """Final qualified arbitrage opportunity ready for reporting and Telegram delivery."""
    ad: ScrapedAd
    saturation: SaturationReport
    economics: UnitEconomics
    sourcing: Optional[SourcingBenchmark] = None
    arbitrage_score: float = Field(ge=0.0, le=100.0)
    qualified: bool
    evaluation_notes: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
