"""Download the pictures of a recipe's steps (best effort: a failure only loses that picture)."""

import logging
import time

from app.config import get_settings
from app.services.media import StoredImage, delete_images, save_image
from app.services.page_fetcher import PageFetcher
from app.services.safe_fetch import FetchError

logger = logging.getLogger(__name__)


def download_step_images(
    fetcher: PageFetcher, urls: tuple[str | None, ...]
) -> tuple[list[StoredImage | None], int]:
    """One stored image (or None) per step, and how many pictures could not be kept.

    Limits: `image_max_per_recipe` pictures, `image_max_bytes` each, `image_total_budget_sec`
    for all of them together. Anything over a limit or failing is counted as skipped.
    """
    settings = get_settings()
    deadline = time.monotonic() + settings.image_total_budget_sec
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
        image = None
        try:
            image = save_image(fetcher.fetch_image(url, timeout=remaining).body)
        except FetchError as exc:
            logger.info("step_image_failed code=%s", exc.code)
        except OSError:
            logger.exception("step_image_not_saved")
        if image is None:
            skipped += 1
        stored.append(image)
    return stored, skipped


def names(images: list[StoredImage | None]) -> list[str]:
    return [i.name for i in images if i is not None]


def discard(images: list[StoredImage | None]) -> None:
    delete_images(names(images))
