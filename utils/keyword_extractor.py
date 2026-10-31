"""
Enhanced Keyword Cleaning, Sanitization, and Token Overlap Analyzer.
Strips marketing buzzwords, emojis, trademark symbols, and extracts core 2-3 word product phrases.
"""

import re
from typing import List, Set, Tuple

# Comprehensive dropshipping noise and promotional triggers
MARKETING_BUZZWORDS = [
    r"\b\d+%\s*(?:off|discount)\b",
    r"\b(?:free|express|worldwide)\s+shipping\b",
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
    r"\bviral\b",
    r"\bbest\s+seller\b",
    r"\btrending\b",
    r"\bpay\s+on\s+delivery\b",
    r"\bcash\s+on\s+delivery\b",
    r"\bhot\s+deal\b",
    r"\blowest\s+price\b",
    r"\bup\s+to\s+\d+%\s*off\b",
]

COMPILED_BUZZWORDS = [re.compile(p, re.IGNORECASE) for p in MARKETING_BUZZWORDS]
URL_REGEX = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMOJI_REGEX = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\uD83C-\uDBFF\uDC00-\uDFFF]",
    flags=re.UNICODE,
)
TRADEMARK_SYMBOLS_REGEX = re.compile(r"[™®©℠℗]", re.UNICODE)
NON_ALPHANUM_REGEX = re.compile(r"[#@&*^%$!~`+=_<>|/\\{}\[\]\"\'\(\)\:\;\-\–\—]+", re.UNICODE)

COMMON_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "is", "are", "was",
    "were", "with", "for", "and", "or", "to", "in", "on", "at", "by", "from",
    "up", "your", "our", "my", "you", "we", "it", "its", "so", "just", "best",
    "new", "make", "more", "now", "here", "there", "why", "how", "what", "all",
    "pro", "ultra", "mini", "portable", "super", "easy", "perfect", "smart"
}


def sanitize_text(text: str) -> str:
    """
    Strips marketing buzzwords, emojis, URLs, and trademark symbols from raw text.
    """
    if not text:
        return ""
    
    # 1. Strip URLs and emails
    cleaned = URL_REGEX.sub(" ", text)
    # 2. Strip emojis
    cleaned = EMOJI_REGEX.sub(" ", cleaned)
    # 3. Strip trademark and copyright symbols (™, ®, ©)
    cleaned = TRADEMARK_SYMBOLS_REGEX.sub(" ", cleaned)
    # 4. Strip marketing buzzwords
    for pat in COMPILED_BUZZWORDS:
        cleaned = pat.sub(" ", cleaned)
    # 5. Clean non-alphanumeric punctuation
    cleaned = NON_ALPHANUM_REGEX.sub(" ", cleaned)
    # 6. Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_core_2_3_word_phrase(sanitized_text: str) -> str:
    """
    Extracts the core 2-3 word noun phrase for precise marketplace search matching.
    Filters out common marketing descriptors and adjectives.
    """
    tokens = [w for w in sanitized_text.split() if len(w) > 1]
    filtered = [w for w in tokens if w.lower() not in COMMON_STOPWORDS]

    # If filtered tokens has at least 2 words, select the core 2 or 3
    if len(filtered) >= 2:
        candidate = filtered[:3]
        return " ".join(candidate).title()
    elif tokens:
        return " ".join(tokens[:3]).title()
    return sanitized_text[:30].strip().title()


def extract_core_keywords(title: str, body: str = "") -> Tuple[str, List[str]]:
    """
    Sanitizes ad copy and extracts clean product entity and target search variants.
    """
    clean_title = sanitize_text(title)
    clean_body = sanitize_text(body)

    clean_phrase = extract_core_2_3_word_phrase(clean_title)
    if not clean_phrase and clean_body:
        clean_phrase = extract_core_2_3_word_phrase(clean_body)

    if not clean_phrase:
        clean_phrase = "Trending Product"

    # Generate targeted search variants (full 2-3 word phrase, 2-word variant)
    words = clean_phrase.split()
    queries = [clean_phrase]
    if len(words) >= 3:
        queries.append(" ".join(words[:2]))
        queries.append(" ".join(words[-2:]))
    elif len(words) == 2:
        queries.append(words[0])

    unique_queries = list(dict.fromkeys([q.strip() for q in queries if len(q.strip()) > 2]))
    return clean_phrase, unique_queries


# ======================================================================================
# Meesho Fallback & Token Overlap Detection
# ======================================================================================

def tokenize(text: str) -> Set[str]:
    """Tokenizes text into a normalized lowercase word set."""
    if not text:
        return set()
    clean = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return {w for w in clean.split() if len(w) > 1 and w not in COMMON_STOPWORDS}


def calculate_token_overlap(query: str, candidate_title: str) -> float:
    """
    Calculates token intersection ratio against the query:
    |Query_Tokens ∩ Title_Tokens| / |Query_Tokens|
    """
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.0
    cand_tokens = tokenize(candidate_title)
    if not cand_tokens:
        return 0.0
    common = q_tokens.intersection(cand_tokens)
    return len(common) / len(q_tokens)


def calculate_jaccard_similarity(query: str, candidate_title: str) -> float:
    """
    Calculates Jaccard similarity:
    |Query ∩ Title| / |Query ∪ Title|
    """
    q_tokens = tokenize(query)
    c_tokens = tokenize(candidate_title)
    if not q_tokens or not c_tokens:
        return 0.0
    intersection = len(q_tokens.intersection(c_tokens))
    union = len(q_tokens.union(c_tokens))
    return intersection / union if union > 0 else 0.0


def is_meesho_algorithmic_fallback(query: str, candidate_titles: List[str], threshold: float = 0.20) -> bool:
    """
    Detects if Meesho's search returned irrelevant fallback/popular items when the query
    has 0 actual results.
    
    If the average token overlap across top candidate items is < 20% (threshold),
    or if fewer than 10% of items share any token with the query, it is marked as
    an algorithmic fallback (True Virgin).
    """
    if not candidate_titles:
        return True  # 0 results = True Virgin

    q_tokens = tokenize(query)
    if not q_tokens:
        return False

    overlapping_items = 0
    total_overlap_score = 0.0

    for title in candidate_titles:
        overlap = calculate_token_overlap(query, title)
        total_overlap_score += overlap
        if overlap >= threshold:
            overlapping_items += 1

    avg_overlap = total_overlap_score / len(candidate_titles)
    overlap_item_ratio = overlapping_items / len(candidate_titles)

    # If average overlap is under 20% or less than 15% of items have matching tokens,
    # it is an algorithmic fallback to unrelated popular catalogs (sarees, watches, etc.)
    return avg_overlap < threshold or overlap_item_ratio < 0.15
