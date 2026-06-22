import json
from pathlib import Path
from typing import Any

from sc_revit.core.batch import BatchStore, DB_PATH
from xlsx_exporter import write_xlsx


BATCH_REPORT_HEADERS = [
    "section",
    "status",
    "time",
    "batch_id",
    "action",
    "element_id",
    "unique_id",
    "family",
    "type",
    "level",
    "group_status",
    "group_name",
    "document",
    "x",
    "y",
    "z",
    "detail",
]


def default_report_path(batch_id: str) -> Path:
    output_dir = DB_PATH.parent / "cad2bim_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{batch_id}.xlsx"


def export_cad_points_batch_report_xlsx(
    batch_id: str,
    output_path_or_dir: str | Path | None = None,
    *,
    store: BatchStore | None = None,
) -> Path:
    store = store or BatchStore()
    batch = _find_batch(store, batch_id)
    target = Path(output_path_or_dir) if output_path_or_dir else default_report_path(batch_id)
    if target.suffix.casefold() != ".xlsx":
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"{batch_id}.xlsx"
    else:
        output_path = target
        output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [BATCH_REPORT_HEADERS]
    rows.extend(_batch_rows(batch))
    rows.extend(_request_rows(store.list_requests(batch_id), batch_id))
    rows.extend(_product_rows(store.list_products(batch_id), batch_id))
    rows.extend(_event_rows(store.list_events(batch_id), batch_id))
    write_xlsx(output_path, "CAD2BIM Batch", rows)
    return output_path


def _find_batch(store: BatchStore, batch_id: str) -> dict[str, Any]:
    for batch in store.list_batches(limit=1000):
        if str(batch.get("batch_id")) == str(batch_id):
            return batch
    return {"batch_id": batch_id, "status": "unknown"}


def _batch_rows(batch: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            "batch",
            batch.get("status", ""),
            batch.get("created_at", ""),
            batch.get("batch_id", ""),
            batch.get("action", ""),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            _compact_json(
                {
                    "feature": batch.get("feature"),
                    "title": batch.get("title"),
                    "tracked_count": batch.get("tracked_count"),
                    "existing_count": batch.get("existing_count"),
                    "missing_count": batch.get("missing_count"),
                    "unknown_count": batch.get("unknown_count"),
                    "error": batch.get("error_message"),
                }
            ),
        ]
    ]


def _request_rows(requests: list[dict[str, Any]], batch_id: str) -> list[list[Any]]:
    rows = []
    for request in requests:
        rows.append(
            [
                "request",
                request.get("status", ""),
                request.get("created_at", ""),
                batch_id,
                request.get("action", ""),
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                request.get("error_message") or request.get("request_id", ""),
            ]
        )
    return rows


def _product_rows(products: list[dict[str, Any]], batch_id: str) -> list[list[Any]]:
    rows = []
    for product in products:
        rows.append(
            [
                "product",
                product.get("last_seen_status") or ("deleted" if product.get("deleted_at") else "exists"),
                product.get("last_checked_at") or product.get("created_at", ""),
                batch_id,
                "",
                product.get("product_ref", ""),
                product.get("element_unique_id", ""),
                product.get("family_name", "") or product.get("label", ""),
                product.get("type_name", ""),
                product.get("level_name", ""),
                product.get("group_status", ""),
                product.get("group_name", ""),
                product.get("document_path") or product.get("document_title", ""),
                product.get("location_x", ""),
                product.get("location_y", ""),
                product.get("location_z", ""),
                "",
            ]
        )
    return rows


def _event_rows(events: list[dict[str, Any]], batch_id: str) -> list[list[Any]]:
    rows = []
    for event in events:
        rows.append(
            [
                "event",
                event.get("level", ""),
                event.get("created_at", ""),
                batch_id,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                _compact_json({"message": event.get("message"), "detail": event.get("detail")}),
            ]
        )
    return rows


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
