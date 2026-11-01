"""
========================================================================================
Product Title, High-Intent Keyword & Supplier Link Generator (utils/supplier_generator.py)
========================================================================================
Extracts clean product titles, high buyer-intent keyword variants, and generates
clickable deep-search URLs for top 9 global and domestic B2B/B2C supplier platforms:
1. 1688 (China Factory Wholesale)
2. Alibaba (Global B2B Manufacturers)
3. YiwuGo (Yiwu Wholesale Market)
4. AliExpress (Fast Dropship Testing)
5. CJ Dropshipping (Direct Fulfillment & Agent Sourcing)
6. IndiaMART (Indian Domestic Importers & Manufacturers)
7. Meesho (Indian Reseller & B2C Price Floor)
8. Temu (Direct Factory Retail Competitor)
9. Amazon (Consumer Demand & Retail Benchmark)
========================================================================================
"""

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple


# Common e-commerce stopwords and filler adjectives
COMMON_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "is", "are", "was",
    "were", "with", "for", "and", "or", "to", "in", "on", "at", "by", "from",
    "up", "your", "our", "my", "you", "we", "it", "its", "so", "just", "best",
    "new", "make", "more", "now", "here", "there", "why", "how", "what", "all",
    "pro", "ultra", "mini", "portable", "super", "easy", "perfect", "smart",
    "get", "buy", "shop", "order", "free", "shipping", "discount", "sale",
    "top", "trend", "trending", "viral", "amazing", "magic", "hot"
}

# Marketing buzzwords & promotional call-to-actions to strip
MARKETING_NOISE_PATTERNS = [
    r"\b\d+%\s*(?:off|discount)\b",
    r"\b(?:free|fast|express|worldwide)\s+shipping\b",
    r"\bget\s+yours\s+(?:today|now)\b",
    r"\bmust[\s-]have\b",
    r"\blimited\s+(?:time|stock|offer|quantity|edition)\b",
    r"\border\s+now\b",
    r"\bshop\s+now\b",
    r"\bbuy\s+\d+\s+get\s+\d+\s*(?:free)?\b",
    r"\bclaim\s+yours\b",
    r"\blink\s+in\s+bio\b",
    r"\btap\s+to\s+shop\b",
    r"\bhurry\b",
    r"\bsale\s+ends?\s*(?:tonight|soon)?\b",
    r"\bwhile\s+supplies\s+last\b",
    r"\bexclusive\s+(?:deal|offer)\b",
    r"\bclick\s+here\b",
    r"\btik\s*tok\s*made\s*me\s*buy\s*it\b",
    r"\bamazon\s+finds?\b",
    r"\bviral\b",
    r"\bbest\s+seller\b",
    r"\btrending\b",
    r"\bpay\s+on\s+delivery\b",
    r"\bcash\s+on\s+delivery\b",
    r"\bhot\s+deal\b",
    r"\blowest\s+price\b",
    r"\bup\s+to\s+\d+%\s*off\b",
]

COMPILED_NOISE = [re.compile(p, re.IGNORECASE) for p in MARKETING_NOISE_PATTERNS]
URL_REGEX = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMOJI_REGEX = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\uD83C-\uDBFF\uDC00-\uDFFF]",
    flags=re.UNICODE,
)
NON_ALPHANUM_REGEX = re.compile(r"[#@&*^%$!~`+=_<>|/\\{}\[\]\"\'\(\)\:\;\-\–\—]+", re.UNICODE)


def extract_clean_product_title(raw_text: str, fallback: str = "Viral Product") -> str:
    """
    Strips noise, marketing buzzwords, emojis, and URLs to extract a clean product title.
    Example: "🔥 50% OFF! Sunset Projection Lamp Tik Tok Made Me Buy It 🔥"
             -> "Sunset Projection Lamp"
    """
    if not raw_text or not isinstance(raw_text, str):
        return fallback

    # 1. Strip URLs
    text = URL_REGEX.sub(" ", raw_text)
    # 2. Strip Emojis
    text = EMOJI_REGEX.sub(" ", text)
    # 3. Strip trademark / noise patterns
    for pat in COMPILED_NOISE:
        text = pat.sub(" ", text)
    # 4. Strip excessive punctuation
    text = NON_ALPHANUM_REGEX.sub(" ", text)
    # 5. Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return fallback

    # Extract 2-5 meaningful words
    tokens = [w for w in text.split() if len(w) > 1]
    filtered = [w for w in tokens if w.lower() not in COMMON_STOPWORDS]

    if len(filtered) >= 2:
        candidate = filtered[:4]
        return " ".join(candidate).title()
    elif tokens:
        return " ".join(tokens[:4]).title()

    return text[:40].strip().title() or fallback


