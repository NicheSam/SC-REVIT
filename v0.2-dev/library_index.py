import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from naming_rules import SYSTEM_DISPLAY_NAMES


UPLOAD_RECORDS_RELATIVE_DIR = Path("03 管理區") / "04 上傳紀錄"
DB_NAME = "library_index.db"


def get_records_dir(library_root: str) -> Path:
    return Path(library_root) / UPLOAD_RECORDS_RELATIVE_DIR


def get_db_path(library_root: str) -> Path:
    return get_records_dir(library_root) / DB_NAME


def ensure_schema(library_root: str) -> Path:
    records_dir = get_records_dir(library_root)
    records_dir.mkdir(parents=True, exist_ok=True)
    db_path = get_db_path(library_root)
    with closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.execute(
            """
            CREATE TABLE IF NOT EXISTS families (
                id TEXT PRIMARY KEY,
                ingested_at TEXT NOT NULL,
                source_file_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                final_file_name TEXT NOT NULL,
                final_relative_path TEXT NOT NULL,
                system_code TEXT,
                system_name TEXT,
                revit_category TEXT,
                family_name TEXT,
                base_name TEXT,
                selected_suffixes_json TEXT NOT NULL,
                classification_path TEXT,
                classification_score INTEGER,
                classification_status TEXT,
                folder_overridden INTEGER NOT NULL,
                name_overridden INTEGER NOT NULL,
                duplicate_original_name INTEGER NOT NULL,
                duplicate_planned_name INTEGER NOT NULL
            )
            """
        )
        cursor.close()
        conn.commit()
    return db_path


def record_ingest(
    *,
    library_root: str,
    source_path: str,
    final_path: str,
    result: dict[str, Any],
    base_name: str | None,
    suffix_options: list[dict[str, object]],
    approved_path: str | None,
    planned_name_manual: bool,
    duplicate_result: dict[str, Any] | None,
) -> str:
    db_path = ensure_schema(library_root)
    source = Path(source_path)
    final = Path(final_path)
    source_metadata = result.get("source_metadata", {})
    system_code = result.get("system")
    system_name = SYSTEM_DISPLAY_NAMES.get(system_code, system_code)
    selected_suffixes = [
        {"category": item["category"], "value": item["value"]}
        for item in suffix_options
        if item.get("selected")
    ]
    record_id = str(uuid.uuid4())
    with closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO families (
                id, ingested_at, source_file_name, source_path, final_file_name,
                final_relative_path, system_code, system_name, revit_category,
                family_name, base_name, selected_suffixes_json, classification_path,
                classification_score, classification_status, folder_overridden,
                name_overridden, duplicate_original_name, duplicate_planned_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                datetime.now().astimezone().isoformat(timespec="seconds"),
                source.name,
                str(source),
                final.name,
                str(final.relative_to(Path(library_root))).replace("/", "\\"),
                system_code,
                system_name,
                source_metadata.get("revit_category"),
                source_metadata.get("family_name"),
                base_name,
                json.dumps(selected_suffixes, ensure_ascii=False),
                approved_path or result.get("path"),
                result.get("score"),
                result.get("status"),
                int(bool(approved_path)),
                int(bool(planned_name_manual)),
                int(bool((duplicate_result or {}).get("original_name_exists"))),
                int(bool((duplicate_result or {}).get("planned_name_exists"))),
            ),
        )
        cursor.close()
        conn.commit()
    return record_id


def fetch_recent_records(library_root: str, limit: int = 10) -> list[dict[str, Any]]:
    db_path = ensure_schema(library_root)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM families ORDER BY ingested_at DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        records = [dict(row) for row in rows]
        cursor.close()
    return records
