"""
Perceptual image hashing and visual similarity matcher.
Used to detect products on Indian marketplaces that are sold under disguised, generic, or altered titles.
"""

import io
import logging
from typing import List, Optional, Tuple
import httpx

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False

logger = logging.getLogger("TrendArbitrage.ImageMatcher")


def _calculate_pil_dhash(img: object) -> int:
    """Computes a 64-bit difference hash (dHash) using pure PIL without external imagehash."""
    # Convert to grayscale and resize to 9x8
    resized = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(resized.getdata())
    diff = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            diff = (diff << 1) | (1 if left > right else 0)
    return diff


def _hamming_distance(hash1: int, hash2: int) -> int:
    """Calculates hamming distance between two 64-bit integers."""
    return bin(hash1 ^ hash2).count("1")


async def download_image(url: str, timeout: float = 10.0) -> Optional[object]:
    """Asynchronously downloads an image from a URL and parses it with PIL if available."""
    if not url or not url.startswith("http") or not HAS_PIL:
        return None
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.content:
                img = Image.open(io.BytesIO(resp.content))
                return img.convert("RGB")
    except Exception as exc:
        logger.debug(f"Failed to download image from {url}: {exc}")
    return None


def calculate_perceptual_similarity(img1: object, img2: object) -> float:
    """
    Computes visual similarity between two PIL images using a hybrid of
    Difference Hash (dHash) and Perceptual Hash (pHash).
    Falls back to pure-PIL dHash if imagehash library is not installed.
    Returns similarity between 0.0 (completely distinct) and 1.0 (identical).
    """
    if not HAS_PIL or img1 is None or img2 is None:
        return 0.0

    try:
        # Resize images to standard 128x128 for consistent comparison
        res1 = img1.resize((128, 128), Image.Resampling.LANCZOS)
        res2 = img2.resize((128, 128), Image.Resampling.LANCZOS)

        if HAS_IMAGEHASH:
            # 1. Perceptual Hash (DCT-based, resilient to color changes and compression)
            phash1 = imagehash.phash(res1)
            phash2 = imagehash.phash(res2)
            phash_diff = phash1 - phash2  # Hamming distance (0 to 64)

            # 2. Difference Hash (gradient-based, resilient to brightness/contrast adjustments)
            dhash1 = imagehash.dhash(res1)
            dhash2 = imagehash.dhash(res2)
            dhash_diff = dhash1 - dhash2  # Hamming distance (0 to 64)

            # Average distance
            avg_diff = (phash_diff * 0.6) + (dhash_diff * 0.4)
            similarity = max(0.0, 1.0 - (avg_diff / 64.0))
            return round(similarity, 4)
        else:
            # Pure PIL dHash fallback
            h1 = _calculate_pil_dhash(res1)
            h2 = _calculate_pil_dhash(res2)
            dist = _hamming_distance(h1, h2)
            similarity = max(0.0, 1.0 - (dist / 64.0))
            return round(similarity, 4)
    except Exception as exc:
        logger.debug(f"Error computing image similarity: {exc}")
        return 0.0


async def check_visual_saturation_matches(
    target_image_url: Optional[str],
    marketplace_image_urls: List[str],
    similarity_threshold: float = 0.80,
    max_candidates_to_check: int = 8
) -> Tuple[int, List[str]]:
    """
    Compares the target dropshipping ad thumbnail against top candidate images found on
    Indian marketplaces. Returns count of matches exceeding the similarity threshold.
    """
    if not target_image_url or not marketplace_image_urls:
        return 0, []

    target_img = await download_image(target_image_url)
    if target_img is None:
        return 0, []

    matched_urls: List[str] = []
    candidates = marketplace_image_urls[:max_candidates_to_check]

    for cand_url in candidates:
        if not cand_url:
            continue
        cand_img = await download_image(cand_url)
        if cand_img is None:
            continue

        sim = calculate_perceptual_similarity(target_img, cand_img)
        if sim >= similarity_threshold:
            logger.info(f"Visual match found! Score: {sim:.2f} (Threshold: {similarity_threshold})")
            matched_urls.append(cand_url)

    return len(matched_urls), matched_urls
