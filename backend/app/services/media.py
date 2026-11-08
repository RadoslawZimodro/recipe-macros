"""Local storage of step images: type detection by content, generated names, safe deletion.

Only the file name (`<uuid hex>.<ext>`) is stored in the database; the directory comes from
MEDIA_DIR. Names are never taken from a URL or from the client, so there is no path to traverse.
"""

import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# Same pattern as the CHECK constraint on recipe_steps.image_path.
_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|gif)$")


@dataclass(frozen=True)
class StoredImage:
    name: str  # file name inside MEDIA_DIR
    content_type: str


def detect_image(data: bytes) -> tuple[str, str] | None:
    """(extension, content type) from the first bytes, or None. SVG and anything else: None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    return None


def save_image(data: bytes) -> StoredImage | None:
    """Write `data` under a fresh name; None if it is not a supported image."""
    detected = detect_image(data)
    if detected is None:
        return None
    ext, content_type = detected
    directory = Path(get_settings().media_dir)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    # Write next to the target and rename: a crash never leaves a half-written picture under a
    # servable name. "<name>.tmp" does not match _NAME, so it is never served or deleted as one.
    tmp = directory / f"{name}.tmp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, directory / name)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return StoredImage(name, content_type)


def image_file(name: str) -> Path | None:
    """The path of a stored image, or None if the name is malformed or the file is gone."""
    if not _NAME.fullmatch(name):
        return None
    path = Path(get_settings().media_dir) / name
    return path if path.is_file() else None


def delete_images(names: list[str]) -> None:
    """Best effort: a file that cannot be removed is logged, never raised (the DB is the truth)."""
    for name in names:
        if not _NAME.fullmatch(name):
            continue
        try:
            (Path(get_settings().media_dir) / name).unlink(missing_ok=True)
        except OSError:
            logger.warning("media_delete_failed name=%s", name)
