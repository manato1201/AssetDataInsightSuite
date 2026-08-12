"""Unity-specific adapter.

Parses `.meta` sidecars (YAML) for `TextureImporter` settings and scans
`.prefab` / `.unity` YAML documents for `LODGroup` components. Only the
subset of fields the Phase 2 rules actually consume is extracted — this is
not a general-purpose Unity YAML parser.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from core.schema import AssetRecord, CheckResult
from ingest.adapters.registry import register

_TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".psd", ".tif", ".tiff"}
_MODEL_EXTS = {".fbx", ".obj", ".blend", ".gltf", ".glb"}


def _classify(extension: str) -> str:
    ext = extension.lower()
    if ext in _TEXTURE_EXTS:
        return "texture"
    if ext in _MODEL_EXTS:
        return "model"
    return "unknown"


def _load_unity_yaml_documents(path: Path) -> list[dict]:
    """Unity YAML uses `%TAG` directives and `!u!<classID> &<fileID>` markers
    that PyYAML can't resolve; split on the `--- !u!` document separator and
    drop the classID/fileID header line before parsing each document body."""
    docs: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return docs
    for raw_doc in text.split("--- !u!")[1:]:
        _header, _, body = raw_doc.partition("\n")
        try:
            loaded = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(loaded, dict):
            docs.append(loaded)
    return docs


def _parse_texture_meta(meta: dict) -> dict[str, CheckResult]:
    checks: dict[str, CheckResult] = {}
    importer = meta.get("TextureImporter")
    if not isinstance(importer, dict):
        return checks

    max_size = importer.get("maxTextureSize")
    if max_size is not None:
        checks["resolution_px"] = CheckResult(status="info", value=max_size)

    mipmaps = importer.get("mipmaps", {})
    enable_mip = (
        mipmaps.get("enableMipMap")
        if isinstance(mipmaps, dict)
        else importer.get("enableMipMap")
    )
    if enable_mip is not None:
        checks["mipmaps_enabled"] = CheckResult(
            status="pass" if enable_mip else "warn", value=bool(enable_mip)
        )

    return checks


def _asset_has_lod_group(docs: list[dict]) -> bool:
    return any("LODGroup" in doc for doc in docs)


@register
class UnityAssetAdapter:
    producer_id = "unity_asset"

    def scan(self, target_path: str, since: str | None = None) -> list[AssetRecord]:
        since_ts = None
        if since:
            since_ts = datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()

        collected_at = datetime.now(timezone.utc).isoformat()
        root = Path(target_path)
        results: list[AssetRecord] = []

        for meta_path in sorted(root.rglob("*.meta")):
            asset_path = meta_path.with_suffix("")
            if not asset_path.exists():
                continue

            stat = asset_path.stat()
            if since_ts is not None and stat.st_mtime <= since_ts:
                continue

            try:
                meta = (
                    yaml.safe_load(
                        meta_path.read_text(encoding="utf-8", errors="ignore")
                    )
                    or {}
                )
            except yaml.YAMLError:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}

            rel_path = asset_path.relative_to(root).as_posix()
            extension = asset_path.suffix.lower()
            asset_type = _classify(extension)
            checks: dict[str, CheckResult] = {}

            if asset_type == "texture":
                checks.update(_parse_texture_meta(meta))
            elif (
                asset_type == "model"
                and extension in {".fbx"}
                and asset_path.with_suffix(".prefab").exists()
            ):
                docs = _load_unity_yaml_documents(asset_path.with_suffix(".prefab"))
                has_lod = _asset_has_lod_group(docs)
                checks["lod_group_configured"] = CheckResult(
                    status="pass" if has_lod else "fail", value=has_lod
                )

            last_modified = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
            results.append(
                AssetRecord(
                    asset_id=rel_path,
                    asset_type=asset_type,
                    source_producer="unity_asset",
                    collected_at=collected_at,
                    size_bytes=stat.st_size,
                    extension=extension,
                    last_modified=last_modified,
                    checks=checks,
                )
            )
        return results
