"""Download the cover and step pictures of a recipe (best effort: a failure loses only that one)."""

import logging
import time

from app.config import get_settings
from app.services.media import StoredImage, delete_images, save_image
from app.services.page_fetcher import PageFetcher
from app.services.safe_fetch import FetchError

logger = logging.getLogger(__name__)


def new_deadline() -> float:
    """The end of the shared time budget of the whole picture phase (cover first, then steps)."""
    return time.monotonic() + get_settings().image_total_budget_sec


def _download(fetcher: PageFetcher, url: str, remaining: float, what: str) -> StoredImage | None:
    try:
        return save_image(fetcher.fetch_image(url, timeout=remaining).body)
    except FetchError as exc:
        logger.info("%s_failed code=%s", what, exc.code)
    except OSError:
        logger.exception("%s_not_saved", what)
    return None


def download_cover(fetcher: PageFetcher, url: str | None, deadline: float) -> StoredImage | None:
    """The stored photo of the dish, or None (no address, out of time, or the download failed)."""
    remaining = deadline - time.monotonic()
    if url is None or remaining <= 0:
        return None
    return _download(fetcher, url, remaining, "cover")


def download_step_images(
    fetcher: PageFetcher, urls: tuple[str | None, ...], deadline: float | None = None
) -> tuple[list[StoredImage | None], int]:
    """One stored image (or None) per step, and how many pictures could not be kept.

    Limits: `image_max_per_recipe` pictures, `image_max_bytes` each, `image_total_budget_sec`
    for all of them together. Anything over a limit or failing is counted as skipped.
    """
    settings = get_settings()
    deadline = deadline if deadline is not None else new_deadline()
    stored: list[StoredImage | None] = []
    skipped = attempted = 0
    for url in urls:
        if url is None:
            stored.append(None)
            continue
        remaining = deadline - time.monotonic()
        if attempted >= settings.image_max_per_recipe or remaining <= 0:
            stored.append(None)
            skipped += 1
            continue
        attempted += 1
        image = _download(fetcher, url, remaining, "step_image")
        if image is None:
            skipped += 1
        stored.append(image)
    return stored, skipped


def names(images: list[StoredImage | None]) -> list[str]:
    return [i.name for i in images if i is not None]


def discard(images: list[StoredImage | None]) -> None:
    delete_images(names(images))
