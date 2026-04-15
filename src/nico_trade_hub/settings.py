"""! Carga de configuración del proyecto."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class Settings:
    """! Contenedor simple de configuración."""

    root: Path
    raw: dict[str, Any]

    @property
    def database_path(self) -> Path:
        return self.root / self.raw["paths"]["database"]

    @property
    def bronze_dir(self) -> Path:
        return self.root / self.raw["paths"]["bronze_dir"]

    @property
    def inbox_dir(self) -> Path:
        return self.root / self.raw["paths"]["inbox_dir"]

    @property
    def export_dir(self) -> Path:
        return self.root / self.raw["paths"]["export_dir"]

    @property
    def log_dir(self) -> Path:
        return self.root / self.raw["paths"]["log_dir"]

    @property
    def selector_map_path(self) -> Path:
        return self.root / self.raw["paths"]["selector_map"]

    @property
    def country_aliases_path(self) -> Path:
        return self.root / self.raw["paths"]["country_aliases"]

    @property
    def start_month(self) -> str:
        return self.raw["project"]["start_month"]

    @property
    def source_config(self) -> dict[str, Any]:
        return self.raw["sources"]["inegi_bcmm"]


def project_root() -> Path:
    """! Resuelve la raíz del proyecto."""
    return Path(__file__).resolve().parents[2]


def load_settings(root: Path | None = None) -> Settings:
    """! Carga `config/app.yaml`.

    @param root Ruta raíz del proyecto.
    @return Settings cargado.
    """
    root = root or project_root()
    config_path = root / "config" / "app.yaml"
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    settings = Settings(root=root, raw=raw)
    for directory in [settings.bronze_dir, settings.inbox_dir, settings.export_dir, settings.log_dir, settings.database_path.parent]:
        directory.mkdir(parents=True, exist_ok=True)
    return settings
