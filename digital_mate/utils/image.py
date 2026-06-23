"""Image processing utilities for Telegram bot vision capability.

Provides helpers to download, resize, and base64-encode images so they
can be sent to vision-capable LLM endpoints.
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum image dimension (width or height) before resizing.
MAX_IMAGE_DIMENSION = 1024

# Approximate maximum base64 payload size (~1 MB).
MAX_BASE64_SIZE = 1_000_000


def encode_image_file(path: str | Path) -> tuple[str, str]:
    """Read an image file, resize if needed, and return base64 + MIME type.

    Uses Pillow (PIL) when available to resize large images to a maximum
    of 1024×1024 (maintaining aspect ratio) and convert to JPEG.  If PIL
    is not installed, the raw file bytes are base64-encoded as-is and the
    MIME type is guessed from the file extension.

    Args:
        path: Path to the image file on disk.

    Returns:
        A tuple of ``(base64_string, mime_type)`` where *mime_type* is
        typically ``"image/jpeg"`` (when PIL processed the image) or
        ``"image/png"`` / ``"image/webp"`` (raw fallback).

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file is empty.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image file not found: {p}")

    raw = p.read_bytes()
    if not raw:
        raise ValueError("Image file is empty.")

    try:
        from PIL import Image

        img = Image.open(p)
        # Convert to RGB (strip alpha for JPEG)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if larger than MAX_IMAGE_DIMENSION (maintain aspect ratio)
        w, h = img.size
        if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
            ratio = min(MAX_IMAGE_DIMENSION / w, MAX_IMAGE_DIMENSION / h)
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            logger.info("Resized image from %dx%d to %dx%d", w, h, new_w, new_h)

        # Save as JPEG into a temporary buffer
        import io
        buf = io.BytesIO()
        quality = 85
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()

        # If still too large, reduce quality iteratively
        while len(data) > MAX_BASE64_SIZE * 3 // 4 and quality > 30:
            quality -= 10
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            data = buf.getvalue()

        b64 = base64.b64encode(data).decode("ascii")
        logger.info(
            "Encoded image: %d bytes → %d base64 chars (JPEG quality=%d)",
            len(data), len(b64), quality,
        )
        return b64, "image/jpeg"

    except ImportError:
        # PIL not available — encode raw bytes
        logger.warning("Pillow not available — encoding raw image bytes without resize")
        b64 = base64.b64encode(raw).decode("ascii")

        # Guess MIME from extension
        ext = p.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/jpeg")
        return b64, mime


def encode_image_bytes(data: bytes) -> tuple[str, str]:
    """Encode raw image bytes to base64, resizing with PIL if available.

    Writes the bytes to a temporary file, processes with
    :func:`encode_image_file`, and cleans up.

    Args:
        data: Raw image bytes (e.g. from a Telegram download).

    Returns:
        A tuple of ``(base64_string, mime_type)``.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        return encode_image_file(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
