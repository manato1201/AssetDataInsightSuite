"""Plugin registry for source adapters.

Adding a new producer is a single new file under `ingest/adapters/` that
defines a class decorated with `@register` — no changes to existing code are
required.
"""

from __future__ import annotations

from typing import Protocol

from core.schema import AssetRecord


class SourceAdapter(Protocol):
    producer_id: str

    def scan(self, target_path: str, since: str | None = None) -> list[AssetRecord]: ...


ADAPTER_REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter_cls: type[SourceAdapter]) -> type[SourceAdapter]:
    instance = adapter_cls()
    ADAPTER_REGISTRY[instance.producer_id] = instance
    return adapter_cls
