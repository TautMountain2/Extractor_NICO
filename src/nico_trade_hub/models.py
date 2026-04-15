"""! Modelos de datos del dominio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class TradeObservation:
    """! Observación canónica mensual de comercio exterior."""

    date_month: date
    year: int
    month: int
    flow_code: str
    country_name: str
    country_iso3: str | None
    tariff_code: str
    tariff_level: int
    hs2: str | None
    hs4: str | None
    hs6: str | None
    fraccion8: str | None
    nico10: str | None
    tariff_description: str | None
    unit_name: str | None
    quantity: float | None
    value_usd: float | None
    source_code: str
    source_file: str | None
    source_revision: str | None
    load_run_id: int | None = None
    inserted_at: datetime | None = None
    updated_at: datetime | None = None

    def as_record(self) -> dict[str, Any]:
        """! Serializa el objeto a diccionario."""
        return {
            "date_month": self.date_month,
            "year": self.year,
            "month": self.month,
            "flow_code": self.flow_code,
            "country_name": self.country_name,
            "country_iso3": self.country_iso3,
            "tariff_code": self.tariff_code,
            "tariff_level": self.tariff_level,
            "hs2": self.hs2,
            "hs4": self.hs4,
            "hs6": self.hs6,
            "fraccion8": self.fraccion8,
            "nico10": self.nico10,
            "tariff_description": self.tariff_description,
            "unit_name": self.unit_name,
            "quantity": self.quantity,
            "value_usd": self.value_usd,
            "source_code": self.source_code,
            "source_file": self.source_file,
            "source_revision": self.source_revision,
            "load_run_id": self.load_run_id,
        }
