import asyncio
import re
import json
from bs4 import BeautifulSoup
from utils.browser import browser_manager

async def inspect_snapshot():
    try:
        page = await browser_manager.create_stealth_page()
    except Exception as exc:
        print(f"[!] Could not launch browser: {exc}")
        return

    try:
        url = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=sunset%20lamp&search_type=keyword_unordered&media_type=all"
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        for s in soup.find_all("script"):
            txt = s.string or ""
            if "search_results_connection" in txt:
                # Find start of JSON object
                match = re.search(r'"search_results_connection"\s*:\s*(\{.+?\})\s*,\s*"[^"]+"\s*:', txt)
                if not match:
                    # Let's find index
                    idx = txt.find('"search_results_connection"')
                    snippet = txt[idx:idx+2000]
                    print("Snippet:", snippet[:500])
                    # Let's search for startDate in that script
                    for sm in re.finditer(r'"startDate"\s*:\s*(\d+)', txt):
                        print("startDate timestamp:", sm.group(1))
                    for bm in re.finditer(r'"body"\s*:\s*\{"text"\s*:\s*"([^"]+)"\}', txt):
                        print("body text sample:", bm.group(1)[:60])
                    for lm in re.finditer(r'"link_url"\s*:\s*"([^"]+)"', txt):
                        print("link_url sample:", lm.group(1))
                    for im in re.finditer(r'"original_image_url"\s*:\s*"([^"]+)"', txt):
                        print("image_url sample:", im.group(1)[:80])
                    break
    finally:
        await browser_manager.close()

if __name__ == "__main__":
    asyncio.run(inspect_snapshot())
