import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).parent
QUEUE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR)))
    / "RevitFamilyClassifier"
    / "runtime"
    / "queue"
)
REQUEST_DIR = QUEUE_DIR / "requests"
RESPONSE_DIR = QUEUE_DIR / "responses"
ERROR_DIR = QUEUE_DIR / "errors"
HEARTBEAT_FILE = QUEUE_DIR / "listener_heartbeat.json"


@dataclass(frozen=True)
class QueueRequest:
    request_id: str
    rfa_path: str
    action: str = "read_metadata"


def ensure_queue_dirs() -> None:
    for path in (REQUEST_DIR, RESPONSE_DIR, ERROR_DIR):
        path.mkdir(parents=True, exist_ok=True)


def create_request(rfa_path: str) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(request_id=str(uuid.uuid4()), rfa_path=rfa_path)
    payload = {
        "request_id": request.request_id,
        "rfa_path": request.rfa_path,
        "action": request.action,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_add_parameters_request(rfa_path: str, parameters: list[dict]) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path=rfa_path,
        action="add_missing_string_parameters",
    )
    payload = {
        "request_id": request.request_id,
        "rfa_path": request.rfa_path,
        "action": request.action,
        "parameters": parameters,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_set_string_values_request(rfa_path: str, values: dict[str, str]) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path=rfa_path,
        action="set_string_parameter_values",
    )
    payload = {
        "request_id": request.request_id,
        "rfa_path": request.rfa_path,
        "action": request.action,
        "values": values,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_scan_project_families_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_project_families",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_export_project_families_request(
    family_ids: list[int | str],
    output_dir: str,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="export_project_families",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "family_ids": [str(item) for item in family_ids],
        "output_dir": output_dir,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_point_placement_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_point_placement_context",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_scan_cad_block_points_request(
    import_id: str | int,
    block_filter: str,
    limit: int,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_cad_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "block_filter": block_filter,
        "limit": limit,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_list_cad_block_names_request(import_id: str | int) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_cad_block_names",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_get_cad_import_path_request(import_id: str | int) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="get_cad_import_path",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_transform_dwg_block_points_request(
    import_id: str | int,
    points: list[dict],
    limit: int,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="transform_dwg_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "points": points,
        "limit": limit,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_place_cad_block_points_request(
    *,
    import_id: str | int,
    symbol_id: str | int,
    level_id: str | int,
    block_filter: str,
    limit: int,
    offset_mm: float,
    duplicate_tolerance_mm: float,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="place_cad_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "symbol_id": str(symbol_id),
        "level_id": str(level_id),
        "block_filter": block_filter,
        "limit": limit,
        "offset_mm": offset_mm,
        "duplicate_tolerance_mm": duplicate_tolerance_mm,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_place_dwg_block_points_request(
    *,
    import_id: str | int,
    symbol_id: str | int,
    level_id: str | int,
    points: list[dict],
    offset_mm: float,
    duplicate_tolerance_mm: float,
    preview_group_id: str | int | None = None,
    preview_origin: dict | None = None,
    delete_preview_after_place: bool = True,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="place_dwg_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "symbol_id": str(symbol_id),
        "level_id": str(level_id),
        "points": points,
        "offset_mm": offset_mm,
        "duplicate_tolerance_mm": duplicate_tolerance_mm,
        "preview_group_id": str(preview_group_id or ""),
        "preview_origin": preview_origin or {},
        "delete_preview_after_place": delete_preview_after_place,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_dwg_preview_markers_request(
    *,
    import_id: str | int,
    level_id: str | int,
    points: list[dict],
    offset_mm: float,
    marker_size_mm: float = 150,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_dwg_preview_markers",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "level_id": str(level_id),
        "points": points,
        "offset_mm": offset_mm,
        "marker_size_mm": marker_size_mm,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_fire_branch_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_fire_branch_context",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_fire_branch_selection_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="read_fire_branch_selection",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_fire_branch_pipes_request(
    *,
    main_pipe_id: str | int,
    sprinkler_ids: list[str | int],
    pipe_type_id: str | int,
    system_type_id: str | int,
    level_id: str | int,
    diameter_mm: float,
    branch_offset_cm: float,
    height_reference: str,
    preview_group_id: str | int | None = None,
    delete_preview_after_create: bool = True,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_fire_branch_pipes",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "main_pipe_id": str(main_pipe_id),
        "sprinkler_ids": [str(item) for item in sprinkler_ids],
        "pipe_type_id": str(pipe_type_id),
        "system_type_id": str(system_type_id),
        "level_id": str(level_id),
        "diameter_mm": diameter_mm,
        "branch_offset_cm": branch_offset_cm,
        "height_reference": height_reference,
        "delete_preview_after_create": delete_preview_after_create,
    }
    if preview_group_id:
        payload["preview_group_id"] = str(preview_group_id)
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_fire_branch_preview_request(
    *,
    main_pipe_id: str | int,
    sprinkler_ids: list[str | int],
    level_id: str | int,
    branch_offset_cm: float,
    height_reference: str,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_fire_branch_preview",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "main_pipe_id": str(main_pipe_id),
        "sprinkler_ids": [str(item) for item in sprinkler_ids],
        "level_id": str(level_id),
        "branch_offset_cm": branch_offset_cm,
        "height_reference": height_reference,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_opening_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_opening_context",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_scan_opening_candidates_request(
    *,
    link_id: str | int,
    mep_types: list[str],
    host_types: list[str],
    clearance_mm: float,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_opening_candidates",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "link_id": str(link_id),
        "mep_types": mep_types,
        "host_types": host_types,
        "clearance_mm": clearance_mm,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_view_opening_candidate_request(
    *,
    candidate: dict,
    box_size_cm: float = 250,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="view_opening_candidate",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "candidate": candidate,
        "box_size_cm": box_size_cm,
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request


def create_place_opening_markers_request(
    *,
    candidates: list[dict],
    clear_existing: bool = True,
    view_name_prefix: str = "SC 預留套管平面",
    dimension_type_id: str | int | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="place_opening_markers",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "candidates": candidates,
        "clear_existing": clear_existing,
        "view_name_prefix": view_name_prefix,
        "dimension_type_id": "" if dimension_type_id is None else str(dimension_type_id),
    }
    (REQUEST_DIR / f"{request.request_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return request
