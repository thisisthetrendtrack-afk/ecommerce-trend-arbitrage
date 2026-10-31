"""
Resilient HTTP Client with Humanized Client Hints and Exponential Backoff (utils/http_client.py).
Mitigates HTTP 429 (Rate Limit) and HTTP 503 (Service Unavailable) blocks.
"""

import asyncio
import functools
import logging
import random
from typing import Any, Dict, Optional
import httpx

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except ImportError:
    # Lightweight fallback when tenacity is not installed
    def stop_after_attempt(max_attempt_number: int):
        return max_attempt_number

    def wait_exponential(multiplier: float = 1.0, min: float = 0.0, max: float = 60.0):
        return lambda attempt: max(min, min + multiplier * (2.0 ** attempt))

    def retry_if_exception_type(exception_types):
        return exception_types

    def retry(stop=None, wait=None, retry=None, reraise: bool = True):
        def decorator(func):
            max_attempts = stop if isinstance(stop, int) else 3
            exc_types = retry if isinstance(retry, tuple) else (Exception,)

            if asyncio.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    for attempt in range(1, max_attempts + 1):
                        try:
                            return await func(*args, **kwargs)
                        except exc_types:
                            if attempt == max_attempts:
                                if reraise:
                                    raise
                                return None
                            delay = wait(attempt) if callable(wait) else (1.5 ** attempt)
                            await asyncio.sleep(min(delay, 5.0))
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    import time
                    for attempt in range(1, max_attempts + 1):
                        try:
                            return func(*args, **kwargs)
                        except exc_types:
                            if attempt == max_attempts:
                                if reraise:
                                    raise
                                return None
                            delay = wait(attempt) if callable(wait) else (1.5 ** attempt)
                            time.sleep(min(delay, 5.0))
                return sync_wrapper
        return decorator

logger = logging.getLogger("TrendArbitrage.HttpClient")

HUMAN_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}


class RateLimitOrServerError(Exception):
    """Raised when an upstream service returns 429 or 503."""
    pass


class HumanizedHttpClient:
    """Async HTTP wrapper with automatic humanized headers and backoff retry logic."""

    @staticmethod
    def get_headers(custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = dict(HUMAN_BROWSER_HEADERS)
        if custom_headers:
            headers.update(custom_headers)
        return headers

    @staticmethod
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1.5, min=2.0, max=12.0),
        retry=retry_if_exception_type((RateLimitOrServerError, httpx.TimeoutException, httpx.NetworkError)),
        reraise=True
    )
    async def get_json(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        req_headers = HumanizedHttpClient.get_headers(headers)
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=req_headers)
            
            # Catch 429 Too Many Requests or 503 Service Unavailable for exponential backoff
            if resp.status_code in (429, 503):
                logger.warning(f"Upstream returned HTTP {resp.status_code} for {url}. Applying exponential backoff...")
                raise RateLimitOrServerError(f"HTTP {resp.status_code}: Rate limited or service unavailable")
            
            resp.raise_for_status()
            return resp.json()
