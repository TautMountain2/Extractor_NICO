from nico_trade_hub.utils import parse_month, parse_tariff_label


def test_parse_month():
    assert parse_month("Enero") == 1
    assert parse_month("09") == 9


def test_parse_tariff_label():
    info = parse_tariff_label("73.06.19.99.00 (Kg) Los demás")
    assert info["tariff_code"] == "7306199900"
    assert info["nico10"] == "7306199900"
    assert info["unit_name"] == "Kg"