def extract_high_intent_keywords(title: str, body: str = "") -> List[str]:
    """
    Extracts high buyer-intent keyword combinations for e-commerce search queries.
    Returns: List of optimized 2-3 word search phrases.
    """
    combined = f"{title} {body}"
    clean = extract_clean_product_title(combined)
    tokens = [w.lower() for w in clean.split() if len(w) > 2 and w.lower() not in COMMON_STOPWORDS]

    keywords: List[str] = []

    # 1. Full cleaned title
    if clean:
        keywords.append(clean.lower())

    # 2. 2-word and 3-word n-grams
    if len(tokens) >= 3:
        keywords.append(f"{tokens[0]} {tokens[1]} {tokens[2]}")
        keywords.append(f"{tokens[0]} {tokens[1]}")
        keywords.append(f"{tokens[1]} {tokens[2]}")
    elif len(tokens) == 2:
        keywords.append(f"{tokens[0]} {tokens[1]}")

    # Remove duplicates preserving order
    seen = set()
    result = []
    for kw in keywords:
        if kw not in seen and len(kw) > 3:
            seen.add(kw)
            result.append(kw)

    return result or [clean.lower() if clean else "dropshipping product"]


def generate_supplier_links(product_name_or_keyword: str) -> Dict[str, str]:
    """
    Generates clickable deep-search URLs across 9 supplier and marketplace platforms:
    - 1688
    - Alibaba
    - YiwuGo
    - AliExpress
    - CJ Dropshipping
    - IndiaMART
    - Meesho
    - Temu
    - Amazon
    """
    query = extract_clean_product_title(product_name_or_keyword)
    encoded = urllib.parse.quote_plus(query)

    return {
        "1688": f"https://s.1688.com/youyuan/index.htm?tab=all&cosite=baidujj&keywords={encoded}",
        "Alibaba": f"https://www.alibaba.com/trade/search?SearchText={encoded}",
        "YiwuGo": f"https://en.yiwugo.com/search/s.html?q={encoded}",
        "AliExpress": f"https://www.aliexpress.com/wholesale?SearchText={encoded}",
        "CJDropshipping": f"https://cjdropshipping.com/list/search.html?search={encoded}",
        "IndiaMART": f"https://dir.indiamart.com/search.mp?ss={encoded}",
        "Meesho": f"https://www.meesho.com/search?q={encoded}",
        "Temu": f"https://www.temu.com/search_result.html?search_key={encoded}",
        "Amazon": f"https://www.amazon.com/s?k={encoded}",
    }


def build_9_supplier_keyboard(
    clean_product_name: str,
    landing_page_url: Optional[str] = None,
    ad_library_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Constructs an organized Telegram inline keyboard with all 9 supplier platforms,
    plus direct Storefront and Meta Ad Library buttons.
    """
    links = generate_supplier_links(clean_product_name)

    keyboard = [
        # Row 1: China Factory Wholesale (Tier 1 B2B)
        [
            {"text": "🇨🇳 1688 Factory", "url": links["1688"]},
            {"text": "🏭 Alibaba", "url": links["Alibaba"]},
            {"text": "🏮 YiwuGo", "url": links["YiwuGo"]},
        ],
        # Row 2: Global Dropship & Fulfillment
        [
            {"text": "📦 AliExpress", "url": links["AliExpress"]},
            {"text": "🚚 CJ Dropship", "url": links["CJDropshipping"]},
            {"text": "⚡ Temu", "url": links["Temu"]},
        ],
        # Row 3: Domestic Sourcing & Retail Benchmarks
        [
            {"text": "🇮🇳 IndiaMART", "url": links["IndiaMART"]},
            {"text": "🛒 Meesho", "url": links["Meesho"]},
            {"text": "🛍️ Amazon", "url": links["Amazon"]},
        ],
    ]

    # Row 4: Storefront & Ad Creative links
    row_media = []
    if landing_page_url and landing_page_url.startswith("http"):
        row_media.append({"text": "🌐 Live Storefront", "url": landing_page_url})
    if ad_library_url and ad_library_url.startswith("http"):
        row_media.append({"text": "🎬 Ad Creative", "url": ad_library_url})
    if row_media:
        keyboard.append(row_media)

    return {"inline_keyboard": keyboard}


def format_supplier_markdown_links(clean_product_name: str) -> str:
    """
    Returns formatted clickable Markdown links for the 9 supplier platforms
    for inclusion in Telegram messages, reports, or CLI outputs.
    """
    links = generate_supplier_links(clean_product_name)
    return (
        f"🔗 *1-Click Sourcing & Supplier Links:*\n"
        f"• *Factory Wholesale:* [1688]({links['1688']}) | [Alibaba]({links['Alibaba']}) | [YiwuGo]({links['YiwuGo']})\n"
        f"• *Dropshipping:* [AliExpress]({links['AliExpress']}) | [CJ Dropshipping]({links['CJDropshipping']}) | [Temu]({links['Temu']})\n"
        f"• *Domestic & Retail:* [IndiaMART]({links['IndiaMART']}) | [Meesho]({links['Meesho']}) | [Amazon]({links['Amazon']})"
    )
