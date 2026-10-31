"""
SQLite-backed De-duplication Cache with Memory Fallback (utils/dedup_cache.py).
Prevents redundant processing of already evaluated Meta ads, ensuring subsequent runs
only evaluate fresh opportunities.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from models import ScrapedAd

logger = logging.getLogger("TrendArbitrage.DedupCache")

DB_PATH = Path("processed_ads.db")


class DeduplicationCache:
    """Thread-safe storage with SQLite and graceful in-memory fallback."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._fallback_mode: bool = False
        self._mem_store: Dict[str, Dict[str, Any]] = {}
        self._mem_conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if str(self.db_path) == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", timeout=10.0)
            return self._mem_conn
        return sqlite3.connect(str(self.db_path), timeout=10.0)

    def _init_db(self) -> None:
        """Initializes the SQLite cache table if not present, falling back to in-memory on error."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_ads (
                    ad_id TEXT PRIMARY KEY,
                    product_name TEXT,
                    days_active INTEGER,
                    arbitrage_score REAL,
                    qualified INTEGER,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_ads(processed_at);")
            conn.commit()
            if str(self.db_path) != ":memory:":
                conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError) as exc:
            logger.warning(f"SQLite initialization failed at {self.db_path}: {exc}. Using in-memory cache.")
            self._fallback_mode = True

    def is_processed(self, ad_id: str) -> bool:
        """Checks if an ad ID has already been evaluated."""
        if self._fallback_mode:
            return ad_id in self._mem_store
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM processed_ads WHERE ad_id = ? LIMIT 1;", (ad_id,))
            res = cursor.fetchone() is not None
            if str(self.db_path) != ":memory:":
                conn.close()
            return res
        except Exception:
            return ad_id in self._mem_store

    def record_ad(
        self,
        ad_id: str,
        product_name: str,
        days_active: int,
        score: float,
        qualified: bool
    ) -> None:
        """Stores or updates an analyzed ad record."""
        self._mem_store[ad_id] = {
            "ad_id": ad_id,
            "product_name": product_name,
            "days_active": days_active,
            "arbitrage_score": score,
            "qualified": 1 if qualified else 0,
            "processed_at": datetime.now(timezone.utc),
        }
        if self._fallback_mode:
            return
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO processed_ads (ad_id, product_name, days_active, arbitrage_score, qualified, processed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ad_id) DO UPDATE SET
                    days_active = excluded.days_active,
                    arbitrage_score = excluded.arbitrage_score,
                    qualified = excluded.qualified,
                    processed_at = excluded.processed_at;
            """, (ad_id, product_name, days_active, score, 1 if qualified else 0, datetime.now(timezone.utc)))
            conn.commit()
            if str(self.db_path) != ":memory:":
                conn.close()
        except Exception as exc:
            logger.warning(f"Error persisting ad to SQLite: {exc}. Switching to in-memory mode.")
            self._fallback_mode = True

    def filter_fresh_ads(self, ads: List[ScrapedAd]) -> List[ScrapedAd]:
        """Filters out already-evaluated ads, retaining only fresh unseen candidates."""
        if not ads:
            return []
        
        fresh: List[ScrapedAd] = []
        for ad in ads:
            if not self.is_processed(ad.ad_id):
                fresh.append(ad)
            else:
                logger.debug(f"Skipping already-processed ad ID: {ad.ad_id}")
                    
        return fresh

    def get_stats(self) -> dict:
        """Returns statistics on processed opportunities."""
        if self._fallback_mode:
            total = len(self._mem_store)
            qual = sum(1 for v in self._mem_store.values() if v.get("qualified"))
            return {"total_processed": total, "qualified_count": qual}
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(qualified) FROM processed_ads;")
            row = cursor.fetchone()
            total = row[0] if row else 0
            qualified = row[1] if row else 0
            if str(self.db_path) != ":memory:":
                conn.close()
            return {"total_processed": total or 0, "qualified_count": qualified or 0}
        except Exception:
            total = len(self._mem_store)
            qual = sum(1 for v in self._mem_store.values() if v.get("qualified"))
            return {"total_processed": total, "qualified_count": qual}


# Global singleton instance
dedup_cache = DeduplicationCache()
