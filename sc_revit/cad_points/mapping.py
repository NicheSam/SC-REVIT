import json
from pathlib import Path
from typing import Any

from sc_revit.core.batch import APP_DATA_DIR


MAPPING_VERSION = 1
MAPPING_DIR = APP_DATA_DIR / "cad2bim_mappings"


def default_mapping_dir() -> Path:
    MAPPING_DIR.mkdir(parents=True, exist_ok=True)
    return MAPPING_DIR


def safe_mapping_file_name(source_name: str) -> str:
    cleaned = "".join(
        "_" if char in '\\/:*?"<>|' or ord(char) < 32 else char
        for char in str(source_name or "").strip()
    )
    cleaned = cleaned.strip(" ._") or "cad2bim_mapping"
    if not cleaned.lower().endswith(".json"):
        cleaned += ".json"
    return cleaned


def build_mapping_document(
    *,
    source_path: str = "",
    source_name: str = "",
    mappings: dict[str, dict[str, Any]] | None = None,
    block_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    mappings = mappings or {}
    block_counts = block_counts or {}
    return {
        "version": MAPPING_VERSION,
        "source_path": str(source_path or ""),
        "source_name": str(source_name or ""),
        "mappings": {
            str(block_name): normalize_mapping(block_name, mapping, block_counts.get(str(block_name)))
            for block_name, mapping in sorted(mappings.items())
        },
    }


def normalize_mapping(block_name: str, mapping: dict[str, Any], count: int | None = None) -> dict[str, Any]:
    return {
        "block_name": str(mapping.get("block_name") or block_name or ""),
        "count": int(count or mapping.get("count") or 0),
        "category": str(mapping.get("category") or ""),
        "family_name": str(mapping.get("family_name") or ""),
        "type_name": str(mapping.get("type_name") or ""),
        "symbol_id": str(mapping.get("symbol_id") or ""),
        "level_name": str(mapping.get("level_name") or ""),
        "level_id": str(mapping.get("level_id") or ""),
        "offset_mm": float(mapping.get("offset_mm") or 0),
    }


def save_mapping_file(
    path: str | Path,
    *,
    source_path: str = "",
    source_name: str = "",
    mappings: dict[str, dict[str, Any]] | None = None,
    block_counts: dict[str, int] | None = None,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = build_mapping_document(
        source_path=source_path,
        source_name=source_name,
        mappings=mappings,
        block_counts=block_counts,
    )
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def load_mapping_file(path: str | Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_mappings = document.get("mappings") or {}
    mappings = {
        str(block_name): normalize_mapping(str(block_name), mapping)
        for block_name, mapping in raw_mappings.items()
        if isinstance(mapping, dict)
    }
    return {
        "version": int(document.get("version") or 0),
        "source_path": str(document.get("source_path") or ""),
        "source_name": str(document.get("source_name") or ""),
        "mappings": mappings,
    }


def filter_mappings_for_blocks(
    mappings: dict[str, dict[str, Any]],
    block_counts: dict[str, int],
) -> dict[str, dict[str, Any]]:
    return {
        block_name: normalize_mapping(block_name, mappings[block_name], block_counts.get(block_name))
        for block_name in sorted(block_counts)
        if block_name in mappings
    }
