"""
Media Asset Grabber Module (media_extractor.py).
Extracts direct MP4 video CDN links and high-res image assets from Meta Ad Library JSON snapshots.
Streams media safely into a temporary directory (with a 25MB file-size safety cap) and
provides post-send cleanup.
"""

import asyncio
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid
import httpx

logger = logging.getLogger("TrendArbitrage.MediaExtractor")

TEMP_MEDIA_DIR = Path("./temp_media")
MAX_TELEGRAM_MEDIA_BYTES = 48 * 1024 * 1024  # 48 MB limit (Telegram Bot API allows up to 50MB)


class MediaAssetExtractor:
    """Handles extracting, streaming, and caching ad creative videos and photos."""

    def __init__(self, temp_dir: Path = TEMP_MEDIA_DIR):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def extract_direct_urls_from_snapshot(self, snapshot: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Parses direct CDN source URLs for both playable MP4 videos (HD/SD)
        and high-resolution original preview images from Meta snapshot dictionaries.
        Returns:
            (video_mp4_url, high_res_image_url)
        """
        if not snapshot or not isinstance(snapshot, dict):
            return None, None

        video_url: Optional[str] = None
        image_url: Optional[str] = None

        # 1. Search top-level videos array
        videos = snapshot.get("videos", [])
        if videos and isinstance(videos, list):
            for v in videos:
                if not isinstance(v, dict):
                    continue
                # Prefer HD playable MP4, fallback to SD MP4
                v_cand = v.get("video_hd_url") or v.get("video_sd_url")
                if v_cand and ("http" in v_cand):
                    video_url = v_cand
                # Preview image fallback
                preview = v.get("video_preview_image_url")
                if preview and not image_url:
                    image_url = preview
                if video_url:
                    break

        # 2. Search top-level images array
        images = snapshot.get("images", [])
        if images and isinstance(images, list):
            for img in images:
                if not isinstance(img, dict):
                    continue
                img_cand = img.get("original_image_url") or img.get("resized_image_url")
                if img_cand and ("http" in img_cand):
                    image_url = img_cand
                    break

        # 3. Check carousel cards if top-level has no media
        cards = snapshot.get("cards", [])
        if cards and isinstance(cards, list):
            for card in cards:
                if not isinstance(card, dict):
                    continue
                if not video_url:
                    card_v = card.get("video_hd_url") or card.get("video_sd_url")
                    if card_v and ("http" in card_v):
                        video_url = card_v
                if not image_url:
                    card_img = card.get("original_image_url") or card.get("resized_image_url") or card.get("video_preview_image_url")
                    if card_img and ("http" in card_img):
                        image_url = card_img
                if video_url and image_url:
                    break

        return video_url, image_url

    async def stream_and_download_media(
        self,
        media_url: str,
        is_video: bool = False,
        timeout_seconds: float = 20.0
    ) -> Optional[Path]:
        """
        Streams media into `./temp_media/` with chunked writing and size validation.
        Enforces a 25MB safety cap (Telegram API limit). Returns local Path if successful.
        """
        if not media_url or not media_url.startswith("http"):
            return None

        ext = ".mp4" if is_video else ".jpg"
        unique_name = f"{'vid' if is_video else 'img'}_{uuid.uuid4().hex[:10]}{ext}"
        target_path = self.temp_dir / unique_name

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "video/mp4,video/*,image/*,*/*;q=0.8",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
                async with client.stream("GET", media_url) as response:
                    if response.status_code != 200:
                        logger.warning(f"[Media] Upstream returned status {response.status_code} for {media_url[:60]}")
                        return None

                    # Check Content-Length header if reported
                    content_len_header = response.headers.get("content-length")
                    if content_len_header:
                        try:
                            total_bytes = int(content_len_header)
                            if total_bytes > MAX_TELEGRAM_MEDIA_BYTES:
                                logger.warning(f"[Media] File size ({total_bytes / (1024*1024):.1f}MB) exceeds 25MB cap. Skipping stream.")
                                return None
                        except ValueError:
                            pass

                    # Stream download chunks
                    downloaded_bytes = 0
                    with open(target_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > MAX_TELEGRAM_MEDIA_BYTES:
                                logger.warning(f"[Media] Stream exceeded 25MB safety threshold. Aborting download.")
                                f.close()
                                self.cleanup_file(target_path)
                                return None
                            f.write(chunk)

            if target_path.exists() and target_path.stat().st_size > 500:
                logger.info(f"[Media] Downloaded {'video' if is_video else 'image'} ({target_path.stat().st_size / 1024:.1f} KB) -> {target_path.name}")
                return target_path

        except Exception as exc:
            logger.error(f"[Media] Download exception for {media_url[:60]}: {exc}")
            self.cleanup_file(target_path)

        return None

    def cleanup_file(self, file_path: Optional[Path]) -> None:
        """Deletes a local temporary media file once successfully sent."""
        if file_path and isinstance(file_path, Path) and file_path.exists():
            try:
                file_path.unlink()
                logger.debug(f"[Media] Cleaned up temporary file: {file_path.name}")
            except Exception as exc:
                logger.debug(f"[Media] Cleanup error: {exc}")


# Global singleton instance
media_extractor = MediaAssetExtractor()
