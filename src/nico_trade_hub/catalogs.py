"""! Normalización de países y catálogos auxiliares."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pycountry

from .utils import normalize_text


@dataclass(slots=True)
class CountryCatalog:
    """! Resuelve nombres canónicos de países."""

    alias_map: dict[str, tuple[str, str | None]]

    @classmethod
    def from_csv(cls, path: Path) -> "CountryCatalog":
        df = pd.read_csv(path)
        alias_map: dict[str, tuple[str, str | None]] = {}
        for row in df.to_dict(orient="records"):
            raw = normalize_text(row["raw_name"]).lower()
            alias_map[raw] = (
                normalize_text(row["canonical_name"]),
                None if pd.isna(row.get("iso3")) else str(row.get("iso3") or "").strip() or None,
            )
        return cls(alias_map=alias_map)

    def normalize(self, raw_name: object) -> tuple[str, str | None]:
        """! Normaliza nombre de país a nombre canónico e ISO3 cuando sea posible."""
        text = normalize_text(raw_name)
        key = text.lower()
        if key in self.alias_map:
            return self.alias_map[key]

        try:
            match = pycountry.countries.lookup(text)
            canonical = getattr(match, "name", text)
            iso3 = getattr(match, "alpha_3", None)
            return canonical, iso3
        except LookupError:
            return text, None
