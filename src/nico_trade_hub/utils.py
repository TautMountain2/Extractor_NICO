"""! Utilidades generales."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd


SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def normalize_text(value: object) -> str:
    """! Normaliza texto removiendo acentos y espacios redundantes."""
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_key(value: object) -> str:
    """! Crea una llave robusta para comparación flexible de encabezados."""
    text = normalize_text(value).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def parse_number(value: object) -> float | None:
    """! Convierte valores numéricos con comas, espacios o vacíos."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) else float(value)
    if isinstance(value, int):
        return float(value)
    text = str(value).strip()
    if text == "":
        return None
    text = text.replace(",", "")
    text = text.replace("$", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_month(value: object) -> int:
    """! Interpreta mes numérico o nombre en español."""
    if isinstance(value, int):
        return value
    text = normalize_text(value).lower()
    if text.isdigit():
        return int(text)
    if text in SPANISH_MONTHS:
        return SPANISH_MONTHS[text]
    raise ValueError(f"No se pudo interpretar el mes: {value!r}")


def month_start(year: int, month: int) -> date:
    """! Devuelve el primer día del mes."""
    return date(year, month, 1)


def parse_tariff_label(label: object) -> dict[str, str | int | None]:
    """! Descompone una etiqueta de tarifa exportada por INEGI.

    Soporta variantes como:
    - 73.06.19.99.00 (Kg) Descripción
    - 7306199900 Descripción
    - 73.06.19.99 (Kg) Descripción
    """
    text = normalize_text(label)
    if not text:
        raise ValueError("La etiqueta de tarifa viene vacía")

    unit_name = None
    unit_match = re.search(r"\(([^)]+)\)", text)
    if unit_match:
        unit_name = unit_match.group(1).strip()

    code_match = re.match(r"^([0-9][0-9.]+)", text)
    if not code_match:
        digits = re.sub(r"\D", "", text)
        if not digits:
            raise ValueError(f"No se encontró código arancelario en: {text}")
        code = digits
        description = text
    else:
        code = re.sub(r"\D", "", code_match.group(1))
        description = text[code_match.end():].strip()
        if unit_match:
            description = re.sub(r"^\([^)]*\)\s*", "", description).strip()

    level = len(code)
    hs2 = code[:2] if level >= 2 else None
    hs4 = code[:4] if level >= 4 else None
    hs6 = code[:6] if level >= 6 else None
    fraccion8 = code[:8] if level >= 8 else None
    nico10 = code[:10] if level >= 10 else None

    return {
        "tariff_code": code,
        "tariff_level": level,
        "hs2": hs2,
        "hs4": hs4,
        "hs6": hs6,
        "fraccion8": fraccion8,
        "nico10": nico10,
        "unit_name": unit_name,
        "tariff_description": description or None,
    }


def file_sha256(path: Path) -> str:
    """! Calcula hash SHA-256 de un archivo."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_hash(record: dict[str, object]) -> str:
    """! Genera hash determinístico para un registro canónico."""
    ordered = "|".join(
        "" if record.get(k) is None else str(record.get(k))
        for k in [
            "date_month",
            "flow_code",
            "country_name",
            "tariff_code",
            "quantity",
            "value_usd",
            "source_code",
        ]
    )
    return hashlib.sha256(ordered.encode("utf-8")).hexdigest()


def dataframe_to_bytes_csv(df: pd.DataFrame) -> bytes:
    """! Serializa un DataFrame a bytes CSV UTF-8."""
    return df.to_csv(index=False).encode("utf-8")
