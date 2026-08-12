"""Naive filesystem scan adapter.

The universal fallback producer: extension / size / mtime only, no
per-format metadata. Used for any asset type that doesn't have a dedicated
producer yet.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from core.schema import AssetRecord
from ingest.adapters.registry import register

_TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".psd", ".tif", ".tiff"}
_MODEL_EXTS = {".fbx", ".obj", ".blend", ".gltf", ".glb"}
_MATERIAL_EXTS = {".mat"}
_AUDIO_EXTS = {".wav", ".ogg", ".bank", ".mp3"}

_SKIP_SUFFIXES = {".meta", ".lqa.json"}


def _classify(extension: str) -> str:
    ext = extension.lower()
    if ext in _TEXTURE_EXTS:
        return "texture"
    if ext in _MODEL_EXTS:
        return "model"
    if ext in _MATERIAL_EXTS:
        return "material"
    if ext in _AUDIO_EXTS:
        return "audio_bank"
    return "unknown"


@register
class FsScanAdapter:
    producer_id = "fs_scan"

    def scan(self, target_path: str, since: str | None = None) -> list[AssetRecord]:
        since_ts = None
        if since:
            since_ts = datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()

        collected_at = datetime.now(timezone.utc).isoformat()
        root = Path(target_path)
        results: list[AssetRecord] = []

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.endswith(tuple(_SKIP_SUFFIXES)):
                continue

            stat = path.stat()
            if since_ts is not None and stat.st_mtime <= since_ts:
                continue

            rel_path = path.relative_to(root).as_posix()
            last_modified = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()

            results.append(
                AssetRecord(
                    asset_id=rel_path,
                    asset_type=_classify(path.suffix),
                    source_producer="fs_scan",
                    collected_at=collected_at,
                    size_bytes=stat.st_size,
                    extension=path.suffix.lower(),
                    last_modified=last_modified,
                    checks={},
                )
            )
        return results
