"""Registry de plantillas estáticas por métrica para Banxico."""

from __future__ import annotations

from .common import BanxicoStaticTemplateConfig, decode_embedded_json, encode_embedded_json, transform_embedded_json, get_measure_caption_from_config
from .value import VALUE_STATIC_TEMPLATE_CONFIG
from .volume import VOLUME_STATIC_TEMPLATE_CONFIG

_STATIC_TEMPLATES: dict[str, BanxicoStaticTemplateConfig] = {
    VALUE_STATIC_TEMPLATE_CONFIG.metric: VALUE_STATIC_TEMPLATE_CONFIG,
}
if VOLUME_STATIC_TEMPLATE_CONFIG is not None:
    _STATIC_TEMPLATES[VOLUME_STATIC_TEMPLATE_CONFIG.metric] = VOLUME_STATIC_TEMPLATE_CONFIG


def get_static_template_config(metric: str) -> BanxicoStaticTemplateConfig | None:
    return _STATIC_TEMPLATES.get(metric.lower())


def get_measure_caption(metric: str) -> str:
    config = get_static_template_config(metric)
    return get_measure_caption_from_config(config, metric)


__all__ = [
    "BanxicoStaticTemplateConfig",
    "decode_embedded_json",
    "encode_embedded_json",
    "transform_embedded_json",
    "get_measure_caption",
    "get_static_template_config",
]
