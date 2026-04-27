"""Normalización robusta de países y agregados comerciales."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pycountry

from .utils import normalize_text


@dataclass(frozen=True, slots=True)
class CountryResolution:
    canonical_name: str
    iso3: str | None
    iso2: str | None = None
    is_aggregate: bool = False
    aggregate_kind: str | None = None
    source: str = "catalog"


@dataclass(slots=True)
class CountryCatalog:
    """Resuelve nombres canónicos de países y agregados.

    Mantiene compatibilidad con el resto del proyecto: ``normalize`` sigue
    devolviendo ``(canonical_name, iso3)``.
    """

    alias_map: dict[str, CountryResolution]

    @classmethod
    def from_csv(cls, path: Path) -> "CountryCatalog":
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]

        alias_map: dict[str, CountryResolution] = {}
        for row in df.to_dict(orient="records"):
            raw_display = _clean_text(row.get("raw_name"))
            raw = normalize_text(raw_display)
            if not raw:
                continue

            canonical_name = _clean_text(
                row.get("canonical_name_es")
                or row.get("canonical_name")
                or row.get("canonical_name_en")
                or raw_display
            )
            iso2 = _clean_code(row.get("iso2"))
            iso3 = _clean_code(row.get("iso3"))
            is_aggregate = _to_bool(row.get("is_aggregate"))
            aggregate_kind = _clean_text(row.get("aggregate_kind")) or None
            source = _clean_text(row.get("source")) or "catalog"
            priority = _to_int(row.get("priority"), default=100)

            resolution = CountryResolution(
                canonical_name=canonical_name,
                iso3=iso3,
                iso2=iso2,
                is_aggregate=is_aggregate,
                aggregate_kind=aggregate_kind,
                source=source,
            )
            _register_alias(alias_map, raw_display, resolution, priority)

            if canonical_name:
                _register_alias(alias_map, canonical_name, resolution, priority)

        return cls(alias_map=alias_map)

    def resolve(self, raw_name: object) -> CountryResolution:
        text = normalize_text(raw_name)
        if not text:
            return CountryResolution(canonical_name="", iso3=None, source="empty")

        key = _norm_key(text)
        explicit = self.alias_map.get(key)
        if explicit is not None:
            return explicit

        for candidate in _pycountry_candidates(text):
            key = _norm_key(candidate)
            explicit = self.alias_map.get(key)
            if explicit is not None:
                return explicit

        try:
            match = pycountry.countries.lookup(text)
            canonical = getattr(match, "name", text)
            iso3 = getattr(match, "alpha_3", None)
            iso2 = getattr(match, "alpha_2", None)
            return CountryResolution(
                canonical_name=canonical,
                iso3=iso3,
                iso2=iso2,
                is_aggregate=False,
                aggregate_kind=None,
                source="pycountry",
            )
        except LookupError:
            return CountryResolution(
                canonical_name=text,
                iso3=None,
                iso2=None,
                is_aggregate=False,
                aggregate_kind=None,
                source="raw",
            )

    def normalize(self, raw_name: object) -> tuple[str, str | None]:
        resolved = self.resolve(raw_name)
        return resolved.canonical_name, resolved.iso3

    def is_aggregate(self, raw_name: object) -> bool:
        return self.resolve(raw_name).is_aggregate


def _register_alias(
    alias_map: dict[str, CountryResolution],
    raw_name: str,
    resolution: CountryResolution,
    priority: int,
) -> None:
    key = _norm_key(raw_name)
    if not key:
        return
    marker_key = f"__priority__::{key}"
    existing_priority = alias_map.get(marker_key)  # type: ignore[assignment]
    current_priority = getattr(existing_priority, "aggregate_kind", None)
    current_priority_value = int(current_priority) if current_priority is not None else -10**9
    if priority >= current_priority_value:
        alias_map[key] = resolution
        alias_map[marker_key] = CountryResolution(
            canonical_name="",
            iso3=None,
            aggregate_kind=str(priority),
            source="internal",
        )


def _norm_key(value: object) -> str:
    text = normalize_text(value).strip().lower()
    return " ".join(text.split())


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def _clean_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    return text or None


def _to_bool(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "si", "sí"}


def _to_int(value: Any, default: int) -> int:
    if value is None or pd.isna(value):
        return default
    try:
        return int(value)
    except Exception:
        return default


def _pycountry_candidates(text: str) -> list[str]:
    candidates = [text]
    try:
        match = pycountry.countries.lookup(text)
    except LookupError:
        return candidates

    for attr in ["name", "official_name", "common_name", "alpha_2", "alpha_3"]:
        value = getattr(match, attr, None)
        if value:
            candidates.append(str(value))
    if getattr(match, "alpha_3", None) == "GBR":
        candidates.extend(["UK", "U.K.", "Reino Unido"])
    if getattr(match, "alpha_3", None) == "USA":
        candidates.extend(["USA", "U.S.A.", "EUA", "EE. UU."])
    return candidates