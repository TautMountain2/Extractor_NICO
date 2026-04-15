"""! Parser de archivos exportados desde el cubo interactivo de INEGI/BCMM."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from ..catalogs import CountryCatalog
from ..models import TradeObservation
from ..utils import normalize_key, parse_month, parse_number, parse_tariff_label, month_start


REQUIRED_KEYS = {
    "anio": "year",
    "mes": "month",
    "pais": "country",
    "tarifa": "tariff",
}
OPTIONAL_KEYS = {
    "tipodeoperacion": "flow",
    "valortotalendolares": "value_usd",
    "valorusd": "value_usd",
    "cantidadtotal": "quantity",
    "cantidad": "quantity",
}


class InegiCubeExportParser:
    """! Convierte exportaciones del cubo a observaciones canónicas."""

    name = "inegi_cube_export"

    def detect(self, path: Path) -> bool:
        preview = self._read_raw(path, nrows=15)
        flattened = [normalize_key(value) for value in preview.fillna("").astype(str).to_numpy().ravel()]
        return "tarifa" in flattened and "pais" in flattened and ("anio" in flattened or "ano" in flattened)

    def parse(self, path: Path, catalog: CountryCatalog, source_code: str, source_revision: str | None = None, load_run_id: int | None = None) -> list[TradeObservation]:
        raw = self._read_raw(path)
        header_row = self._find_header_row(raw)
        header = [normalize_key(v) for v in raw.iloc[header_row].tolist()]
        body = raw.iloc[header_row + 1 :].copy()
        body.columns = header
        body = body.dropna(how="all")

        column_map: dict[str, str] = {}
        for raw_key in body.columns:
            if raw_key in REQUIRED_KEYS:
                column_map[REQUIRED_KEYS[raw_key]] = raw_key
            if raw_key in OPTIONAL_KEYS:
                column_map[OPTIONAL_KEYS[raw_key]] = raw_key
            if raw_key == "ano":
                column_map["year"] = raw_key

        missing = {v for v in REQUIRED_KEYS.values()} - set(column_map)
        if missing:
            raise ValueError(f"Columnas requeridas ausentes en {path.name}: {sorted(missing)}")

        observations: list[TradeObservation] = []
        for row in body.to_dict(orient="records"):
            year = int(parse_number(row[column_map["year"]]) or 0)
            month = parse_month(row[column_map["month"]])
            flow_raw = row.get(column_map.get("flow"), "")
            flow_norm = normalize_key(flow_raw)
            if flow_norm.startswith("import"):
                flow_code = "IMPORT"
            elif flow_norm.startswith("export"):
                flow_code = "EXPORT"
            else:
                flow_code = "UNKNOWN"

            country_name, country_iso3 = catalog.normalize(row[column_map["country"]])
            tariff_info = parse_tariff_label(row[column_map["tariff"]])
            quantity = parse_number(row.get(column_map.get("quantity")))
            value_usd = parse_number(row.get(column_map.get("value_usd")))

            observations.append(
                TradeObservation(
                    date_month=month_start(year, month),
                    year=year,
                    month=month,
                    flow_code=flow_code,
                    country_name=country_name,
                    country_iso3=country_iso3,
                    tariff_code=str(tariff_info["tariff_code"]),
                    tariff_level=int(tariff_info["tariff_level"]),
                    hs2=tariff_info["hs2"],
                    hs4=tariff_info["hs4"],
                    hs6=tariff_info["hs6"],
                    fraccion8=tariff_info["fraccion8"],
                    nico10=tariff_info["nico10"],
                    tariff_description=tariff_info["tariff_description"],
                    unit_name=tariff_info["unit_name"],
                    quantity=quantity,
                    value_usd=value_usd,
                    source_code=source_code,
                    source_file=str(path),
                    source_revision=source_revision,
                    load_run_id=load_run_id,
                )
            )
        return observations

    def _read_raw(self, path: Path, nrows: int | None = None) -> pd.DataFrame:
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, header=None, nrows=nrows)
        return pd.read_csv(path, header=None, nrows=nrows)

    def _find_header_row(self, raw: pd.DataFrame) -> int:
        for idx in range(min(len(raw), 25)):
            keys = {normalize_key(value) for value in raw.iloc[idx].tolist()}
            if ({"tarifa", "pais"} <= keys) and ({"anio"} <= keys or {"ano"} <= keys) and {"mes"} <= keys:
                return idx
        raise ValueError("No se pudo localizar la fila de encabezados del archivo exportado")
