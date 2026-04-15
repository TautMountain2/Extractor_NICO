"""Parser genérico para exportaciones Excel del cubo de Banxico."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..catalogs import CountryCatalog
from ..models import TradeObservation
from ..utils import month_start, normalize_key, normalize_text, parse_number, parse_tariff_label


AGGREGATE_REGION_KEYS = {
    "todaslasregiones",
    "africayoceania",
    "africayoceania",
    "americadelnorte",
    "asia",
    "europa",
    "latinoamericayantillas",
    "otros",
}


class BanxicoCubeExportParser:
    name = "banxico_cube_export"

    def detect(self, path: Path) -> bool:
        if path.suffix.lower() not in {".xlsx", ".xls"}:
            return False
        try:
            sheets = pd.read_excel(path, sheet_name=None, header=None)
        except Exception:
            return False
        blob = " ".join(
            normalize_text(v)
            for df in sheets.values()
            for v in df.head(20).fillna("").to_numpy().ravel().tolist()
        )
        blob = blob.lower()
        return "comercio exterior" in blob or "banxico" in blob or "exportacion" in blob or "importacion" in blob

    def resolve_source_code(self, path: Path, source_code: str) -> str:
        metric = self._infer_metric(None, path.name, source_code)
        return "BANXICO_VALUE_USD" if metric == "value" else "BANXICO_VOLUME"

    def parse(
        self,
        path: Path,
        catalog: CountryCatalog,
        source_code: str,
        source_revision: str | None = None,
        load_run_id: int | None = None,
    ) -> list[TradeObservation]:
        book = pd.read_excel(path, sheet_name=None, header=None)
        observations: list[TradeObservation] = []
        effective_source = self.resolve_source_code(path, source_code)
        for sheet_name, raw in book.items():
            observations.extend(
                self._parse_sheet(raw, path=path, sheet_name=sheet_name, catalog=catalog, source_code=effective_source, source_revision=source_revision, load_run_id=load_run_id)
            )
        if not observations:
            raise ValueError(f"No se pudieron obtener observaciones Banxico desde {path.name}")
        return observations

    def _parse_sheet(self, raw: pd.DataFrame, *, path: Path, sheet_name: str, catalog: CountryCatalog, source_code: str, source_revision: str | None, load_run_id: int | None) -> list[TradeObservation]:
        year, month = self._infer_period(raw, path.name)
        flow_code = self._infer_flow(raw, path.name)
        metric = self._infer_metric(raw, path.name, source_code)

        header_row, data_rows = self._find_table_bounds(raw)
        if header_row is None or data_rows is None:
            return []

        table = raw.iloc[header_row : data_rows + 1].copy().reset_index(drop=True)
        header = [normalize_text(v) for v in table.iloc[0].tolist()]
        header = self._make_unique_header(header)
        table = table.iloc[1:].copy()
        table.columns = header
        table = table.dropna(how="all")
        if table.empty:
            return []

        numeric_like_cols = [col for col in table.columns if self._column_is_numeric(table[col])]
        numeric_cols = [col for col in numeric_like_cols if self._is_detail_country_column(col)]
        if not numeric_cols:
            return []
        dim_cols = [col for col in table.columns if col not in numeric_like_cols]
        if not dim_cols:
            return []

        # algunos reportes tienen jerarquía distribuida en varias columnas; se usa la etiqueta más profunda no vacía.
        table[dim_cols] = table[dim_cols].ffill()

        rows: list[TradeObservation] = []
        for _, row in table.iterrows():
            tariff_label = self._deepest_dimension_value(row, dim_cols)
            if not tariff_label:
                continue
            try:
                tariff_info = parse_tariff_label(tariff_label)
            except Exception:
                continue
            for country_col in numeric_cols:
                value = parse_number(row[country_col])
                if value is None:
                    continue
                country_name, country_iso3 = catalog.normalize(country_col)
                kwargs = dict(
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
                    quantity=value if metric == "volume" else None,
                    value_usd=value if metric == "value" else None,
                    source_code=source_code,
                    source_file=f"{path}::{sheet_name}",
                    source_revision=source_revision,
                    load_run_id=load_run_id,
                )
                rows.append(TradeObservation(**kwargs))
        return rows

    def _make_unique_header(self, header: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        result: list[str] = []
        for idx, value in enumerate(header):
            base = value or f"col_{idx}"
            count = seen.get(base, 0)
            seen[base] = count + 1
            result.append(base if count == 0 else f"{base}_{count}")
        return result

    def _find_table_bounds(self, raw: pd.DataFrame) -> tuple[int | None, int | None]:
        candidates: list[tuple[int, int]] = []
        scan_limit = min(len(raw) - 1, 30)
        for idx in range(scan_limit):
            row_values = [normalize_text(v) for v in raw.iloc[idx].tolist()]
            next_values = raw.iloc[idx + 1].tolist() if idx + 1 < len(raw) else []
            non_empty = [v for v in row_values if v]
            if len(non_empty) < 2:
                continue
            score = len(non_empty)
            text_count = sum(1 for v in non_empty if parse_number(v) is None)
            score += text_count * 2
            if text_count >= 3:
                score += 20
            blob = " ".join(v.lower() for v in non_empty)
            if any(token in blob for token in ["producto", "pais", "país", "region", "región", "tigie"]):
                score += 10
            if "tigie" in blob:
                score += 50
            if "todas las regiones" in blob:
                score += 20
            numeric_next = sum(parse_number(v) is not None for v in next_values)
            if numeric_next >= 1:
                score += 5
            if numeric_next >= 3:
                score += 5
            candidates.append((score, idx))

        if not candidates:
            return None, None

        _, best_header = max(candidates)
        last = best_header
        for idx in range(best_header + 1, len(raw)):
            if raw.iloc[idx].notna().sum() == 0:
                break
            last = idx
        return best_header, last

    def _column_is_numeric(self, series: pd.Series) -> bool:
        numeric = 0
        meaningful = 0
        for raw in series.tolist():
            text = normalize_text(raw).lower()
            if text in {"", "na", "nan", "none"}:
                continue
            meaningful += 1
            if parse_number(raw) is not None:
                numeric += 1
        return meaningful > 0 and numeric == meaningful

    def _is_detail_country_column(self, column_name: str) -> bool:
        key = normalize_key(column_name)
        if not key:
            return False
        if key in AGGREGATE_REGION_KEYS:
            return False
        return True

    def _deepest_dimension_value(self, row: pd.Series, dim_cols: list[str]) -> str | None:
        values: list[str] = []
        for col in dim_cols:
            value = normalize_text(row[col])
            if value.lower() in {"", "na", "nan", "none"}:
                continue
            values.append(value)
        if not values:
            return None
        return values[-1]

    def _infer_flow(self, raw: pd.DataFrame, filename: str) -> str:
        blob = " ".join(normalize_text(v).lower() for v in raw.head(15).fillna("").to_numpy().ravel().tolist())
        filename_norm = normalize_text(filename).lower()
        if "importacion" in blob or "import" in filename_norm:
            return "IMPORT"
        return "EXPORT"

    def _infer_metric(self, raw: pd.DataFrame | None, filename: str, source_code: str) -> str:
        source_norm = normalize_text(source_code).lower()
        file_norm = normalize_text(filename).lower()
        if "value" in source_norm or "usd" in source_norm or "valor" in source_norm:
            return "value"
        if "volume" in source_norm or "volumen" in source_norm:
            return "volume"
        if "_value_" in file_norm or "valor" in file_norm:
            return "value"
        if "_volume_" in file_norm or "volumen" in file_norm:
            return "volume"
        if raw is not None:
            blob = " ".join(normalize_text(v).lower() for v in raw.head(10).fillna("").to_numpy().ravel().tolist())
            if "valor en dolares" in blob or "valor en dólares" in blob:
                return "value"
            if "volumen" in blob:
                return "volume"
        return "value"

    def _infer_period(self, raw: pd.DataFrame, filename: str) -> tuple[int, int]:
        match = re.search(r"(20\d{2})[_-](\d{2})", filename)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            if 1 <= month <= 12:
                return year, month
        blob = " ".join(normalize_text(v).lower() for v in raw.head(10).fillna("").to_numpy().ravel().tolist())
        months = {
            "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
            "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        }
        year = None
        month = None
        for token, value in months.items():
            if token in blob:
                month = value
                break
        match = re.search(r"(20\d{2})", blob)
        if match:
            year = int(match.group(1))
        if year is None or month is None:
            raise ValueError("No se pudo inferir el periodo del archivo Banxico")
        return year, month
