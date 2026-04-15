from pathlib import Path

import pandas as pd

from nico_trade_hub.nico_catalog import NicoCatalogLoader


def test_nico_catalog_loader(tmp_path: Path):
    path = tmp_path / "nico.xlsx"
    df = pd.DataFrame(
        [
            [None, "FRACCIÓN ARANCELARIA", "NICO", "DESCRIPCIÓN"],
            [None, "0101.21.01", "00", "Reproductores de raza pura."],
            [None, "0101.29.99", "01", "Para saltos o carreras."],
        ]
    )
    df.to_excel(path, index=False, header=False)
    loader = NicoCatalogLoader()
    rows = loader.load(path)
    assert len(rows) == 2
    assert rows[0].nico10 == "0101210100"
    assert rows[1].nico10 == "0101299901"
