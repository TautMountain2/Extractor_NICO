"""! Configuración de logs."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_dir: Path) -> None:
    """! Configura logging básico a archivo y consola."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "nico_trade_hub.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
