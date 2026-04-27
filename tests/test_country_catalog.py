from pathlib import Path

from nico_trade_hub.catalogs import CountryCatalog


def test_country_catalog_aliases():
    catalog = CountryCatalog.from_csv(Path('config/catalogs/country_aliases.csv'))

    assert catalog.normalize('EE. UU.') == ('Estados Unidos de América', 'USA')
    assert catalog.normalize('U.S.A.') == ('Estados Unidos de América', 'USA')
    assert catalog.normalize('República de Corea') == ('Corea del Sur', 'KOR')
    assert catalog.normalize('Holland') == ('Países Bajos', 'NLD')
    assert catalog.normalize('World Total') == ('Mundo', None)


def test_country_catalog_aggregate_flag():
    catalog = CountryCatalog.from_csv(Path('config/catalogs/country_aliases.csv'))

    assert catalog.is_aggregate('World Total') is True
    assert catalog.is_aggregate('Unión Europea') is True
    assert catalog.is_aggregate('México') is False
