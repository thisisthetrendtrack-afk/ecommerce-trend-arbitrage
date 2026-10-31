"""
Configuration module for E-Commerce Trend Arbitrage Engine.
Loads, validates, and exposes settings from environment variables or .env file.
Supports both Pydantic v1 and v2.
"""

from pathlib import Path
from typing import List, Optional, Union

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field, field_validator
    _PYDANTIC_V2 = True
except ImportError:
    from pydantic import BaseSettings, Field, validator
    _PYDANTIC_V2 = False


if _PYDANTIC_V2:
    class AppSettings(BaseSettings):
        """Production settings schema with validation and sensible defaults (Pydantic v2)."""

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )

        # --- Telegram Settings ---
        TELEGRAM_BOT_TOKEN: Optional[str] = None
        TELEGRAM_CHAT_ID: Optional[str] = None
        TELEGRAM_ENABLED: bool = False

        # --- Ingestion & Ad Search Filters ---
        META_ACCESS_TOKEN: Optional[str] = None  # Optional official Graph API token
        AD_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "50% off free shipping",
                "get yours today",
                "limited stock",
                "order now while supplies last",
                "buy 1 get 1 free",
            ]
        )
        SEARCH_COUNTRIES: Union[List[str], str] = Field(
            default_factory=lambda: ["US", "GB", "CA", "AU"]
        )
        MIN_AD_ACTIVE_DAYS: int = 7
        MAX_ADS_PER_KEYWORD: int = 15

        # --- Playwright & Stealth ---
        HEADLESS: bool = True
        BROWSER_TIMEOUT_MS: int = 30000
        MAX_CONCURRENT_TASKS: int = 3
        ROTATE_USER_AGENTS: bool = True
        PROXY_SERVER: Optional[str] = None

        # --- Saturation Checkers ---
        MEESHO_ENABLED: bool = True
        AMAZON_IN_ENABLED: bool = True
        META_INDIA_ENABLED: bool = True
        VISUAL_MATCH_ENABLED: bool = True
        VISUAL_SIMILARITY_THRESHOLD: float = 0.80

        VIRGIN_MAX_MEESHO_LISTINGS: int = 2
        VIRGIN_MAX_INDIA_ADS: int = 0
        EARLY_MAX_MEESHO_LISTINGS: int = 8
        EARLY_MAX_INDIA_ADS: int = 2

        # --- Economics & Feasibility ---
        MIN_TARGET_PRICE_INR: float = 699.0
        MAX_TARGET_PRICE_INR: float = 1499.0
        MAX_WHOLESALE_PRICE_INR: float = 350.0  # Wholesale ceiling filter in INR
        USD_TO_INR_RATE: float = 83.5
        MIN_ARBITRAGE_SCORE_TO_NOTIFY: float = 65.0

        # --- RTO Risk Dictionaries ---
        RTO_FRAGILE_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "glass", "ceramic", "mirror", "porcelain", "fragile", "crystal", "cup", "mug"
            ]
        )
        RTO_LIQUID_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "serum", "liquid", "cream", "oil", "perfume", "shampoo", "lotion", "spray", "gel", "fluid"
            ]
        )
        RTO_HEAVY_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "dumbbell", "heavy", "gym", "weight", "sofa", "furniture", "table", "chair", "overweight"
            ]
        )

        @field_validator("AD_KEYWORDS", "SEARCH_COUNTRIES", "RTO_FRAGILE_KEYWORDS", "RTO_LIQUID_KEYWORDS", "RTO_HEAVY_KEYWORDS", mode="before")
        @classmethod
        def parse_comma_separated(cls, value):
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            return value

        @property
        def is_telegram_configured(self) -> bool:
            return bool(self.TELEGRAM_ENABLED and self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

else:
    class AppSettings(BaseSettings):
        """Production settings schema with validation and sensible defaults (Pydantic v1)."""

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"

            @classmethod
            def parse_env_var(cls, field_name: str, raw_val: str):
                upper_field = field_name.upper()
                if upper_field in ("AD_KEYWORDS", "SEARCH_COUNTRIES", "RTO_FRAGILE_KEYWORDS", "RTO_LIQUID_KEYWORDS", "RTO_HEAVY_KEYWORDS"):
                    return [item.strip() for item in raw_val.split(",") if item.strip()]
                try:
                    return cls.json_loads(raw_val)
                except Exception:
                    return raw_val

        # --- Telegram Settings ---
        TELEGRAM_BOT_TOKEN: Optional[str] = None
        TELEGRAM_CHAT_ID: Optional[str] = None
        TELEGRAM_ENABLED: bool = False

        # --- Ingestion & Ad Search Filters ---
        META_ACCESS_TOKEN: Optional[str] = None  # Optional official Graph API token
        AD_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "50% off free shipping",
                "get yours today",
                "limited stock",
                "order now while supplies last",
                "buy 1 get 1 free",
            ]
        )
        SEARCH_COUNTRIES: Union[List[str], str] = Field(
            default_factory=lambda: ["US", "GB", "CA", "AU"]
        )
        MIN_AD_ACTIVE_DAYS: int = 7
        MAX_ADS_PER_KEYWORD: int = 15

        # --- Playwright & Stealth ---
        HEADLESS: bool = True
        BROWSER_TIMEOUT_MS: int = 30000
        MAX_CONCURRENT_TASKS: int = 3
        ROTATE_USER_AGENTS: bool = True
        PROXY_SERVER: Optional[str] = None

        # --- Saturation Checkers ---
        MEESHO_ENABLED: bool = True
        AMAZON_IN_ENABLED: bool = True
        META_INDIA_ENABLED: bool = True
        VISUAL_MATCH_ENABLED: bool = True
        VISUAL_SIMILARITY_THRESHOLD: float = 0.80

        VIRGIN_MAX_MEESHO_LISTINGS: int = 2
        VIRGIN_MAX_INDIA_ADS: int = 0
        EARLY_MAX_MEESHO_LISTINGS: int = 8
        EARLY_MAX_INDIA_ADS: int = 2

        # --- Economics & Feasibility ---
        MIN_TARGET_PRICE_INR: float = 699.0
        MAX_TARGET_PRICE_INR: float = 1499.0
        MAX_WHOLESALE_PRICE_INR: float = 350.0  # Wholesale ceiling filter in INR
        USD_TO_INR_RATE: float = 83.5
        MIN_ARBITRAGE_SCORE_TO_NOTIFY: float = 65.0

        # --- RTO Risk Dictionaries ---
        RTO_FRAGILE_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "glass", "ceramic", "mirror", "porcelain", "fragile", "crystal", "cup", "mug"
            ]
        )
        RTO_LIQUID_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "serum", "liquid", "cream", "oil", "perfume", "shampoo", "lotion", "spray", "gel", "fluid"
            ]
        )
        RTO_HEAVY_KEYWORDS: Union[List[str], str] = Field(
            default_factory=lambda: [
                "dumbbell", "heavy", "gym", "weight", "sofa", "furniture", "table", "chair", "overweight"
            ]
        )

        @validator("AD_KEYWORDS", "SEARCH_COUNTRIES", "RTO_FRAGILE_KEYWORDS", "RTO_LIQUID_KEYWORDS", "RTO_HEAVY_KEYWORDS", pre=True, always=True)
        def parse_comma_separated(cls, value):
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            return value

        @property
        def is_telegram_configured(self) -> bool:
            return bool(self.TELEGRAM_ENABLED and self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)


# Global singleton instance
settings = AppSettings()
