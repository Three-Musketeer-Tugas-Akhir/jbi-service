import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.config import settings

logger = logging.getLogger(__name__)

DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB chunks


class DownloadError(Exception):
    """Raised when a video URL download fails."""
    pass


def download_video(url: str, dest_path: str) -> int:
    """Download a video from a URL to a local file path."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
    except requests.ConnectionError:
        raise DownloadError(f"Cannot connect to URL: {url}")
    except requests.Timeout:
        raise DownloadError(f"Connection timed out: {url}")
    except requests.HTTPError as exc:
        raise DownloadError(f"URL returned HTTP {exc.response.status_code}")

    max_bytes = settings.max_upload_size_bytes
    downloaded = 0

    try:
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise DownloadError(
                            f"Download exceeds maximum size of "
                            f"{settings.max_upload_size_mb} MB"
                        )
                    f.write(chunk)
    except DownloadError:
        Path(dest_path).unlink(missing_ok=True)
        raise
    except IOError as exc:
        Path(dest_path).unlink(missing_ok=True)
        raise DownloadError(f"Failed to write file: {exc}")

    logger.info("Downloaded %d bytes from %s", downloaded, url)
    return downloaded


def infer_extension(url: str) -> str:
    """Infer file extension from a URL path or default to .mp4."""
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()

    if path_ext in settings.allowed_extensions_list:
        return path_ext

    return ".mp4"
