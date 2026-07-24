import contextvars
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

APP_DATA_DIR = Path(
    os.environ.get(
        "SC_REVIT_RUNTIME_DIR",
        str(
            Path(os.environ.get("LOCALAPPDATA", str(Path(__file__).resolve().parents[2])))
            / "RevitFamilyClassifier"
            / "runtime"
        ),
    )
)
DB_PATH = APP_DATA_DIR / "sc_revit_workflows.sqlite3"
_active_batch_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sc_revit_active_batch_id",
    default=None,
)


TRACKED_PRODUCT_ACTIONS = {
    "place_cad_block_points",
    "place_dwg_block_points",
    "place_dwg_blocks",
    "place_opening_markers",
    "create_fire_branch_pipes",
    "create_drainage_pipes",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"repr": repr(value)}, ensure_ascii=False)


def _safe_summary(value: Any, max_len: int = 4000) -> str:
    text = _to_json(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


PRODUCT_EXTRA_COLUMNS = (
    "element_unique_id",
    "document_title",
    "document_path",
    "group_id",
    "group_name",
    "group_status",
    "family_name",
    "type_name",
    "level_name",
    "location_x",
    "location_y",
    "location_z",
)


def _as_text(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw)


def _as_element_id(raw: Any) -> str:
    if raw in (None, "", 0, "0"):
        return ""
    text = str(raw)
    if text.isdigit() and len(text) <= 12:
        return text
    return ""


def _location_value(item: dict[str, Any], axis: str) -> str:
    for key in ("location", "point"):
        value = item.get(key)
        if isinstance(value, dict) and axis in value:
            return _as_text(value.get(axis))
    if axis in item:
        return _as_text(item.get(axis))
    return ""


def _collect_created_product_records(value: Any) -> list[dict[str, str]]:
    records: dict[str, dict[str, str]] = {}

    def add(item: dict[str, Any], parent: dict[str, Any]) -> None:
        element_id = _as_element_id(item.get("element_id"))
        if not element_id:
            return
        records[element_id] = {
            "product_ref": element_id,
            "element_unique_id": _as_text(item.get("unique_id") or item.get("element_unique_id")),
            "document_title": _as_text(item.get("document_title") or parent.get("document_title")),
            "document_path": _as_text(item.get("document_path") or parent.get("document_path")),
            "group_id": _as_text(item.get("group_id") or parent.get("group_id")),
            "group_name": _as_text(item.get("group_name") or parent.get("group_name")),
            "group_status": "intact" if item.get("group_id") or parent.get("group_id") else "",
            "family_name": _as_text(item.get("family_name")),
            "type_name": _as_text(item.get("type_name")),
            "level_name": _as_text(item.get("level_name")),
            "location_x": _location_value(item, "x"),
            "location_y": _location_value(item, "y"),
            "location_z": _location_value(item, "z"),
        }

    def visit_created(item: Any, parent: dict[str, Any]) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            add(item, parent)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit_created(child, parent)

    if isinstance(value, dict):
        visit_created(value.get("created"), value)
        visit_created(value.get("created_elements"), value)
    return [records[key] for key in sorted(records, key=lambda x: int(x) if x.isdigit() else x)]


def _collect_created_element_ids(value: Any) -> list[str]:
    ids: set[str] = set()

    def add(raw: Any) -> None:
        text = _as_element_id(raw)
        if text:
            ids.add(text)

    def visit_created(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            if "element_id" in item:
                add(item.get("element_id"))
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit_created(child)

    if isinstance(value, dict):
        visit_created(value.get("created"))
        visit_created(value.get("created_elements"))
    return sorted(ids, key=lambda x: int(x) if x.isdigit() else x)


@dataclass(frozen=True)
class Batch:
    batch_id: str
    feature: str
    action: str
    title: str


class BatchStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    feature TEXT NOT NULL,
                    action TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    input_summary TEXT,
                    result_summary TEXT,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_requests (
                    request_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    request_summary TEXT,
                    response_summary TEXT,
                    error_message TEXT,
                    FOREIGN KEY(batch_id) REFERENCES batches(batch_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    product_ref TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT,
                    FOREIGN KEY(batch_id) REFERENCES batches(batch_id)
                )
                """
            )
            for column_name in ("last_seen_status", "last_checked_at", *PRODUCT_EXTRA_COLUMNS):
                columns = [row[1] for row in conn.execute("PRAGMA table_info(batch_products)").fetchall()]
                if column_name not in columns:
                    conn.execute(f"ALTER TABLE batch_products ADD COLUMN {column_name} TEXT")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES batches(batch_id)
                )
                """
            )

    def start_batch(self, feature: str, action: str, title: str, input_summary: Any = None) -> Batch:
        batch_id = "SCB-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO batches(batch_id, feature, action, title, status, created_at, updated_at, input_summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (batch_id, feature, action, title, "running", now, now, _safe_summary(input_summary) if input_summary is not None else None),
            )
        return Batch(batch_id=batch_id, feature=feature, action=action, title=title)

    def finish_batch(self, batch_id: str, status: str, result_summary: Any = None, error_message: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE batches SET status=?, updated_at=?, result_summary=?, error_message=? WHERE batch_id=?",
                (status, _now(), _safe_summary(result_summary) if result_summary is not None else None, error_message, batch_id),
            )

    def add_event(self, batch_id: str, level: str, message: str, detail: Any = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO batch_events(batch_id, level, message, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (batch_id, level, message, _safe_summary(detail) if detail is not None else None, _now()),
            )

    def record_request(self, batch_id: str, request_id: str, action: str, request_payload: Any) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO batch_requests(request_id, batch_id, action, status, created_at, updated_at, request_summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request_id, batch_id, action, "pending", now, now, _safe_summary(request_payload)),
            )

    def finish_request(self, request_id: str, status: str, response_payload: Any = None, error_message: str | None = None) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT batch_id, action FROM batch_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            conn.execute(
                "UPDATE batch_requests SET status=?, updated_at=?, response_summary=?, error_message=? WHERE request_id=?",
                (status, _now(), _safe_summary(response_payload) if response_payload is not None else None, error_message, request_id),
            )
            if row and response_payload is not None and status == "success" and row["action"] in TRACKED_PRODUCT_ACTIONS:
                for record in _collect_created_product_records(response_payload):
                    conn.execute(
                        """
                        INSERT INTO batch_products(
                            batch_id, product_type, product_ref, label, created_at,
                            last_seen_status, last_checked_at, element_unique_id,
                            document_title, document_path, group_id, group_name, group_status,
                            family_name, type_name, level_name, location_x, location_y, location_z
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["batch_id"],
                            "revit_element",
                            record["product_ref"],
                            record.get("family_name") or record.get("type_name") or "Revit Element",
                            _now(),
                            "exists",
                            _now(),
                            record.get("element_unique_id", ""),
                            record.get("document_title", ""),
                            record.get("document_path", ""),
                            record.get("group_id", ""),
                            record.get("group_name", ""),
                            record.get("group_status", ""),
                            record.get("family_name", ""),
                            record.get("type_name", ""),
                            record.get("level_name", ""),
                            record.get("location_x", ""),
                            record.get("location_y", ""),
                            record.get("location_z", ""),
                        ),
                    )

    def list_batches(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT b.*,
                       (SELECT COUNT(*) FROM batch_requests r WHERE r.batch_id=b.batch_id) AS request_count,
                       (SELECT COUNT(*) FROM batch_products p WHERE p.batch_id=b.batch_id) AS tracked_count,
                       (SELECT COUNT(*) FROM batch_products p WHERE p.batch_id=b.batch_id AND p.deleted_at IS NULL AND COALESCE(p.last_seen_status, 'exists')='exists') AS existing_count,
                       (SELECT COUNT(*) FROM batch_products p WHERE p.batch_id=b.batch_id AND (p.deleted_at IS NOT NULL OR COALESCE(p.last_seen_status, '')='missing')) AS missing_count,
                       (SELECT COUNT(*) FROM batch_products p WHERE p.batch_id=b.batch_id AND p.deleted_at IS NULL AND COALESCE(p.last_seen_status, '') IN ('unknown', 'document_mismatch')) AS unknown_count,
                       (SELECT COUNT(*) FROM batch_products p WHERE p.batch_id=b.batch_id AND p.deleted_at IS NULL AND COALESCE(p.last_seen_status, 'exists')='exists') AS product_count
                FROM batches b
                ORDER BY b.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM batch_events WHERE batch_id=? ORDER BY id",
                (batch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_requests(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM batch_requests WHERE batch_id=? ORDER BY created_at",
                (batch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_products(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM batch_products WHERE batch_id=? ORDER BY id",
                (batch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_active_revit_element_ids(self, batch_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT product_ref FROM batch_products WHERE batch_id=? AND product_type='revit_element' AND deleted_at IS NULL AND COALESCE(last_seen_status, 'exists')='exists'",
                (batch_id,),
            ).fetchall()
        return [str(row["product_ref"]) for row in rows]

    def list_active_revit_products(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM batch_products
                WHERE batch_id=?
                  AND product_type='revit_element'
                  AND deleted_at IS NULL
                  AND COALESCE(last_seen_status, 'exists') IN ('exists', 'unknown', 'document_mismatch')
                ORDER BY id
                """,
                (batch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_product_sync_status(
        self,
        batch_id: str,
        existing_ids: Iterable[str],
        missing_ids: Iterable[str],
        unknown_ids: Iterable[str] = (),
        *,
        document_mismatch_ids: Iterable[str] = (),
        relinked: Iterable[dict[str, Any]] = (),
        element_states: Iterable[dict[str, Any]] = (),
    ) -> None:
        existing = {str(item) for item in existing_ids}
        missing = {str(item) for item in missing_ids}
        unknown = {str(item) for item in unknown_ids}
        document_mismatch = {str(item) for item in document_mismatch_ids}
        now = _now()
        with self._connect() as conn:
            for item in relinked:
                old_id = _as_element_id(item.get("old_element_id"))
                new_id = _as_element_id(item.get("element_id") or item.get("new_element_id"))
                unique_id = _as_text(item.get("unique_id"))
                if not old_id or not new_id:
                    continue
                conn.execute(
                    """
                    UPDATE batch_products
                    SET product_ref=?, element_unique_id=COALESCE(NULLIF(?, ''), element_unique_id), last_seen_status=?, last_checked_at=?
                    WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL
                    """,
                    (new_id, unique_id, "exists", now, batch_id, old_id),
                )
            for element_id in existing:
                conn.execute(
                    "UPDATE batch_products SET last_seen_status=?, last_checked_at=? WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL",
                    ("exists", now, batch_id, element_id),
                )
            for element_id in missing:
                conn.execute(
                    "UPDATE batch_products SET last_seen_status=?, last_checked_at=? WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL",
                    ("missing", now, batch_id, element_id),
                )
            for element_id in unknown:
                conn.execute(
                    "UPDATE batch_products SET last_seen_status=?, last_checked_at=? WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL",
                    ("unknown", now, batch_id, element_id),
                )
            for element_id in document_mismatch:
                conn.execute(
                    "UPDATE batch_products SET last_seen_status=?, last_checked_at=? WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL",
                    ("document_mismatch", now, batch_id, element_id),
                )
            for item in element_states:
                element_id = _as_element_id(item.get("element_id") or item.get("new_element_id") or item.get("old_element_id"))
                if not element_id:
                    continue
                conn.execute(
                    """
                    UPDATE batch_products
                    SET group_status=COALESCE(NULLIF(?, ''), group_status),
                        last_checked_at=?
                    WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL
                    """,
                    (_as_text(item.get("group_status")), now, batch_id, element_id),
                )

    def mark_products_deleted(self, batch_id: str, element_ids: Iterable[str]) -> None:
        ids = [str(item) for item in element_ids]
        if not ids:
            return
        with self._connect() as conn:
            for element_id in ids:
                conn.execute(
                    "UPDATE batch_products SET deleted_at=?, last_seen_status=?, last_checked_at=? WHERE batch_id=? AND product_type='revit_element' AND product_ref=? AND deleted_at IS NULL",
                    (_now(), "missing", _now(), batch_id, element_id),
                )


def get_active_batch_id() -> str | None:
    return _active_batch_id.get()


@contextmanager
def activate_batch(batch_id: str | None):
    token = _active_batch_id.set(batch_id)
    try:
        yield
    finally:
        _active_batch_id.reset(token)


@contextmanager
def batch_context(feature: str, action: str, title: str, input_summary: Any = None):
    store = BatchStore()
    batch = store.start_batch(feature, action, title, input_summary)
    with activate_batch(batch.batch_id):
        try:
            yield batch
        except Exception as exc:
            store.finish_batch(batch.batch_id, "failed", error_message=str(exc))
            store.add_event(batch.batch_id, "error", str(exc))
            raise
        else:
            store.finish_batch(batch.batch_id, "success")


def record_request_created(request_id: str, action: str, payload: dict[str, Any]) -> None:
    batch_id = get_active_batch_id()
    if not batch_id:
        return
    BatchStore().record_request(batch_id, request_id, action, payload)


def record_request_succeeded(request_id: str, payload: dict[str, Any]) -> None:
    BatchStore().finish_request(request_id, "success", response_payload=payload)


def record_request_failed(request_id: str, message: str) -> None:
    BatchStore().finish_request(request_id, "failed", error_message=message)
