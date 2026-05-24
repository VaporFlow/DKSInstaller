from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .config import get_local_appdata_dir


def get_log_dir() -> Path:
    log_dir = get_local_appdata_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file_path() -> Path:
    return get_log_dir() / "dks_installer.log"


class _UiCallbackHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self.callback(message)
        except Exception:  # pragma: no cover
            self.handleError(record)


def setup_logger(
    name: str = "dks_installer",
    ui_callback: Callable[[str], None] | None = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(get_log_file_path(), encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    if ui_callback is not None:
        ui_handler = _UiCallbackHandler(ui_callback)
        ui_handler.setFormatter(formatter)
        ui_handler.setLevel(logging.INFO)
        logger.addHandler(ui_handler)

    logger.propagate = False
    return logger
