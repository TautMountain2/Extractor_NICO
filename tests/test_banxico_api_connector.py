import json
from pathlib import Path

from nico_trade_hub.catalogs import CountryCatalog
from nico_trade_hub.connectors.api_banxico import BanxicoMatrixApiConnector
from nico_trade_hub.connectors.browser_banxico import BanxicoJob
from nico_trade_hub.connectors.banxico_static_templates import get_measure_caption, get_static_template_config
from nico_trade_hub.parsers.banxico_cube import BanxicoCubeExportParser


class _DummySettings:
    def __init__(self, tmp_path: Path):
        self.project_root = tmp_path
        self.data_dir = tmp_path
        self.database_path = tmp_path / "test_nico.duckdb"
        self.raw = {
            "sources": {
                "banxico": {
                    "timeout_ms": 90000,
                    "api_http_pool_maxsize": 4,
                    "api_parallelism": 4,
                    "api_http_connect_timeout_seconds": 15,
                    "api_topology_cache_enabled": False,
                    "fallback_browser": False,
                    "value_matrix_url": "https://example.test/value",
                    "volume_matrix_url": "https://example.test/volume",
                }
            }
        }

def _build_catalog(tmp_path: Path) -> CountryCatalog:
    country_csv = tmp_path / "countries.csv"
    country_csv.write_text(
        "raw_name,canonical_name,iso3\n"
        "Estados Unidos,United States,USA\n",
        encoding="utf-8",
    )
    return CountryCatalog.from_csv(country_csv)


def test_api_connector_rebuilds_excel_compatible_with_parser(tmp_path: Path):
    settings = _DummySettings(tmp_path)
    connector = BanxicoMatrixApiConnector(settings)
    job = BanxicoJob(year=2022, month=1, flow_code="EXPORT", metric="value")

    serialized = "☻".join(
        [
            "163U␞◙-␞◙0␞◙Valor en dólares␞◙␞◙␞◙␞◙␞◙[Measures].[Valor en dólares]",
            "2␞◙-␞◙0␞◙Todas las regiones␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[Todas las regiones]",
            "1b␞◙-␞◙0␞◙Todos los productos␞◙␞◙␞◙␞◙␞◙[Productos].[TIGIE].[Todos los productos]",
            "1Z␞◙2␞◙5␞◙0101210000 Caballos reproductores de raza pura␞◙␞◙␞◙␞◙␞◙[Productos].[TIGIE].[0101210000 Caballos reproductores de raza pura]",
            "2␞◙1␞◙1␞◙América del Norte␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[América del Norte]",
            "0␞◙4␞◙2␞◙Estados Unidos␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[Estados Unidos]",
        ]
    )
    response_obj = {
        "data": {
            "serializedMemberMap": {"memberMapSerialized": serialized},
            "rawResults": [[5], [3], [123.45]],
            "columnMap": [
                {"caption": "Regiones"},
                {"caption": "TIGIE"},
                {"caption": "Valor en dólares"},
            ],
            "measuresMemberMap": {"2": 0},
        }
    }

    path = tmp_path / "banxico_value_export_2022_01.xlsx"
    connector._response_to_excel(response_obj, job, path)

    parser = BanxicoCubeExportParser()
    catalog = _build_catalog(tmp_path)
    observations = parser.parse(path, catalog, source_code="BANXICO_BROWSER")
    assert len(observations) == 1
    assert observations[0].country_name == "United States"
    assert observations[0].nico10 == "0101210000"
    assert observations[0].value_usd == 123.45


def test_decode_member_map_uses_record_position_as_identifier(tmp_path: Path):
    settings = _DummySettings(tmp_path)
    connector = BanxicoMatrixApiConnector(settings)
    members = connector._decode_member_map(
        "☻".join(
            [
                "163U␞◙-␞◙0␞◙Valor en dólares␞◙␞◙␞◙␞◙␞◙[Measures].[Valor en dólares]",
                "2␞◙-␞◙0␞◙Todas las regiones␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[Todas las regiones]",
                "0␞◙1␞◙1␞◙África y Oceanía␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[África y Oceanía]",
            ]
        )
    )
    assert members[0].caption == "Valor en dólares"
    assert members[1].caption == "Todas las regiones"
    assert members[2].parent_index == 1
    assert members[2].level == 1


def test_api_connector_rebuilds_excel_volume_compatible_with_parser(tmp_path: Path):
    settings = _DummySettings(tmp_path)
    connector = BanxicoMatrixApiConnector(settings)
    job = BanxicoJob(year=2022, month=1, flow_code="EXPORT", metric="volume")

    serialized = "☻".join(
        [
            "163U␞◙-␞◙0␞◙Valor volumen␞◙␞◙␞◙␞◙␞◙[Measures].[Valor volumen]",
            "2␞◙-␞◙0␞◙Todas las regiones␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[Todas las regiones]",
            "1b␞◙-␞◙0␞◙Todos los productos␞◙␞◙␞◙␞◙␞◙[Productos].[TIGIE].[Todos los productos]",
            "1Z␞◙2␞◙5␞◙0101210000 Caballos reproductores de raza pura␞◙␞◙␞◙␞◙␞◙[Productos].[TIGIE].[0101210000 Caballos reproductores de raza pura]",
            "2␞◙1␞◙1␞◙América del Norte␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[América del Norte]",
            "0␞◙4␞◙2␞◙Estados Unidos␞◙␞◙␞◙␞◙␞◙[Localización].[Regiones].[Estados Unidos]",
        ]
    )
    response_obj = {
        "data": {
            "serializedMemberMap": {"memberMapSerialized": serialized},
            "rawResults": [[5], [3], [987.65]],
            "columnMap": [
                {"caption": "Regiones"},
                {"caption": "TIGIE"},
                {"caption": "Valor volumen"},
            ],
            "measuresMemberMap": {"2": 0},
        }
    }

    path = tmp_path / "banxico_volume_export_2022_01.xlsx"
    connector._response_to_excel(response_obj, job, path)

    parser = BanxicoCubeExportParser()
    catalog = _build_catalog(tmp_path)
    observations = parser.parse(path, catalog, source_code="BANXICO_BROWSER")
    assert len(observations) == 1
    assert observations[0].country_name == "United States"
    assert observations[0].nico10 == "0101210000"
    assert observations[0].quantity == 987.65
    assert observations[0].value_usd is None


def test_static_template_registry_includes_volume_metric():
    config = get_static_template_config("volume")
    assert config is not None
    assert config.measure_member == "[Measures].[Valor volumen]"
    assert get_measure_caption("volume") == "Valor volumen"
    assert len(config.seed_payloads_b64) >= 1
    value_config = get_static_template_config("value")
    assert value_config is not None
    assert len(config.chapter_seed_payloads_b64) == len(value_config.chapter_seed_payloads_b64)
