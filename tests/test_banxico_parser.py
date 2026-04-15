from pathlib import Path

import pandas as pd

from nico_trade_hub.catalogs import CountryCatalog
from nico_trade_hub.parsers.banxico_cube import BanxicoCubeExportParser


def _build_catalog(tmp_path: Path) -> CountryCatalog:
    country_csv = tmp_path / "countries.csv"
    country_csv.write_text(
        "raw_name,canonical_name,iso3\n"
        "Estados Unidos,United States,USA\n"
        "Canadá,Canada,CAN\n"
        "Angola,Angola,AGO\n",
        encoding="utf-8",
    )
    return CountryCatalog.from_csv(country_csv)


def test_banxico_parser_reads_simple_matrix(tmp_path: Path):
    path = tmp_path / "banxico_value_export_2022_01.xlsx"
    df = pd.DataFrame(
        [
            ["Cubo de Información de Comercio Exterior - Valor en dólares", None, None],
            ["Exportación", "Enero 2022", None],
            ["Producto", "Estados Unidos", "Canadá"],
            ["08044001 Aguacates", 100.5, 20.0],
            ["08045002 Guayabas", 10.0, None],
        ]
    )
    df.to_excel(path, index=False, header=False)
    catalog = _build_catalog(tmp_path)
    parser = BanxicoCubeExportParser()
    observations = parser.parse(path, catalog, source_code="BANXICO_VALUE_USD")
    assert len(observations) == 3
    assert observations[0].flow_code == "EXPORT"
    assert observations[0].value_usd == 100.5
    assert observations[0].fraccion8 == "08044001"


def test_banxico_parser_ignores_aggregate_region_columns(tmp_path: Path):
    path = tmp_path / "banxico_value_export_2022_01.xlsx"
    df = pd.DataFrame(
        [
            ["Cubo de Información de Comercio Exterior - Valor en dólares", None, None, None],
            ["Exportación", "Enero 2022", None, None],
            ["TIGIE", "Todas las regiones", "África y Oceanía", "Angola"],
            ["0101909900 --- Los demás.", 999.0, 123.0, 5.0],
        ]
    )
    df.to_excel(path, index=False, header=False)
    catalog = _build_catalog(tmp_path)
    parser = BanxicoCubeExportParser()
    observations = parser.parse(path, catalog, source_code="BANXICO_VALUE_USD")
    assert len(observations) == 1
    assert observations[0].country_name == "Angola"
    assert observations[0].nico10 == "0101909900"


def test_banxico_parser_resolves_metric_from_generic_source(tmp_path: Path):
    path = tmp_path / "banxico_value_export_2022_01.xlsx"
    df = pd.DataFrame(
        [
            ["Cubo de Información de Comercio Exterior - Valor en dólares", None],
            ["Exportación", "Enero 2022"],
            ["Producto", "Estados Unidos"],
            ["0101909900 --- Los demás.", 7.0],
        ]
    )
    df.to_excel(path, index=False, header=False)
    catalog = _build_catalog(tmp_path)
    parser = BanxicoCubeExportParser()
    observations = parser.parse(path, catalog, source_code="BANXICO_BROWSER")
    assert observations[0].source_code == "BANXICO_VALUE_USD"
    assert observations[0].value_usd == 7.0
    assert observations[0].quantity is None
