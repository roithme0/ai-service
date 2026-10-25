"""Application logging setup."""

import logging


def configure_logging() -> None:
    application_logger = logging.getLogger("app")
    if application_logger.level == logging.NOTSET:
        application_logger.setLevel(logging.INFO)
    if not application_logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        application_logger.addHandler(handler)
