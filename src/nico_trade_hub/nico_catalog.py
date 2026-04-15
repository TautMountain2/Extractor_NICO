"""Catálogo de NICO desde el Excel oficial."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .utils import normalize_text


@dataclass(slots=True)
class NicoCatalogRow:
    fraccion8: str
    nico: str
    nico10: str
    description: str

    def as_record(self) -> dict[str, str]:
        return {
            "fraccion8": self.fraccion8,
            "nico": self.nico,
            "nico10": self.nico10,
            "description": self.description,
        }


class NicoCatalogLoader:
    """Convierte el Excel maestro de NICO a filas canónicas."""

    def load(self, path: Path) -> list[NicoCatalogRow]:
        raw = pd.read_excel(path, header=None)
        header_row = self._find_header_row(raw)
        body = raw.iloc[header_row + 1 :].copy()
        body.columns = [normalize_text(v).upper() for v in raw.iloc[header_row].tolist()]
        rename_map = {
            "FRACCION ARANCELARIA": "fraccion",
            "FRACCIÓN ARANCELARIA": "fraccion",
            "NICO": "nico",
            "DESCRIPCION": "description",
            "DESCRIPCIÓN": "description",
        }
        body = body.rename(columns=rename_map)
        required = {"fraccion", "nico", "description"}
        if not required.issubset(set(body.columns)):
            raise ValueError(f"No se detectaron columnas requeridas en {path.name}")

        body = body[["fraccion", "nico", "description"]].dropna(how="all")
        rows: list[NicoCatalogRow] = []
        for item in body.to_dict(orient="records"):
            fraccion = self._digits(item["fraccion"])
            nico = self._digits(item["nico"]).zfill(2)
            description = normalize_text(item["description"])
            if len(fraccion) != 8 or len(nico) != 2 or not description:
                continue
            rows.append(
                NicoCatalogRow(
                    fraccion8=fraccion,
                    nico=nico,
                    nico10=f"{fraccion}{nico}",
                    description=description,
                )
            )
        if not rows:
            raise ValueError(f"No se pudieron extraer filas válidas del catálogo NICO: {path.name}")
        return rows

    def _find_header_row(self, raw: pd.DataFrame) -> int:
        for idx in range(min(len(raw), 15)):
            keys = {normalize_text(v).upper() for v in raw.iloc[idx].tolist() if pd.notna(v)}
            if "NICO" in keys and any(k in keys for k in ["FRACCIÓN ARANCELARIA", "FRACCION ARANCELARIA"]):
                return idx
        raise ValueError("No se encontró la fila de encabezados del catálogo NICO")

    def _digits(self, value: object) -> str:
        text = normalize_text(value)
        return "".join(ch for ch in text if ch.isdigit())
