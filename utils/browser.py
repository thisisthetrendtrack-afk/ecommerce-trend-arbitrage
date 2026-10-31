"""
Playwright browser manager with stealth evasion, user-agent pooling, and anti-bot mitigation.
"""

import asyncio
import logging
import random
from typing import AsyncGenerator, Optional

try:
    from playwright.async_api import (
        async_playwright,
        Browser,
        BrowserContext,
        Page,
        Playwright,
    )
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Playwright = object
    Browser = object
    BrowserContext = object
    Page = object

from config import settings

try:
    from playwright_stealth import stealth_async
    HAS_PLAYWRIGHT_STEALTH = True
except ImportError:
    HAS_PLAYWRIGHT_STEALTH = False

logger = logging.getLogger("TrendArbitrage.Browser")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
]


class PlaywrightBrowserManager:
    """Manages resilient Playwright instances with stealth and context recycling."""

    def __init__(self):
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if not HAS_PLAYWRIGHT:
            logger.warning("Playwright is not installed. Browser automation will not be available.")
            return

        async with self._lock:
            if self._pw is None:
                self._pw = await async_playwright().start()
                launch_kwargs = {
                    "headless": settings.HEADLESS,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-infobars",
                        "--window-position=0,0",
                        "--ignore-certificate-errors",
                        "--ignore-certificate-errors-spki-list",
                    ]
                }
                if settings.PROXY_SERVER:
                    launch_kwargs["proxy"] = {"server": settings.PROXY_SERVER}
                
                self._browser = await self._pw.chromium.launch(**launch_kwargs)
                logger.info("Playwright Chromium engine initialized successfully.")

    async def create_stealth_context(self) -> BrowserContext:
        """Spawns an isolated browser context with randomized fingerprints."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright is not installed in the environment. Please run: pip install playwright && playwright install chromium")

        if not self._browser:
            await self.initialize()

        user_agent = random.choice(USER_AGENTS) if settings.ROTATE_USER_AGENTS else USER_AGENTS[0]
        viewport = random.choice(VIEWPORTS)

        context = await self._browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            locale="en-US",
            timezone_id="America/New_York",
            has_touch=False,
            is_mobile=False,
            device_scale_factor=1,
            color_scheme="light",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "max-age=0",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

        # Pre-seed realistic display and consent cookies to prevent 403 on Meta & Marketplaces
        try:
            await context.add_cookies([
                {"name": "wd", "value": f"{viewport['width']}x{viewport['height']}", "domain": ".facebook.com", "path": "/"},
                {"name": "dpr", "value": "1", "domain": ".facebook.com", "path": "/"},
            ])
        except Exception:
            pass

        return context

    async def create_stealth_page(self, context: Optional[BrowserContext] = None) -> Page:
        """Instantiates a page and injects stealth script evasions."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright is not installed in the environment.")

        ctx = context or await self.create_stealth_context()
        page = await ctx.new_page()
        page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)

        if HAS_PLAYWRIGHT_STEALTH:
            await stealth_async(page)
        else:
            # Native JS evasion script fallback
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """)

        return page

    async def close(self) -> None:
        """Gracefully shuts down browser contexts and Playwright."""
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None
            logger.info("Playwright browser instance closed.")


# Global browser manager instance
browser_manager = PlaywrightBrowserManager()
