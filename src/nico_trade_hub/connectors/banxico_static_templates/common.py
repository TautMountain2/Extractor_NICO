"""Contratos y utilidades para plantillas estáticas de Banxico."""

from __future__ import annotations

import base64
import gzip
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BanxicoStaticTemplateConfig:
    metric: str
    default_template_b64: str
    seed_payloads_b64: tuple[str, ...]
    chapter_seed_payloads_b64: dict[str, tuple[str, ...]]
    chapter_response_seeds_b64: dict[str, tuple[str, ...]]
    measure_member: str
    excel_caption: str
    default_month_label: str = "Enero 2022"
    default_flow_label: str = "Exportación"


def decode_embedded_json(encoded: str) -> dict[str, Any]:
    return json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8"))


def encode_embedded_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii")


def transform_embedded_json(
    encoded: str,
    transform: callable,
) -> str:
    payload = decode_embedded_json(encoded)
    transformed = transform(payload)
    return encode_embedded_json(transformed)


def get_measure_caption_from_config(config: BanxicoStaticTemplateConfig | None, metric: str) -> str:
    if config is not None:
        return config.excel_caption
    return "Valor en dólares" if metric.lower() == "value" else metric
