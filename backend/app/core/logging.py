import logging
import sys

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """
    Configure application logging from backend settings.
    """
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )

    logging.getLogger("uvicorn").setLevel(settings.log_level)
    logging.getLogger("uvicorn.error").setLevel(settings.log_level)
    logging.getLogger("uvicorn.access").setLevel(settings.log_level)
