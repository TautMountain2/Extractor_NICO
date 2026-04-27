"""Builders ligeros de payload para Banxico API privada.

Fase 7A:
- evita deepcopy del payload completo por request;
- clona únicamente las ramas del JSON que realmente se mutan;
- mantiene compatibilidad con la lógica actual del conector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BanxicoPayloadTemplate:
    """Plantilla preparada para mutaciones baratas del payload."""

    base_payload: dict[str, Any]
    qsm_product_item_index: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BanxicoPayloadTemplate":
        qsm_product_item_index: int | None = None
        try:
            qsm = payload["query"]["arguments"][0].get("qsm")
            if isinstance(qsm, dict):
                for idx, item in enumerate(qsm.get("dropZoneItems", [])):
                    if isinstance(item, dict) and item.get("hierarchyUniqueName") == "[Productos].[TIGIE]":
                        qsm_product_item_index = idx
                        break
        except Exception:
            qsm_product_item_index = None

        return cls(
            base_payload=payload,
            qsm_product_item_index=qsm_product_item_index,
        )


class BanxicoPayloadBuilder:
    """Construye payloads mutando sólo la rama necesaria."""

    def __init__(self, template: BanxicoPayloadTemplate) -> None:
        self.template = template

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BanxicoPayloadBuilder":
        return cls(BanxicoPayloadTemplate.from_payload(payload))

    def build_product_payload(
        self,
        base_payload: dict[str, Any],
        *,
        explicit_products: list[str],
        descendants_products: list[str],
    ) -> dict[str, Any]:
        payload, product_attr = self._clone_for_product_selection(base_payload)
        selection_list: list[dict[str, Any]] = []

        for unique_name in self._dedupe_preserve(explicit_products):
            selection_list.append(self._make_explicit_selection(unique_name))
        for unique_name in self._dedupe_preserve(descendants_products):
            selection_list.append(self._make_descendants_selection(unique_name))

        product_attr["elementSelectionList"] = selection_list
        self._sync_product_selection_mirrors(payload, selection_list)
        return payload

    def _clone_for_product_selection(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        payload_copy = dict(payload)

        query = dict(payload_copy["query"])
        payload_copy["query"] = query

        arguments = list(query["arguments"])
        query["arguments"] = arguments

        argument0 = dict(arguments[0])
        arguments[0] = argument0

        qom = dict(argument0["qom"])
        argument0["qom"] = qom

        columns = dict(qom["columns"])
        qom["columns"] = columns

        attributes = list(columns["attributes"])
        columns["attributes"] = attributes

        product_attr = dict(attributes[0])
        attributes[0] = product_attr

        qsm = argument0.get("qsm")
        if isinstance(qsm, dict):
            qsm_copy = dict(qsm)
            argument0["qsm"] = qsm_copy
            drop_items = list(qsm.get("dropZoneItems", []))
            qsm_copy["dropZoneItems"] = drop_items

            idx = self.template.qsm_product_item_index
            if idx is not None and 0 <= idx < len(drop_items) and isinstance(drop_items[idx], dict):
                item_copy = dict(drop_items[idx])
                drop_items[idx] = item_copy
                qom_selection = item_copy.get("qomSelection")
                if isinstance(qom_selection, dict):
                    item_copy["qomSelection"] = dict(qom_selection)
            else:
                for idx2, item in enumerate(drop_items):
                    if isinstance(item, dict) and item.get("hierarchyUniqueName") == "[Productos].[TIGIE]":
                        item_copy = dict(item)
                        drop_items[idx2] = item_copy
                        qom_selection = item_copy.get("qomSelection")
                        if isinstance(qom_selection, dict):
                            item_copy["qomSelection"] = dict(qom_selection)
                        break

        return payload_copy, product_attr

    def _sync_product_selection_mirrors(
        self,
        payload: dict[str, Any],
        selection_list: list[dict[str, Any]],
    ) -> None:
        query = payload.get("query", {})
        arguments = query.get("arguments", [])
        if not arguments:
            return
        argument0 = arguments[0]
        qsm = argument0.get("qsm")
        if not isinstance(qsm, dict):
            return

        drop_items = qsm.get("dropZoneItems", [])
        idx = self.template.qsm_product_item_index
        if idx is not None and 0 <= idx < len(drop_items):
            item = drop_items[idx]
            if isinstance(item, dict) and item.get("hierarchyUniqueName") == "[Productos].[TIGIE]":
                qom_selection = item.get("qomSelection")
                if isinstance(qom_selection, dict):
                    qom_selection["elementSelectionList"] = [dict(sel) for sel in selection_list]
                return

        for item in drop_items:
            if not isinstance(item, dict):
                continue
            if item.get("hierarchyUniqueName") != "[Productos].[TIGIE]":
                continue
            qom_selection = item.get("qomSelection")
            if not isinstance(qom_selection, dict):
                continue
            qom_selection["elementSelectionList"] = [dict(sel) for sel in selection_list]
            return

    @staticmethod
    def _make_explicit_selection(unique_name: str) -> dict[str, Any]:
        return {
            "elementSelectionType": 0,
            "value": unique_name,
            "elementFunction": None,
            "deselect": False,
        }

    @staticmethod
    def _make_descendants_selection(unique_name: str) -> dict[str, Any]:
        return {
            "elementSelectionType": 1,
            "elementFunction": {
                "elementFunctionType": 8,
                "arguments": [unique_name],
                "caption": None,
                "includeCalculatedMembers": True,
            },
            "value": None,
            "deselect": False,
        }

    @staticmethod
    def _dedupe_preserve(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
